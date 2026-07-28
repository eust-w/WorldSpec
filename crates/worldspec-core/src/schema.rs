use crate::{Diagnostic, Severity};
use jsonschema::Registry;
use serde_json::Value;
use std::{
    collections::BTreeMap,
    error::Error,
    fmt::{Display, Formatter},
    fs,
    path::{Path, PathBuf},
};

/// Errors that prevent validation from running. Instance failures are diagnostics instead.
#[derive(Debug)]
pub enum SchemaCatalogError {
    ReadDirectory {
        path: PathBuf,
        source: std::io::Error,
    },
    ReadSchema {
        path: PathBuf,
        source: std::io::Error,
    },
    ParseSchema {
        path: PathBuf,
        source: serde_json::Error,
    },
    MissingSchemaId {
        path: PathBuf,
    },
    DuplicateSchemaId {
        id: String,
    },
    MissingSchema {
        name: String,
    },
    BuildRegistry {
        message: String,
    },
    BuildValidator {
        schema: String,
        message: String,
    },
}

impl Display for SchemaCatalogError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ReadDirectory { path, source } => {
                write!(
                    formatter,
                    "cannot read schema directory {}: {source}",
                    path.display()
                )
            }
            Self::ReadSchema { path, source } => {
                write!(formatter, "cannot read schema {}: {source}", path.display())
            }
            Self::ParseSchema { path, source } => {
                write!(
                    formatter,
                    "cannot parse schema {}: {source}",
                    path.display()
                )
            }
            Self::MissingSchemaId { path } => {
                write!(formatter, "schema {} has no string $id", path.display())
            }
            Self::DuplicateSchemaId { id } => write!(formatter, "duplicate schema $id: {id}"),
            Self::MissingSchema { name } => write!(formatter, "schema not found: {name}"),
            Self::BuildRegistry { message } => {
                write!(formatter, "cannot prepare schema registry: {message}")
            }
            Self::BuildValidator { schema, message } => {
                write!(formatter, "cannot build validator for {schema}: {message}")
            }
        }
    }
}

impl Error for SchemaCatalogError {}

/// Self-contained schema catalog. No network or implicit file retrieval is used.
pub struct SchemaCatalog {
    schemas: BTreeMap<String, Value>,
    registry: Registry<'static>,
}

impl SchemaCatalog {
    pub fn load(schema_dir: impl AsRef<Path>) -> Result<Self, SchemaCatalogError> {
        let schema_dir = schema_dir.as_ref();
        let entries =
            fs::read_dir(schema_dir).map_err(|source| SchemaCatalogError::ReadDirectory {
                path: schema_dir.to_path_buf(),
                source,
            })?;
        let mut paths = entries
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|path| {
                path.file_name()
                    .and_then(|name| name.to_str())
                    .is_some_and(|name| name.ends_with(".schema.json"))
            })
            .collect::<Vec<_>>();
        paths.sort();

        let mut schemas = BTreeMap::new();
        let mut ids = BTreeMap::new();
        for path in paths {
            let raw =
                fs::read_to_string(&path).map_err(|source| SchemaCatalogError::ReadSchema {
                    path: path.clone(),
                    source,
                })?;
            let schema: Value =
                serde_json::from_str(&raw).map_err(|source| SchemaCatalogError::ParseSchema {
                    path: path.clone(),
                    source,
                })?;
            let id = schema
                .get("$id")
                .and_then(Value::as_str)
                .ok_or_else(|| SchemaCatalogError::MissingSchemaId { path: path.clone() })?
                .to_owned();
            if ids.insert(id.clone(), schema.clone()).is_some() {
                return Err(SchemaCatalogError::DuplicateSchemaId { id });
            }
            let name = path
                .file_name()
                .expect("schema path has a file name")
                .to_string_lossy()
                .into_owned();
            schemas.insert(name, schema);
        }

        let mut registry = Registry::new();
        for (id, schema) in ids {
            registry =
                registry
                    .add(id, schema)
                    .map_err(|error| SchemaCatalogError::BuildRegistry {
                        message: error.to_string(),
                    })?;
        }
        let registry = registry
            .prepare()
            .map_err(|error| SchemaCatalogError::BuildRegistry {
                message: error.to_string(),
            })?;

        Ok(Self { schemas, registry })
    }

    pub fn validate(
        &self,
        schema_name: &str,
        instance: &Value,
    ) -> Result<Vec<Diagnostic>, SchemaCatalogError> {
        let schema =
            self.schemas
                .get(schema_name)
                .ok_or_else(|| SchemaCatalogError::MissingSchema {
                    name: schema_name.to_owned(),
                })?;
        let validator = jsonschema::draft202012::options()
            .with_registry(&self.registry)
            .should_validate_formats(true)
            .build(schema)
            .map_err(|error| SchemaCatalogError::BuildValidator {
                schema: schema_name.to_owned(),
                message: error.to_string(),
            })?;

        Ok(validator
            .iter_errors(instance)
            .map(|error| Diagnostic {
                code: "SCHEMA_VALIDATION_ERROR".to_owned(),
                severity: Severity::Error,
                message: error.to_string(),
                path: Some(error.instance_path().to_string()),
                object_ref: None,
            })
            .collect())
    }
}
