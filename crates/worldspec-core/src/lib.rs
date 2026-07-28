//! Deterministic validation primitives for the WorldSpec 0.1 baseline.
//!
//! This crate validates document structure and selected cross-object invariants.
//! It does not compile simulator bundles or issue L2/L3 certificates.

mod diagnostic;
mod schema;
mod semantic;

pub use diagnostic::{Diagnostic, Severity, ValidationReport};
pub use schema::{SchemaCatalog, SchemaCatalogError};
pub use semantic::{validate_loss_report, validate_world_definition};

use serde_json::Value;
use std::path::Path;

/// Validate an instance against a named schema and its supported semantic rules.
pub fn validate_file(
    schema_dir: impl AsRef<Path>,
    schema_name: &str,
    instance: &Value,
    target_profile: Option<&Value>,
) -> Result<ValidationReport, SchemaCatalogError> {
    let catalog = SchemaCatalog::load(schema_dir)?;
    let mut diagnostics = catalog.validate(schema_name, instance)?;
    let schema_valid = diagnostics
        .iter()
        .all(|item| item.severity != Severity::Error);

    if schema_valid {
        match schema_name {
            "world-definition.schema.json" => {
                diagnostics.extend(validate_world_definition(instance));
            }
            "loss-report.schema.json" => {
                diagnostics.extend(validate_loss_report(instance, target_profile));
            }
            _ => {}
        }
    }

    Ok(ValidationReport::new(schema_name, diagnostics))
}
