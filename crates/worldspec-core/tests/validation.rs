use serde_json::Value;
use std::{fs, path::PathBuf};
use worldspec_core::validate_file;

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
