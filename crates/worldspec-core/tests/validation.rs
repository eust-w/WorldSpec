use serde_json::Value;
use std::{fs, path::PathBuf};
use worldspec_core::{
    validate_build_manifest, validate_certificate, validate_conformance_report, validate_file,
    validate_runtime_record, validate_task_profile, validate_task_run_report,
    validate_world_definition,
};

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("crate has workspace parent")
        .parent()
        .expect("workspace has repository parent")
        .to_path_buf()
}

fn read(relative: &str) -> Value {
    let path = root().join(relative);
    let raw = fs::read_to_string(&path)
        .unwrap_or_else(|error| panic!("cannot read {}: {error}", path.display()));
    serde_json::from_str(&raw)
        .unwrap_or_else(|error| panic!("cannot parse {}: {error}", path.display()))
}

fn codes(report: &worldspec_core::ValidationReport) -> Vec<&str> {
    report
        .diagnostics
        .iter()
        .map(|diagnostic| diagnostic.code.as_str())
        .collect()
}

#[test]
fn positive_world_examples_are_valid() {
    for relative in [
        "examples/minimal-cube/world.json",
        "examples/hollow-mug/world.json",
        "examples/articulated-drawer/world.json",
    ] {
        let report = validate_file(
            root().join("schemas/0.1"),
            "world-definition.schema.json",
            &read(relative),
            None,
        )
        .expect("validator should run");
        assert!(report.valid, "{relative}: {:?}", report.diagnostics);
    }
}

#[test]
fn illegal_id_is_rejected_by_schema() {
    let report = validate_file(
        root().join("schemas/0.1"),
        "world-definition.schema.json",
        &read("examples/negative/illegal-id/world.json"),
        None,
    )
    .expect("validator should run");
    assert!(!report.valid);
    assert!(codes(&report).contains(&"SCHEMA_VALIDATION_ERROR"));
}

#[test]
fn frame_cycle_is_rejected_semantically() {
    let report = validate_file(
        root().join("schemas/0.1"),
        "world-definition.schema.json",
        &read("examples/negative/frame-cycle/world.json"),
        None,
    )
    .expect("validator should run");
    assert!(!report.valid);
    assert!(codes(&report).contains(&"WS_INV_009_FRAME_CYCLE"));
}

#[test]
fn missing_claim_is_rejected_semantically() {
    let report = validate_file(
        root().join("schemas/0.1"),
        "world-definition.schema.json",
        &read("examples/negative/missing-evidence/world.json"),
        None,
    )
    .expect("validator should run");
    assert!(!report.valid);
    assert!(codes(&report).contains(&"WS_INV_032_MISSING_CLAIM"));
}

#[test]
fn silent_downgrade_is_rejected_semantically() {
    let report = validate_file(
        root().join("schemas/0.1"),
        "loss-report.schema.json",
        &read("examples/negative/silent-downgrade/loss-report.json"),
        Some(&read(
            "examples/negative/silent-downgrade/target-profile.json",
        )),
    )
    .expect("validator should run");
    assert!(!report.valid);
    let found = codes(&report);
    assert!(found.contains(&"LOSS_COVERAGE_MISMATCH"));
    assert!(found.contains(&"LOSS_UNREPORTED_NON_EXACT_CAPABILITY"));
}

#[test]
fn complete_loss_report_is_valid() {
    let report = validate_file(
        root().join("schemas/0.1"),
        "loss-report.schema.json",
        &read("examples/minimal-cube/loss-report.json"),
        Some(&read("examples/minimal-cube/target-profile.json")),
    )
    .expect("validator should run");
    assert!(report.valid, "{:?}", report.diagnostics);
}

#[test]
fn diagnostics_are_deterministically_sorted() {
    let report = validate_file(
        root().join("schemas/0.1"),
        "world-definition.schema.json",
        &read("examples/negative/frame-cycle/world.json"),
        None,
    )
    .expect("validator should run");
    let mut sorted = report.diagnostics.clone();
    sorted.sort_by(|left, right| {
        (&left.code, &left.path, &left.object_ref, &left.message).cmp(&(
            &right.code,
            &right.path,
            &right.object_ref,
            &right.message,
        ))
    });
    assert_eq!(report.diagnostics, sorted);
}

