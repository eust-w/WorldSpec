//! Loopback-first asynchronous WorldSpec job and artifact API.

use axum::{
    Json, Router,
    body::Body,
    extract::{Path, State},
    http::{HeaderValue, StatusCode, header},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use serde_json::{Value, json};
use std::{path::PathBuf, sync::Arc};
use worldspec_cas::{Cas, CasError};
use worldspec_core::{canonical_json, validate_file};

#[derive(Clone)]
pub struct AppState {
    pub cas: Cas,
    pub schema_dir: PathBuf,
}

#[derive(Debug)]
struct ApiError {
    status: StatusCode,
    message: String,
}

impl ApiError {
    fn bad_request(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            message: message.into(),
        }
    }

    fn not_found(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::NOT_FOUND,
            message: message.into(),
        }
    }

    fn internal(message: impl Into<String>) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            message: message.into(),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({"error": self.message}))).into_response()
    }
}

impl From<CasError> for ApiError {
    fn from(value: CasError) -> Self {
        Self::internal(value.to_string())
    }
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/healthz", get(health))
        .route("/v1/jobs", post(create_job))
        .route("/v1/jobs/{id}/cancel", post(cancel_job))
        .route("/v1/jobs/{id}", get(get_job))
        .route("/v1/artifacts/{digest}", get(get_artifact))
        .route("/v1/certificates/{id}", get(get_certificate))
        .with_state(Arc::new(state))
}

async fn health() -> Json<Value> {
    Json(json!({"status": "ok", "apiVersion": "v1"}))
}

async fn create_job(
    State(state): State<Arc<AppState>>,
    Json(spec): Json<Value>,
) -> Result<(StatusCode, Json<Value>), ApiError> {
    let report = validate_file(&state.schema_dir, "job.schema.json", &spec, None)
        .map_err(|error| ApiError::internal(error.to_string()))?;
    if !report.valid {
        return Err(ApiError::bad_request(
            serde_json::to_string(&report).unwrap_or_else(|_| "invalid JobSpec".to_owned()),
        ));
    }
    let id = spec
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| ApiError::bad_request("JobSpec.id is required"))?;
    let operation = spec
        .get("operation")
        .and_then(Value::as_str)
        .ok_or_else(|| ApiError::bad_request("JobSpec.operation is required"))?;
    let bytes = canonical_json(&spec).map_err(|error| ApiError::internal(error.to_string()))?;
    let digest = state
        .cas
        .put_bytes(&bytes, Some("application/vnd.worldspec.job+json"))?;
    let record = state
        .cas
        .create_job(id, operation, &digest)
        .map_err(|error| ApiError::bad_request(error.to_string()))?;
    Ok((StatusCode::ACCEPTED, Json(json!(record))))
}

async fn get_job(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
) -> Result<Json<Value>, ApiError> {
    let id = percent_decode_path(&id)?;
    let record = state
        .cas
        .get_job(&id)?
        .ok_or_else(|| ApiError::not_found(format!("job not found: {id}")))?;
    Ok(Json(json!(record)))
}

async fn cancel_job(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
) -> Result<Json<Value>, ApiError> {
    let id = percent_decode_path(&id)?;
    if !state.cas.request_cancel(&id)? {
        return Err(ApiError::not_found(format!(
            "job is absent or not cancellable: {id}"
        )));
    }
    let record = state
        .cas
        .get_job(&id)?
        .ok_or_else(|| ApiError::not_found(format!("job not found: {id}")))?;
    Ok(Json(json!(record)))
}

async fn get_artifact(
    State(state): State<Arc<AppState>>,
    Path(digest): Path<String>,
) -> Result<Response, ApiError> {
    let digest = format!("sha256:{digest}");
    let bytes = state
        .cas
        .get_bytes(&digest)
        .map_err(|_| ApiError::not_found(format!("artifact not found: {digest}")))?;
    let mut response = Response::new(Body::from(bytes));
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/octet-stream"),
    );
    response.headers_mut().insert(
        header::ETAG,
        HeaderValue::from_str(&format!("\"{digest}\""))
            .map_err(|error| ApiError::internal(error.to_string()))?,
    );
    Ok(response)
}

async fn get_certificate(
    State(state): State<Arc<AppState>>,
    Path(id): Path<String>,
) -> Result<Response, ApiError> {
    let id = percent_decode_path(&id)?;
    let digest = state
        .cas
        .resolve_ref(&id)?
        .ok_or_else(|| ApiError::not_found(format!("certificate not found: {id}")))?;
    let bytes = state.cas.get_bytes(&digest)?;
    let mut response = Response::new(Body::from(bytes));
    response.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/vnd.worldspec.certificate+json"),
    );
    Ok(response)
}

fn percent_decode_path(value: &str) -> Result<String, ApiError> {
    // Axum already percent-decodes path captures. The helper only rejects
    // control characters so opaque WorldSpec IDs can safely be used as keys.
    if value.chars().any(char::is_control) {
        return Err(ApiError::bad_request(
            "path identifier contains control characters",
        ));
    }
    Ok(value.to_owned())
}

#[cfg(test)]
mod tests {
    use super::{AppState, router};
    use axum::{
        body::{Body, to_bytes},
        http::{Request, StatusCode, header},
    };
    use std::time::{SystemTime, UNIX_EPOCH};
    use tower::ServiceExt;
    use worldspec_cas::Cas;

    fn root() -> std::path::PathBuf {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .parent()
            .unwrap()
            .to_path_buf()
    }

    fn temporary_root() -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "worldspec-server-test-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ))
    }

    #[tokio::test]
    async fn health_and_job_creation_are_live() {
        let temporary = temporary_root();
        let app = router(AppState {
            cas: Cas::open(&temporary).unwrap(),
            schema_dir: root().join("schemas/0.1"),
        });
        let response = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/healthz")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::OK);

        let job = include_str!("../../../examples/minimal-cube/job-spec.json");
        let response = app
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/v1/jobs")
                    .header(header::CONTENT_TYPE, "application/json")
                    .body(Body::from(job))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.status(), StatusCode::ACCEPTED);
        let body = to_bytes(response.into_body(), 1024 * 1024).await.unwrap();
        let record: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(record["status"], "queued");
        std::fs::remove_dir_all(temporary).unwrap();
    }
}
