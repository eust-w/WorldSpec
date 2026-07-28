//! Local content-addressed storage and recoverable single-node job index.

use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fmt::{Display, Formatter},
    fs,
    io::{self, Write},
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
    time::{SystemTime, UNIX_EPOCH},
};

#[derive(Debug)]
pub enum CasError {
    Io(io::Error),
    Sql(rusqlite::Error),
    InvalidDigest(String),
    Poisoned,
}

impl Display for CasError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "CAS I/O error: {error}"),
            Self::Sql(error) => write!(formatter, "CAS database error: {error}"),
            Self::InvalidDigest(value) => write!(formatter, "invalid SHA-256 digest: {value}"),
            Self::Poisoned => write!(formatter, "CAS database lock is poisoned"),
        }
    }
}

impl std::error::Error for CasError {}

impl From<io::Error> for CasError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<rusqlite::Error> for CasError {
    fn from(value: rusqlite::Error) -> Self {
        Self::Sql(value)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum JobStatus {
    Queued,
    Running,
    Succeeded,
    Failed,
    Cancelled,
    TimedOut,
}

impl JobStatus {
    fn as_str(&self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Running => "running",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::TimedOut => "timed_out",
        }
    }

    fn parse(value: &str) -> Self {
        match value {
            "running" => Self::Running,
            "succeeded" => Self::Succeeded,
            "failed" => Self::Failed,
            "cancelled" => Self::Cancelled,
            "timed_out" => Self::TimedOut,
            _ => Self::Queued,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct JobRecord {
    pub id: String,
    pub operation: String,
    pub status: JobStatus,
    pub spec_digest: String,
    pub result_digest: Option<String>,
    pub created_at_unix_ms: i64,
    pub updated_at_unix_ms: i64,
    pub cancel_requested: bool,
}

#[derive(Clone)]
pub struct Cas {
    root: PathBuf,
    database: Arc<Mutex<Connection>>,
}

fn unix_ms() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as i64
}

fn digest_hex(digest: &str) -> Result<&str, CasError> {
    let Some(hex) = digest.strip_prefix("sha256:") else {
        return Err(CasError::InvalidDigest(digest.to_owned()));
    };
    if hex.len() != 64 || !hex.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(CasError::InvalidDigest(digest.to_owned()));
    }
    Ok(hex)
}

impl Cas {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, CasError> {
        let root = root.as_ref().to_path_buf();
        fs::create_dir_all(root.join("objects/sha256"))?;
        fs::create_dir_all(root.join("tmp"))?;
        let connection = Connection::open(root.join("index.sqlite3"))?;
        connection.pragma_update(None, "journal_mode", "WAL")?;
        connection.pragma_update(None, "foreign_keys", "ON")?;
        connection.execute_batch(
            "
            CREATE TABLE IF NOT EXISTS blobs (
                digest TEXT PRIMARY KEY,
                size_bytes INTEGER NOT NULL,
                media_type TEXT,
                created_at_ms INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                operation TEXT NOT NULL,
                status TEXT NOT NULL,
                spec_digest TEXT NOT NULL,
                result_digest TEXT,
                created_at_ms INTEGER NOT NULL,
                updated_at_ms INTEGER NOT NULL,
                cancel_requested INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS job_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                timestamp_ms INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );
            CREATE TABLE IF NOT EXISTS refs (
                name TEXT PRIMARY KEY,
                digest TEXT NOT NULL,
                kind TEXT NOT NULL,
                updated_at_ms INTEGER NOT NULL
            );
            ",
        )?;
        Ok(Self {
            root,
            database: Arc::new(Mutex::new(connection)),
        })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    pub fn object_path(&self, digest: &str) -> Result<PathBuf, CasError> {
        let hex = digest_hex(digest)?.to_ascii_lowercase();
        Ok(self
            .root
            .join("objects/sha256")
            .join(&hex[..2])
            .join(&hex[2..]))
    }

    pub fn put_bytes(&self, bytes: &[u8], media_type: Option<&str>) -> Result<String, CasError> {
        let digest = format!("sha256:{:x}", Sha256::digest(bytes));
        let target = self.object_path(&digest)?;
        if !target.exists() {
            let parent = target.parent().expect("CAS object path has parent");
            fs::create_dir_all(parent)?;
            let temporary = self.root.join("tmp").join(format!(
                "{}-{}",
                std::process::id(),
                digest.strip_prefix("sha256:").unwrap_or_default()
            ));
            let mut file = fs::File::create(&temporary)?;
            file.write_all(bytes)?;
            file.sync_all()?;
            match fs::rename(&temporary, &target) {
                Ok(()) => {}
                Err(error) if target.exists() => {
                    let _ = fs::remove_file(&temporary);
                    if !target.exists() {
                        return Err(CasError::Io(error));
                    }
                }
                Err(error) => return Err(CasError::Io(error)),
            }
        }
        let connection = self.database.lock().map_err(|_| CasError::Poisoned)?;
        connection.execute(
            "INSERT OR IGNORE INTO blobs(digest,size_bytes,media_type,created_at_ms)
             VALUES (?1,?2,?3,?4)",
            params![digest, bytes.len() as i64, media_type, unix_ms()],
        )?;
        Ok(digest)
    }

    pub fn get_bytes(&self, digest: &str) -> Result<Vec<u8>, CasError> {
        Ok(fs::read(self.object_path(digest)?)?)
    }

    pub fn verify(&self, digest: &str) -> Result<bool, CasError> {
        let bytes = match self.get_bytes(digest) {
            Ok(bytes) => bytes,
            Err(CasError::Io(error)) if error.kind() == io::ErrorKind::NotFound => {
                return Ok(false);
            }
            Err(error) => return Err(error),
        };
        Ok(format!("sha256:{:x}", Sha256::digest(bytes)) == digest.to_ascii_lowercase())
    }

    pub fn put_ref(&self, name: &str, kind: &str, digest: &str) -> Result<(), CasError> {
        digest_hex(digest)?;
        let connection = self.database.lock().map_err(|_| CasError::Poisoned)?;
        connection.execute(
            "INSERT INTO refs(name,digest,kind,updated_at_ms) VALUES (?1,?2,?3,?4)
             ON CONFLICT(name) DO UPDATE SET digest=excluded.digest,
             kind=excluded.kind,updated_at_ms=excluded.updated_at_ms",
            params![name, digest, kind, unix_ms()],
        )?;
        Ok(())
    }

    pub fn resolve_ref(&self, name: &str) -> Result<Option<String>, CasError> {
        let connection = self.database.lock().map_err(|_| CasError::Poisoned)?;
        Ok(connection
            .query_row("SELECT digest FROM refs WHERE name=?1", [name], |row| {
                row.get(0)
            })
            .optional()?)
    }

    pub fn create_job(
        &self,
        id: &str,
        operation: &str,
        spec_digest: &str,
    ) -> Result<JobRecord, CasError> {
        digest_hex(spec_digest)?;
        let now = unix_ms();
        let connection = self.database.lock().map_err(|_| CasError::Poisoned)?;
        connection.execute(
            "INSERT INTO jobs(id,operation,status,spec_digest,created_at_ms,updated_at_ms)
             VALUES (?1,?2,'queued',?3,?4,?4)",
            params![id, operation, spec_digest, now],
        )?;
        drop(connection);
        self.get_job(id)?
            .ok_or_else(|| CasError::Sql(rusqlite::Error::QueryReturnedNoRows))
    }

    pub fn get_job(&self, id: &str) -> Result<Option<JobRecord>, CasError> {
        let connection = self.database.lock().map_err(|_| CasError::Poisoned)?;
        Ok(connection
            .query_row(
                "SELECT id,operation,status,spec_digest,result_digest,created_at_ms,
                 updated_at_ms,cancel_requested FROM jobs WHERE id=?1",
                [id],
                |row| {
                    Ok(JobRecord {
                        id: row.get(0)?,
                        operation: row.get(1)?,
                        status: JobStatus::parse(&row.get::<_, String>(2)?),
                        spec_digest: row.get(3)?,
                        result_digest: row.get(4)?,
                        created_at_unix_ms: row.get(5)?,
                        updated_at_unix_ms: row.get(6)?,
                        cancel_requested: row.get::<_, i64>(7)? != 0,
                    })
                },
            )
            .optional()?)
    }

    pub fn set_job_status(
        &self,
        id: &str,
        status: JobStatus,
        result_digest: Option<&str>,
    ) -> Result<(), CasError> {
        if let Some(digest) = result_digest {
            digest_hex(digest)?;
        }
        let connection = self.database.lock().map_err(|_| CasError::Poisoned)?;
        connection.execute(
            "UPDATE jobs SET status=?2,result_digest=?3,updated_at_ms=?4 WHERE id=?1",
            params![id, status.as_str(), result_digest, unix_ms()],
        )?;
        Ok(())
    }

    pub fn request_cancel(&self, id: &str) -> Result<bool, CasError> {
        let connection = self.database.lock().map_err(|_| CasError::Poisoned)?;
        Ok(connection.execute(
            "UPDATE jobs SET cancel_requested=1,updated_at_ms=?2
             WHERE id=?1 AND status IN ('queued','running')",
            params![id, unix_ms()],
        )? > 0)
    }
}

#[cfg(test)]
mod tests {
    use super::{Cas, JobStatus};
    use std::{fs, time::SystemTime};

    fn temporary_root(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "worldspec-cas-{name}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(SystemTime::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ))
    }

    #[test]
    fn content_identity_is_deterministic_and_verified() {
        let root = temporary_root("identity");
        let cas = Cas::open(&root).unwrap();
        let first = cas.put_bytes(b"worldspec", Some("text/plain")).unwrap();
        let second = cas.put_bytes(b"worldspec", Some("text/plain")).unwrap();
        assert_eq!(first, second);
        assert!(cas.verify(&first).unwrap());
        assert_eq!(cas.get_bytes(&first).unwrap(), b"worldspec");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn job_state_survives_reopen() {
        let root = temporary_root("jobs");
        let digest = format!("sha256:{}", "a".repeat(64));
        {
            let cas = Cas::open(&root).unwrap();
            cas.create_job("job://test/1", "compile", &digest).unwrap();
            cas.set_job_status("job://test/1", JobStatus::Running, None)
                .unwrap();
        }
        let reopened = Cas::open(&root).unwrap();
        let record = reopened.get_job("job://test/1").unwrap().unwrap();
        assert_eq!(record.status, JobStatus::Running);
        assert!(reopened.request_cancel("job://test/1").unwrap());
        fs::remove_dir_all(root).unwrap();
    }
}