#[test]
fn runtime_record_rejects_time_regression_and_wrong_snapshot() {
    let mut record = read("examples/minimal-cube/runtime-record.json");
    record["initialSnapshot"]["worldDefinitionDigest"] =
        Value::String(format!("sha256:{}", "9".repeat(64)));
    record["stateStreams"][0]["samples"][1]["timestamp"] = Value::from(-0.01);
    let found = validate_runtime_record(&record);
    let found = found
        .iter()
        .map(|diagnostic| diagnostic.code.as_str())
        .collect::<Vec<_>>();
    assert!(found.contains(&"WS_INV_031_SNAPSHOT_WORLD_DIGEST_MISMATCH"));
    assert!(found.contains(&"WS_INV_029_TIMESTAMP_NOT_MONOTONIC"));
}

#[test]
fn build_manifest_rejects_ambiguous_model_selection() {
    let mut manifest = read("examples/minimal-cube/build-manifest.json");
    let duplicate = manifest["modelSelections"][0].clone();
    manifest["modelSelections"]
        .as_array_mut()
        .unwrap()
        .push(duplicate);
    let found = validate_build_manifest(&manifest);
    assert!(
        found
            .iter()
            .any(|diagnostic| diagnostic.code == "WS_INV_019_MODEL_SELECTION_AMBIGUOUS")
    );
}

#[test]
fn invalidated_certificate_cannot_remain_valid() {
    let mut certificate = read("examples/minimal-cube/certificate.json");
    certificate["valid"] = Value::Bool(true);
    certificate["invalidatedBy"] = serde_json::json!([
        "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    ]);
    let found = validate_certificate(&certificate);
    assert!(
        found
            .iter()
            .any(|diagnostic| diagnostic.code == "CERT_INVALIDATION_CONFLICT")
    );
}

#[test]
fn not_executed_conformance_cannot_report_runtime_passes() {
    let mut report = read("examples/minimal-cube/conformance-report.json");
    report["tests"][0]["result"] = Value::String("pass".to_owned());
    report["summary"] = serde_json::json!({
        "passed": 1,
        "failed": 0,
        "unknown": 0,
        "notRun": 0,
        "overall": "pass"
    });
    let found = validate_conformance_report(&report);
    assert!(
        found
            .iter()
            .any(|diagnostic| diagnostic.code == "CONFORMANCE_EXECUTION_EVIDENCE_CONFLICT")
    );
}

#[test]
fn derivation_cannot_upgrade_evidence_authority() {
    let mut world = read("examples/minimal-cube/world.json");
    world["evidenceGraph"]["claims"][0]["derivedBy"] =
        Value::String("derivation://cube/invalid-upgrade".to_owned());
    world["evidenceGraph"]["claims"][0]["status"] = Value::String("measured".to_owned());
    world["evidenceGraph"]["derivations"] = serde_json::json!([
        {
            "id": "derivation://cube/invalid-upgrade",
            "method": "copy",
            "methodVersion": "0.1.0",
            "inputs": ["claim://cube/dimensions"],
            "outputs": ["claim://cube/mass"],
            "assumptions": []
        }
    ]);
    let found = validate_world_definition(&world);
    assert!(
        found
            .iter()
            .any(|diagnostic| diagnostic.code == "WS_INV_035_DERIVED_AUTHORITY_UPGRADE")
    );
}

#[test]
fn task_profile_rejects_impossible_success_threshold() {
    let mut task = read("examples/minimal-cube/task-profile.json");
    task["certification"]["requiredRuns"] = Value::from(4);
    task["certification"]["requiredSuccesses"] = Value::from(5);
    let found = validate_task_profile(&task);
    assert!(
        found
            .iter()
            .any(|diagnostic| diagnostic.code == "TASK_SUCCESS_REQUIREMENT_IMPOSSIBLE")
    );
}

#[test]
fn task_run_report_rejects_relabelled_summary_and_non_executed_pass() {
    let mut report = read("examples/minimal-cube/task-run-report.json");
    report["executionEvidence"] = Value::String("not_executed".to_owned());
    report["summary"]["total"] = Value::from(5);
    let found = validate_task_run_report(&report);
    let found = found
        .iter()
        .map(|diagnostic| diagnostic.code.as_str())
        .collect::<Vec<_>>();
    assert!(found.contains(&"TASK_RUN_SUMMARY_MISMATCH"));
    assert!(found.contains(&"TASK_RUN_EXECUTION_EVIDENCE_CONFLICT"));
}
