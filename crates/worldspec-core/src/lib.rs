//! Deterministic validation primitives for the WorldSpec 0.1 baseline.
//!
//! This crate validates document structure and selected cross-object invariants.
//! It does not compile simulator bundles or issue L2/L3 certificates.

mod canonical;
mod diagnostic;
mod model;
mod schema;
mod semantic;

pub use canonical::{CanonicalError, canonical_json, canonical_sha256};
pub use diagnostic::{Diagnostic, Severity, ValidationReport};
pub use model::{
    ArtifactRef, BuildIntent, BuildManifest, Certificate, ConformanceReport, EvidenceGraph,
    LossEntry, LossReport, LossStatus, SourceBundle, TargetProfile, WorldDefinition,
};
pub use schema::{SchemaCatalog, SchemaCatalogError};
pub use semantic::{
    validate_build_manifest, validate_certificate, validate_conformance_report,
    validate_loss_report, validate_lowering_plan, validate_runtime_record,
    validate_world_definition,
};

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
            "build-manifest.schema.json" => {
                diagnostics.extend(validate_build_manifest(instance));
            }
            "lowering-plan.schema.json" => {
                diagnostics.extend(validate_lowering_plan(instance));
            }
            "runtime-record.schema.json" => {
                diagnostics.extend(validate_runtime_record(instance));
            }
            "certificate.schema.json" => {
                diagnostics.extend(validate_certificate(instance));
            }
            "conformance-report.schema.json" => {
                diagnostics.extend(validate_conformance_report(instance));
            }
            _ => {}
        }
    }

    Ok(ValidationReport::new(schema_name, diagnostics))
}
