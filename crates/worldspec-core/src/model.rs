//! Strict outer-envelope Rust mirrors of the normative JSON Schemas.
//!
//! Versioned component and relation payloads intentionally remain JSON values;
//! their type-specific schemas are resolved through their declared type URI.

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ArtifactRef {
    pub id: String,
    pub digest: String,
    pub media_type: String,
    pub path: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub size_bytes: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub role: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum LossStatus {
    Exact,
    Converted,
    Approximated,
    Baked,
    Emulated,
    Dropped,
    Unsupported,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LossEntry {
    pub id: String,
    pub source_ref: String,
    pub capability: String,
    pub status: LossStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub target_binding: Option<String>,
    pub rationale: String,
    pub consequence: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub diagnostics: Vec<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct LossReport {
    pub id: String,
    pub report_version: String,
    pub build_id: String,
    pub coverage: Value,
    pub entries: Vec<LossEntry>,
    pub summary: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SourceBundle {
    pub id: String,
    pub bundle_version: String,
    pub items: Vec<Value>,
    pub rights_ref: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub rights_digest: Option<String>,
    pub bundle_digest: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub native_payloads: Vec<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct WorldDefinition {
    pub id: String,
    pub spec_version: String,
    pub conventions: Value,
    pub root_entity: String,
    pub root_frame: String,
    pub entities: Vec<Value>,
    pub frames: Vec<Value>,
    pub components: Vec<Value>,
    pub relations: Vec<Value>,
    pub representations: Vec<Value>,
    pub models: Vec<Value>,
    pub evidence_graph: EvidenceGraph,
    pub clock_domains: Vec<Value>,
    pub state_channels: Vec<Value>,
    #[serde(default)]
    pub initial_state: Vec<Value>,
    #[serde(default)]
    pub native_payloads: Vec<Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub metadata: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceGraph {
    pub sources: Vec<Value>,
    pub claims: Vec<Value>,
    pub derivations: Vec<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TargetProfile {
    pub id: String,
    pub profile_version: String,
    pub target: String,
    pub runtime_version: String,
    pub platform: Value,
    pub capabilities: Vec<Value>,
    pub certification_tests: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub profile_digest: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuildIntent {
    pub id: String,
    pub intent_version: String,
    pub purpose: Vec<String>,
    pub priorities: Vec<String>,
    pub hard_requirements: Vec<String>,
    pub allowed_degradation: Vec<LossStatus>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub budgets: Option<Value>,
    pub evidence_selection: String,
}

#[cfg(test)]
mod tests {
    use super::{
        BuildIntent, BuildManifest, Certificate, ConformanceReport, ControlProfile, LossReport,
        PredicateProfile, RuntimeRecord, SourceBundle, TargetProfile, TaskProfile, TaskRunReport,
        WorldDefinition,
    };

    fn parse<T: serde::de::DeserializeOwned>(text: &str) {
        serde_json::from_str::<T>(text).unwrap();
    }

    #[test]
    fn rust_envelopes_accept_normative_examples() {
        parse::<WorldDefinition>(include_str!("../../../examples/minimal-cube/world.json"));
        parse::<TargetProfile>(include_str!(
            "../../../examples/minimal-cube/target-profile.json"
        ));
        parse::<BuildIntent>(include_str!(
            "../../../examples/minimal-cube/build-intent.json"
        ));
        parse::<BuildManifest>(include_str!(
            "../../../examples/minimal-cube/build-manifest.json"
        ));
        parse::<Certificate>(include_str!(
            "../../../examples/minimal-cube/certificate.json"
        ));
        parse::<ConformanceReport>(include_str!(
            "../../../examples/minimal-cube/conformance-report.json"
        ));
        parse::<LossReport>(include_str!(
            "../../../examples/minimal-cube/loss-report.json"
        ));
        parse::<SourceBundle>(include_str!(
            "../../../examples/minimal-cube/source-bundle.json"
        ));
        parse::<TaskProfile>(include_str!(
            "../../../examples/minimal-cube/task-profile.json"
        ));
        parse::<PredicateProfile>(include_str!(
            "../../../examples/minimal-cube/predicate-profile.json"
        ));
        parse::<ControlProfile>(include_str!(
            "../../../examples/minimal-cube/control-profile.json"
        ));
        parse::<RuntimeRecord>(include_str!(
            "../../../examples/minimal-cube/runtime-record.json"
        ));
        parse::<TaskRunReport>(include_str!(
            "../../../examples/minimal-cube/task-run-report.json"
        ));
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BuildManifest {
    pub id: String,
    pub manifest_version: String,
    pub world_definition_digest: String,
    pub evidence_graph_digest: String,
    pub target_profile_digest: String,
    pub build_intent_digest: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub backend_calibration_digest: Option<String>,
    pub compiler: Value,
    pub model_selections: Vec<Value>,
    pub artifacts: Vec<ArtifactRef>,
    pub loss_report_digest: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub conformance_report_digest: Option<String>,
    pub lock_digest: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct Certificate {
    pub id: String,
    pub certificate_version: String,
    pub level: String,
    pub asset_digest: String,
    pub target_profile_digest: String,
    pub build_manifest_digest: String,
    pub loss_report_digest: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub conformance_report_digest: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub task_profile_digest: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub task_run_report_digest: Option<String>,
    #[serde(default)]
    pub evidence_statuses: Vec<String>,
    pub issued_at: String,
    pub issuer: String,
    pub valid: bool,
    #[serde(default)]
    pub invalidated_by: Vec<String>,
    pub signature_status: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub signature: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ConformanceReport {
    pub id: String,
    pub report_version: String,
    pub build_manifest_digest: String,
    pub target_profile_digest: String,
    pub target: String,
    pub execution_evidence: String,
    pub runner: Value,
    pub environment: Value,
    pub tested_artifacts: Vec<ArtifactRef>,
    pub tests: Vec<Value>,
    pub summary: Value,
    pub generated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TaskProfile {
    pub id: String,
    pub profile_version: String,
    pub world_digest: String,
    pub robot_ref: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub control_profile_digest: Option<String>,
    pub initial_state_digest: String,
    pub predicate_profiles: Vec<String>,
    pub goals: Vec<Value>,
    pub safety: Vec<Value>,
    pub execution: Value,
    pub certification: Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub profile_digest: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PredicateProfile {
    pub id: String,
    pub profile_version: String,
    pub predicate_id: String,
    pub evaluator_version: String,
    pub signature: Vec<Value>,
    pub requirements: Vec<String>,
    pub thresholds: Value,
    pub temporal: Value,
    pub output: Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub profile_digest: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ControlProfile {
    pub id: String,
    pub profile_version: String,
    pub clock_domain: String,
    pub update_rate_hz: f64,
    pub controllers: Vec<Value>,
    pub arbitration: String,
    pub safety: Value,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub profile_digest: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct RuntimeRecord {
    pub id: String,
    pub record_version: String,
    pub world_definition_digest: String,
    pub epoch: String,
    pub time_spec: Value,
    pub initial_snapshot: Value,
    pub state_streams: Vec<Value>,
    pub events: Vec<Value>,
    pub record_digest: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct TaskRunReport {
    pub id: String,
    pub report_version: String,
    pub task_profile_digest: String,
    pub world_definition_digest: String,
    pub target_profile_digest: String,
    pub build_manifest_digest: String,
    pub control_profile_digest: String,
    pub predicate_profile_digests: Vec<String>,
    pub initial_state_digest: String,
    pub execution_evidence: String,
    pub runner: Value,
    pub environment: Value,
    pub runs: Vec<Value>,
    pub summary: Value,
    pub generated_at: String,
}
