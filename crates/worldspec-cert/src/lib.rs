//! Digest-bound optional Ed25519 certificate signing.

use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use rand_core::OsRng;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::Path,
};
use worldspec_core::{CanonicalError, canonical_json, canonical_sha256};
use worldspec_predicate::{Truth, evaluate};

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct CertificationDiagnostic {
    pub code: String,
    pub message: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct CertificationAssessment {
    pub eligible: bool,
    pub diagnostics: Vec<CertificationDiagnostic>,
}

fn diagnostic(code: &str, message: impl Into<String>) -> CertificationDiagnostic {
    CertificationDiagnostic {
        code: code.to_owned(),
        message: message.into(),
    }
}

fn string<'a>(value: &'a Value, pointer: &str) -> Option<&'a str> {
    value.pointer(pointer).and_then(Value::as_str)
}

fn compare_digest(
    diagnostics: &mut Vec<CertificationDiagnostic>,
    code: &str,
    name: &str,
    declared: Option<&str>,
    actual: &str,
) {
    if declared != Some(actual) {
        diagnostics.push(diagnostic(
            code,
            format!(
                "{name} digest mismatch: declared {}, actual {actual}",
                declared.unwrap_or("<missing>")
            ),
        ));
    }
}

fn assess_build_bindings(
    certificate: &Value,
    world: &Value,
    target_profile: &Value,
    build_manifest: &Value,
    loss_report: &Value,
    conformance_report: &Value,
    expected_level: &str,
) -> Result<CertificationAssessment, CanonicalError> {
    let world_digest = canonical_sha256(world)?;
    let target_digest = canonical_sha256(target_profile)?;
    let manifest_digest = canonical_sha256(build_manifest)?;
    let loss_digest = canonical_sha256(loss_report)?;
    let conformance_digest = canonical_sha256(conformance_report)?;
    let evidence_digest = canonical_sha256(&world["evidenceGraph"])?;
    let mut diagnostics = Vec::new();

    compare_digest(
        &mut diagnostics,
        "CERT_ASSET_DIGEST_MISMATCH",
        "certificate asset",
        string(certificate, "/assetDigest"),
        &world_digest,
    );
    compare_digest(
        &mut diagnostics,
        "CERT_TARGET_PROFILE_DIGEST_MISMATCH",
        "certificate target profile",
        string(certificate, "/targetProfileDigest"),
        &target_digest,
    );
    compare_digest(
        &mut diagnostics,
        "CERT_BUILD_MANIFEST_DIGEST_MISMATCH",
        "certificate build manifest",
        string(certificate, "/buildManifestDigest"),
        &manifest_digest,
    );
    compare_digest(
        &mut diagnostics,
        "CERT_LOSS_REPORT_DIGEST_MISMATCH",
        "certificate loss report",
        string(certificate, "/lossReportDigest"),
        &loss_digest,
    );
    compare_digest(
        &mut diagnostics,
        "CERT_CONFORMANCE_REPORT_DIGEST_MISMATCH",
        "certificate conformance report",
        string(certificate, "/conformanceReportDigest"),
        &conformance_digest,
    );

    compare_digest(
        &mut diagnostics,
        "BUILD_WORLD_DIGEST_MISMATCH",
        "build world",
        string(build_manifest, "/worldDefinitionDigest"),
        &world_digest,
    );
    compare_digest(
        &mut diagnostics,
        "BUILD_EVIDENCE_DIGEST_MISMATCH",
        "build evidence graph",
        string(build_manifest, "/evidenceGraphDigest"),
        &evidence_digest,
    );
    compare_digest(
        &mut diagnostics,
        "BUILD_TARGET_PROFILE_DIGEST_MISMATCH",
        "build target profile",
        string(build_manifest, "/targetProfileDigest"),
        &target_digest,
    );
    compare_digest(
        &mut diagnostics,
        "BUILD_LOSS_REPORT_DIGEST_MISMATCH",
        "build loss report",
        string(build_manifest, "/lossReportDigest"),
        &loss_digest,
    );
    compare_digest(
        &mut diagnostics,
        "CONFORMANCE_BUILD_DIGEST_MISMATCH",
        "conformance build manifest",
        string(conformance_report, "/buildManifestDigest"),
        &manifest_digest,
    );
    compare_digest(
        &mut diagnostics,
        "CONFORMANCE_TARGET_DIGEST_MISMATCH",
        "conformance target profile",
        string(conformance_report, "/targetProfileDigest"),
        &target_digest,
    );

    if string(certificate, "/level") != Some(expected_level) {
        diagnostics.push(diagnostic(
            "CERT_LEVEL_MISMATCH",
            format!("this assessment only authorizes a {expected_level} certificate"),
        ));
    }
    if certificate.get("valid").and_then(Value::as_bool) != Some(true) {
        diagnostics.push(diagnostic(
            "CERT_NOT_MARKED_VALID",
            "an issued L2 certificate must explicitly be valid",
        ));
    }
    if !certificate
        .get("invalidatedBy")
        .and_then(Value::as_array)
        .is_some_and(Vec::is_empty)
    {
        diagnostics.push(diagnostic(
            "CERT_ALREADY_INVALIDATED",
            "an issued L2 certificate cannot have invalidation digests",
        ));
    }
    if conformance_report
        .get("executionEvidence")
        .and_then(Value::as_str)
        != Some("executed")
    {
        diagnostics.push(diagnostic(
            "CONFORMANCE_NOT_EXECUTED",
            "L2 requires an executed conformance report",
        ));
    }
    if string(conformance_report, "/summary/overall") != Some("pass") {
        diagnostics.push(diagnostic(
            "CONFORMANCE_NOT_PASSING",
            "L2 requires summary.overall=pass",
        ));
    }
    if loss_report
        .pointer("/coverage/complete")
        .and_then(Value::as_bool)
        != Some(true)
    {
        diagnostics.push(diagnostic(
            "LOSS_COVERAGE_INCOMPLETE",
            "L2 requires complete lowering coverage",
        ));
    }
    if loss_report
        .pointer("/summary/buildAllowed")
        .and_then(Value::as_bool)
        != Some(true)
    {
        diagnostics.push(diagnostic(
            "LOSS_BUILD_NOT_ALLOWED",
            "the LossReport does not allow certification of this build",
        ));
    }
    for entry in loss_report
        .get("entries")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        if matches!(
            entry.get("status").and_then(Value::as_str),
            Some("dropped" | "unsupported")
        ) {
            diagnostics.push(diagnostic(
                "LOSS_BLOCKS_L2",
                format!(
                    "loss entry {} is dropped or unsupported",
                    entry
                        .get("id")
                        .and_then(Value::as_str)
                        .unwrap_or("<unknown>")
                ),
            ));
        }
    }

    if string(conformance_report, "/target") != string(target_profile, "/target") {
        diagnostics.push(diagnostic(
            "CONFORMANCE_TARGET_MISMATCH",
            "conformance target does not match TargetProfile.target",
        ));
    }
    if string(conformance_report, "/environment/runtimeVersion")
        != string(target_profile, "/runtimeVersion")
    {
        diagnostics.push(diagnostic(
            "CONFORMANCE_RUNTIME_VERSION_MISMATCH",
            "conformance runtime version does not match the TargetProfile",
        ));
    }
    for field in ["os", "architecture"] {
        if string(conformance_report, &format!("/environment/{field}"))
            != string(target_profile, &format!("/platform/{field}"))
        {
            diagnostics.push(diagnostic(
                "CONFORMANCE_PLATFORM_MISMATCH",
                format!("conformance {field} does not match the TargetProfile"),
            ));
        }
    }

    let test_results = conformance_report
        .get("tests")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|test| {
            Some((
                test.get("id")?.as_str()?.to_owned(),
                test.get("result")?.as_str()?.to_owned(),
            ))
        })
        .collect::<BTreeMap<_, _>>();
    for required in target_profile
        .get("certificationTests")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
    {
        if test_results.get(required).map(String::as_str) != Some("pass") {
            diagnostics.push(diagnostic(
                "CONFORMANCE_REQUIRED_TEST_NOT_PASSING",
                format!("required certification test did not pass: {required}"),
            ));
        }
    }

    let manifest_artifacts = build_manifest
        .get("artifacts")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|artifact| {
            Some((
                artifact.get("id")?.as_str()?.to_owned(),
                (
                    artifact.get("digest")?.as_str()?.to_owned(),
                    artifact.get("path")?.as_str()?.to_owned(),
                ),
            ))
        })
        .collect::<BTreeMap<_, _>>();
    let tested_artifacts = conformance_report
        .get("testedArtifacts")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|artifact| {
            Some((
                artifact.get("id")?.as_str()?.to_owned(),
                (
                    artifact.get("digest")?.as_str()?.to_owned(),
                    artifact.get("path")?.as_str()?.to_owned(),
                ),
            ))
        })
        .collect::<BTreeMap<_, _>>();
    if manifest_artifacts != tested_artifacts {
        diagnostics.push(diagnostic(
            "CONFORMANCE_ARTIFACT_SET_MISMATCH",
            "testedArtifacts must exactly match BuildManifest.artifacts",
        ));
    }

    let declared_statuses = certificate
        .get("evidenceStatuses")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .collect::<std::collections::BTreeSet<_>>();
    let actual_statuses = world
        .pointer("/evidenceGraph/claims")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|claim| claim.get("status").and_then(Value::as_str))
        .collect::<std::collections::BTreeSet<_>>();
    if declared_statuses != actual_statuses {
        diagnostics.push(diagnostic(
            "CERT_EVIDENCE_STATUS_MISMATCH",
            "certificate evidenceStatuses must exactly summarize WorldDefinition claims",
        ));
    }

    Ok(CertificationAssessment {
        eligible: diagnostics.is_empty(),
        diagnostics,
    })
}

/// Verify all immutable document bindings required before an L2 certificate can be valid.
pub fn assess_l2_bindings(
    certificate: &Value,
    world: &Value,
    target_profile: &Value,
    build_manifest: &Value,
    loss_report: &Value,
    conformance_report: &Value,
) -> Result<CertificationAssessment, CanonicalError> {
    assess_build_bindings(
        certificate,
        world,
        target_profile,
        build_manifest,
        loss_report,
        conformance_report,
        "L2",
    )
}

fn string_set(value: &Value, pointer: &str) -> BTreeSet<String> {
    value
        .pointer(pointer)
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}

fn obligation_key(value: &Value) -> Option<(String, String, Vec<Value>)> {
    Some((
        value.get("id")?.as_str()?.to_owned(),
        value.get("predicate")?.as_str()?.to_owned(),
        value.get("arguments")?.as_array()?.clone(),
    ))
}

/// Verify the L2 build evidence plus task/control/predicate profiles and every
/// immutable runtime trace required for an L3 certificate.
#[allow(clippy::too_many_arguments)]
pub fn assess_l3_bindings(
    certificate: &Value,
    world: &Value,
    target_profile: &Value,
    build_manifest: &Value,
    loss_report: &Value,
    conformance_report: &Value,
    task_profile: &Value,
    control_profile: &Value,
    predicate_profiles: &[Value],
    initial_state: &Value,
    runtime_records: &[Value],
    task_run_report: &Value,
) -> Result<CertificationAssessment, CanonicalError> {
    let mut diagnostics = assess_build_bindings(
        certificate,
        world,
        target_profile,
        build_manifest,
        loss_report,
        conformance_report,
        "L3",
    )?
    .diagnostics;

    let world_digest = canonical_sha256(world)?;
    let target_digest = canonical_sha256(target_profile)?;
    let manifest_digest = canonical_sha256(build_manifest)?;
    let task_digest = canonical_sha256(task_profile)?;
    let control_digest = canonical_sha256(control_profile)?;
    let initial_state_digest = canonical_sha256(initial_state)?;
    let task_run_digest = canonical_sha256(task_run_report)?;
    let predicate_digests = predicate_profiles
        .iter()
        .map(canonical_sha256)
        .collect::<Result<BTreeSet<_>, _>>()?;

    for (code, name, declared, actual) in [
        (
            "CERT_TASK_PROFILE_DIGEST_MISMATCH",
            "certificate task profile",
            string(certificate, "/taskProfileDigest"),
            task_digest.as_str(),
        ),
        (
            "CERT_TASK_RUN_REPORT_DIGEST_MISMATCH",
            "certificate task run report",
            string(certificate, "/taskRunReportDigest"),
            task_run_digest.as_str(),
        ),
        (
            "TASK_WORLD_DIGEST_MISMATCH",
            "task world",
            string(task_profile, "/worldDigest"),
            world_digest.as_str(),
        ),
        (
            "TASK_CONTROL_PROFILE_DIGEST_MISMATCH",
            "task control profile",
            string(task_profile, "/controlProfileDigest"),
            control_digest.as_str(),
        ),
        (
            "TASK_INITIAL_STATE_DIGEST_MISMATCH",
            "task initial state",
            string(task_profile, "/initialStateDigest"),
            initial_state_digest.as_str(),
        ),
        (
            "TASK_RUN_TASK_PROFILE_DIGEST_MISMATCH",
            "task-run task profile",
            string(task_run_report, "/taskProfileDigest"),
            task_digest.as_str(),
        ),
        (
            "TASK_RUN_WORLD_DIGEST_MISMATCH",
            "task-run world",
            string(task_run_report, "/worldDefinitionDigest"),
            world_digest.as_str(),
        ),
        (
            "TASK_RUN_TARGET_DIGEST_MISMATCH",
            "task-run target profile",
            string(task_run_report, "/targetProfileDigest"),
            target_digest.as_str(),
        ),
        (
            "TASK_RUN_BUILD_DIGEST_MISMATCH",
            "task-run build manifest",
            string(task_run_report, "/buildManifestDigest"),
            manifest_digest.as_str(),
        ),
        (
            "TASK_RUN_CONTROL_DIGEST_MISMATCH",
            "task-run control profile",
            string(task_run_report, "/controlProfileDigest"),
            control_digest.as_str(),
        ),
        (
            "TASK_RUN_INITIAL_STATE_DIGEST_MISMATCH",
            "task-run initial state",
            string(task_run_report, "/initialStateDigest"),
            initial_state_digest.as_str(),
        ),
    ] {
        compare_digest(&mut diagnostics, code, name, declared, actual);
    }

    let declared_predicates = string_set(task_profile, "/predicateProfiles");
    if declared_predicates != predicate_digests {
        diagnostics.push(diagnostic(
            "TASK_PREDICATE_PROFILE_SET_MISMATCH",
            "TaskProfile.predicateProfiles must exactly match supplied PredicateProfile documents",
        ));
    }
    let report_predicates = string_set(task_run_report, "/predicateProfileDigests");
    if report_predicates != predicate_digests {
        diagnostics.push(diagnostic(
            "TASK_RUN_PREDICATE_PROFILE_SET_MISMATCH",
            "TaskRunReport predicate profiles do not match the supplied profiles",
        ));
    }

    let predicate_ids = predicate_profiles
        .iter()
        .filter_map(|profile| string(profile, "/predicateId"))
        .collect::<BTreeSet<_>>();
    let predicate_profile_by_id = predicate_profiles
        .iter()
        .filter_map(|profile| {
            string(profile, "/predicateId").map(|predicate| (predicate.to_owned(), profile))
        })
        .collect::<BTreeMap<_, _>>();
    for obligation in task_profile
        .get("goals")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .chain(
            task_profile
                .get("safety")
                .and_then(Value::as_array)
                .into_iter()
                .flatten(),
        )
    {
        if let Some(predicate) = string(obligation, "/predicate")
            && !predicate_ids.contains(predicate)
        {
            diagnostics.push(diagnostic(
                "TASK_PREDICATE_PROFILE_MISSING",
                format!("no supplied PredicateProfile defines {predicate}"),
            ));
        }
    }

    if string(task_run_report, "/executionEvidence") != Some("executed") {
        diagnostics.push(diagnostic(
            "TASK_RUN_NOT_EXECUTED",
            "L3 requires executed task-run evidence",
        ));
    }
    for field in ["os", "architecture"] {
        if string(task_run_report, &format!("/environment/{field}"))
            != string(target_profile, &format!("/platform/{field}"))
        {
            diagnostics.push(diagnostic(
                "TASK_RUN_PLATFORM_MISMATCH",
                format!("task-run {field} does not match TargetProfile"),
            ));
        }
    }
    if string(task_run_report, "/environment/runtimeVersion")
        != string(target_profile, "/runtimeVersion")
    {
        diagnostics.push(diagnostic(
            "TASK_RUN_RUNTIME_VERSION_MISMATCH",
            "task-run runtime version does not match TargetProfile",
        ));
    }
    if string(task_run_report, "/environment/runtime") != string(target_profile, "/target") {
        diagnostics.push(diagnostic(
            "TASK_RUN_RUNTIME_MISMATCH",
            "task-run runtime does not match TargetProfile.target",
        ));
    }

    let runs = task_run_report
        .get("runs")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or_default();
    let required_runs = task_profile
        .pointer("/certification/requiredRuns")
        .and_then(Value::as_u64)
        .unwrap_or_default() as usize;
    let required_successes = task_profile
        .pointer("/certification/requiredSuccesses")
        .and_then(Value::as_u64)
        .unwrap_or_default() as usize;
    if required_successes > required_runs {
        diagnostics.push(diagnostic(
            "TASK_SUCCESS_REQUIREMENT_IMPOSSIBLE",
            "requiredSuccesses exceeds requiredRuns",
        ));
    }
    if runs.len() != required_runs {
        diagnostics.push(diagnostic(
            "TASK_RUN_COUNT_MISMATCH",
            format!(
                "TaskProfile requires {required_runs} runs, report contains {}",
                runs.len()
            ),
        ));
    }
    let successful = runs
        .iter()
        .filter(|run| string(run, "/result") == Some("pass"))
        .count();
    if successful < required_successes {
        diagnostics.push(diagnostic(
            "TASK_SUCCESS_COUNT_INSUFFICIENT",
            format!(
                "TaskProfile requires {required_successes} successes, report contains {successful}"
            ),
        ));
    }
    let maximum_duration = task_profile
        .pointer("/execution/timeLimitSeconds")
        .and_then(Value::as_f64)
        .unwrap_or(f64::INFINITY);
    let fixed_initial = task_profile
        .pointer("/execution/fixedInitialState")
        .and_then(Value::as_bool)
        == Some(true);

    let expected_obligations = task_profile
        .get("goals")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|item| obligation_key(item).map(|key| (key.0, ("goal", key.1, key.2, item))))
        .chain(
            task_profile
                .get("safety")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(|item| {
                    obligation_key(item).map(|key| (key.0, ("safety", key.1, key.2, item)))
                }),
        )
        .collect::<BTreeMap<_, _>>();

    let runtime_by_digest = runtime_records
        .iter()
        .map(|record| canonical_sha256(record).map(|digest| (digest, record)))
        .collect::<Result<BTreeMap<_, _>, _>>()?;
    let report_runtime_digests = runs
        .iter()
        .filter_map(|run| string(run, "/runtimeRecordDigest").map(str::to_owned))
        .collect::<BTreeSet<_>>();
    if runtime_by_digest.keys().cloned().collect::<BTreeSet<_>>() != report_runtime_digests {
        diagnostics.push(diagnostic(
            "TASK_RUNTIME_RECORD_SET_MISMATCH",
            "supplied RuntimeRecord documents must exactly match TaskRunReport runs",
        ));
    }

    for (run_index, run) in runs.iter().enumerate() {
        if fixed_initial
            && string(run, "/initialStateDigest") != Some(initial_state_digest.as_str())
        {
            diagnostics.push(diagnostic(
                "TASK_RUN_INITIAL_STATE_MISMATCH",
                format!("run {run_index} does not use the locked initial state"),
            ));
        }
        if run
            .get("durationSeconds")
            .and_then(Value::as_f64)
            .is_none_or(|duration| !duration.is_finite() || duration > maximum_duration)
        {
            diagnostics.push(diagnostic(
                "TASK_RUN_TIME_LIMIT_EXCEEDED",
                format!("run {run_index} exceeds or lacks a finite task time limit"),
            ));
        }
        let runtime_digest = string(run, "/runtimeRecordDigest");
        let runtime_record =
            runtime_digest.and_then(|digest| runtime_by_digest.get(digest).copied());
        match runtime_record {
            Some(record) => {
                if string(record, "/worldDefinitionDigest") != Some(world_digest.as_str()) {
                    diagnostics.push(diagnostic(
                        "TASK_RUNTIME_WORLD_DIGEST_MISMATCH",
                        format!("runtime record for run {run_index} targets another world"),
                    ));
                }
                if string(record, "/epoch") != string(run, "/epoch") {
                    diagnostics.push(diagnostic(
                        "TASK_RUNTIME_EPOCH_MISMATCH",
                        format!("runtime record epoch differs for run {run_index}"),
                    ));
                }
                if string(record, "/initialSnapshot/worldDefinitionDigest")
                    != Some(world_digest.as_str())
                {
                    diagnostics.push(diagnostic(
                        "TASK_RUNTIME_SNAPSHOT_WORLD_MISMATCH",
                        format!("runtime snapshot for run {run_index} targets another world"),
                    ));
                }
                match record.pointer("/initialSnapshot/values") {
                    Some(values) => {
                        if canonical_sha256(values)? != initial_state_digest {
                            diagnostics.push(diagnostic(
                                "TASK_RUNTIME_INITIAL_STATE_MISMATCH",
                                format!(
                                    "runtime snapshot values for run {run_index} differ from the locked initial state"
                                ),
                            ));
                        }
                    }
                    None => diagnostics.push(diagnostic(
                        "TASK_RUNTIME_INITIAL_STATE_MISSING",
                        format!("runtime snapshot for run {run_index} has no values"),
                    )),
                }
            }
            None => diagnostics.push(diagnostic(
                "TASK_RUNTIME_RECORD_MISSING",
                format!("run {run_index} has no supplied immutable RuntimeRecord"),
            )),
        }

        let reported_obligations = run
            .get("obligations")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|item| string(item, "/obligationRef").map(|id| (id.to_owned(), item)))
            .collect::<BTreeMap<_, _>>();
        if reported_obligations.keys().collect::<BTreeSet<_>>()
            != expected_obligations.keys().collect::<BTreeSet<_>>()
        {
            diagnostics.push(diagnostic(
                "TASK_OBLIGATION_SET_MISMATCH",
                format!("run {run_index} does not report every declared obligation exactly once"),
            ));
        }
        for (id, (kind, predicate, arguments, source)) in &expected_obligations {
            let Some(actual) = reported_obligations.get(id) else {
                continue;
            };
            if string(actual, "/kind") != Some(kind)
                || string(actual, "/predicate") != Some(predicate)
                || actual.get("arguments").and_then(Value::as_array) != Some(arguments)
            {
                diagnostics.push(diagnostic(
                    "TASK_OBLIGATION_BINDING_MISMATCH",
                    format!("run {run_index} changes the binding for {id}"),
                ));
            }
            if *kind == "safety" {
                let must_remain = string(source, "/mustRemain");
                if string(actual, "/result") != Some("pass")
                    || string(actual, "/truth") != must_remain
                    || actual
                        .get("violationCount")
                        .and_then(Value::as_u64)
                        .unwrap_or_default()
                        != 0
                    || actual
                        .get("evaluatedForSeconds")
                        .and_then(Value::as_f64)
                        .unwrap_or_default()
                        < run
                            .get("durationSeconds")
                            .and_then(Value::as_f64)
                            .unwrap_or_default()
                {
                    diagnostics.push(diagnostic(
                        "TASK_SAFETY_OBLIGATION_FAILED",
                        format!("run {run_index} did not maintain safety obligation {id}"),
                    ));
                }
            } else if string(run, "/result") == Some("pass") {
                let required_hold = source
                    .get("holdForSeconds")
                    .and_then(Value::as_f64)
                    .unwrap_or_default();
                if string(actual, "/result") != Some("pass")
                    || string(actual, "/truth") != Some("true")
                    || actual
                        .get("evaluatedForSeconds")
                        .and_then(Value::as_f64)
                        .unwrap_or_default()
                        < required_hold
                {
                    diagnostics.push(diagnostic(
                        "TASK_GOAL_OBLIGATION_FAILED",
                        format!("passing run {run_index} lacks goal witness {id}"),
                    ));
                }
            }
            if actual
                .get("confidence")
                .and_then(Value::as_f64)
                .is_none_or(|value| !value.is_finite() || value <= 0.0)
            {
                diagnostics.push(diagnostic(
                    "TASK_OBLIGATION_CONFIDENCE_INVALID",
                    format!("run {run_index} obligation {id} has no positive confidence"),
                ));
            }
            let Some(profile) = predicate_profile_by_id.get(predicate) else {
                continue;
            };
            let evaluation = evaluate(
                predicate,
                profile,
                actual.get("metrics").unwrap_or(&Value::Null),
            );
            let evaluated_truth = match evaluation.truth {
                Truth::True => "true",
                Truth::False => "false",
                Truth::Unknown => "unknown",
            };
            if evaluated_truth == "unknown" {
                diagnostics.push(diagnostic(
                    "TASK_PREDICATE_EVIDENCE_UNKNOWN",
                    format!(
                        "run {run_index} obligation {id} cannot be recomputed from canonical metrics"
                    ),
                ));
            }
            if string(actual, "/truth") != Some(evaluated_truth) {
                diagnostics.push(diagnostic(
                    "TASK_PREDICATE_TRUTH_MISMATCH",
                    format!(
                        "run {run_index} obligation {id} reports truth {}, evaluator produced {evaluated_truth}",
                        string(actual, "/truth").unwrap_or("<missing>")
                    ),
                ));
            }
            match (
                actual.get("robustness").and_then(Value::as_f64),
                evaluation.robustness,
            ) {
                (Some(reported), Some(recomputed))
                    if (reported - recomputed).abs() <= f64::EPSILON => {}
                (None, None) => {}
                _ => diagnostics.push(diagnostic(
                    "TASK_PREDICATE_ROBUSTNESS_MISMATCH",
                    format!(
                        "run {run_index} obligation {id} robustness differs from the reference evaluator"
                    ),
                )),
            }
            let reported_confidence = actual
                .get("confidence")
                .and_then(Value::as_f64)
                .unwrap_or_default();
            if (reported_confidence - evaluation.confidence).abs() > f64::EPSILON {
                diagnostics.push(diagnostic(
                    "TASK_PREDICATE_CONFIDENCE_MISMATCH",
                    format!(
                        "run {run_index} obligation {id} confidence differs from the reference evaluator"
                    ),
                ));
            }
        }
    }

    Ok(CertificationAssessment {
        eligible: diagnostics.is_empty(),
        diagnostics,
    })
}

/// Verify every manifest artifact against immutable bytes in a bundle directory.
pub fn verify_bundle_artifacts(
    build_manifest: &Value,
    bundle_root: impl AsRef<Path>,
) -> CertificationAssessment {
    let bundle_root = match fs::canonicalize(bundle_root.as_ref()) {
        Ok(path) => path,
        Err(error) => {
            return CertificationAssessment {
                eligible: false,
                diagnostics: vec![diagnostic(
                    "BUNDLE_ROOT_UNREADABLE",
                    format!("cannot open bundle root: {error}"),
                )],
            };
        }
    };
    let mut diagnostics = Vec::new();
    for artifact in build_manifest
        .get("artifacts")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let id = artifact
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or("<unknown>");
        let Some(relative) = artifact.get("path").and_then(Value::as_str) else {
            diagnostics.push(diagnostic(
                "BUNDLE_ARTIFACT_PATH_MISSING",
                format!("{id} has no path"),
            ));
            continue;
        };
        let joined = bundle_root.join(relative);
        if Path::new(relative).is_absolute()
            || Path::new(relative)
                .components()
                .any(|component| matches!(component, std::path::Component::ParentDir))
            || fs::symlink_metadata(&joined).is_ok_and(|metadata| metadata.file_type().is_symlink())
        {
            diagnostics.push(diagnostic(
                "BUNDLE_ARTIFACT_PATH_UNSAFE",
                format!("{id} has an absolute/traversal path or is a symlink"),
            ));
            continue;
        }
        let candidate = match fs::canonicalize(&joined) {
            Ok(path) => path,
            Err(error) => {
                diagnostics.push(diagnostic(
                    "BUNDLE_ARTIFACT_MISSING",
                    format!("{id} cannot be opened: {error}"),
                ));
                continue;
            }
        };
        if !candidate.starts_with(&bundle_root) {
            diagnostics.push(diagnostic(
                "BUNDLE_ARTIFACT_PATH_UNSAFE",
                format!("{id} escapes the bundle root"),
            ));
            continue;
        }
        let bytes = match fs::read(&candidate) {
            Ok(bytes) => bytes,
            Err(error) => {
                diagnostics.push(diagnostic(
                    "BUNDLE_ARTIFACT_UNREADABLE",
                    format!("{id} cannot be read: {error}"),
                ));
                continue;
            }
        };
        let actual_digest = format!("sha256:{:x}", Sha256::digest(&bytes));
        let expected_digest = artifact
            .get("digest")
            .and_then(Value::as_str)
            .unwrap_or_default();
        let expected_size = artifact.get("sizeBytes").and_then(Value::as_u64);
        if expected_digest != actual_digest || expected_size != Some(bytes.len() as u64) {
            diagnostics.push(diagnostic(
                "BUNDLE_ARTIFACT_DIGEST_MISMATCH",
                format!("{id} does not match its declared digest and size"),
            ));
        }
    }
    CertificationAssessment {
        eligible: diagnostics.is_empty(),
        diagnostics,
    }
}

pub fn generate_signing_key() -> SigningKey {
    SigningKey::generate(&mut OsRng)
}

fn unsigned_payload(certificate: &Value) -> Result<Vec<u8>, CanonicalError> {
    let mut payload = certificate.clone();
    if let Some(object) = payload.as_object_mut() {
        object.remove("signature");
        object.insert(
            "signatureStatus".to_owned(),
            Value::String("unsigned".to_owned()),
        );
    }
    canonical_json(&payload)
}

pub fn sign_certificate(
    certificate: &mut Value,
    key: &SigningKey,
    public_key_id: &str,
) -> Result<(), CanonicalError> {
    let signature = key.sign(&unsigned_payload(certificate)?);
    let object = certificate
        .as_object_mut()
        .expect("certificate schema requires an object");
    object.insert(
        "signatureStatus".to_owned(),
        Value::String("signed".to_owned()),
    );
    object.insert(
        "signature".to_owned(),
        json!({
            "algorithm": "Ed25519",
            "publicKeyId": public_key_id,
            "value": URL_SAFE_NO_PAD.encode(signature.to_bytes())
        }),
    );
    Ok(())
}

pub fn sign_certificate_with_seed(
    certificate: &mut Value,
    seed: &[u8; 32],
    public_key_id: &str,
) -> Result<(), CanonicalError> {
    sign_certificate(certificate, &SigningKey::from_bytes(seed), public_key_id)
}

pub fn verify_certificate(certificate: &Value, key: &VerifyingKey) -> bool {
    let Some(encoded) = certificate
        .pointer("/signature/value")
        .and_then(Value::as_str)
    else {
        return false;
    };
    let Ok(bytes) = URL_SAFE_NO_PAD.decode(encoded) else {
        return false;
    };
    let Ok(signature) = Signature::from_slice(&bytes) else {
        return false;
    };
    let Ok(payload) = unsigned_payload(certificate) else {
        return false;
    };
    key.verify(&payload, &signature).is_ok()
}

#[cfg(test)]
mod tests {
    use super::{
        assess_l2_bindings, assess_l3_bindings, generate_signing_key, sign_certificate,
        verify_bundle_artifacts, verify_certificate,
    };
    use serde_json::{Value, json};
    use std::fs;
    use worldspec_core::canonical_sha256;

    fn fixture() -> Value {
        serde_json::from_str(include_str!(
            "../../../examples/minimal-cube/certificate.json"
        ))
        .unwrap()
    }

    #[test]
    fn signature_detects_certificate_tampering() {
        let key = generate_signing_key();
        let mut certificate = fixture();
        sign_certificate(&mut certificate, &key, "key://worldspec/test").unwrap();
        assert!(verify_certificate(&certificate, &key.verifying_key()));
        certificate["assetDigest"] = Value::String(format!("sha256:{}", "9".repeat(64)));
        assert!(!verify_certificate(&certificate, &key.verifying_key()));
    }

    fn l2_documents() -> (Value, Value, Value, Value, Value, Value) {
        let world: Value =
            serde_json::from_str(include_str!("../../../examples/minimal-cube/world.json"))
                .unwrap();
        let target: Value = serde_json::from_str(include_str!(
            "../../../examples/minimal-cube/target-profile.json"
        ))
        .unwrap();
        let world_digest = canonical_sha256(&world).unwrap();
        let target_digest = canonical_sha256(&target).unwrap();
        let evidence_digest = canonical_sha256(&world["evidenceGraph"]).unwrap();
        let artifact = json!({
            "id": "artifact://test/model",
            "digest": format!("sha256:{}", "7".repeat(64)),
            "mediaType": "application/mujoco+xml",
            "path": "model.xml",
            "sizeBytes": 7,
            "role": "entrypoint"
        });
        let loss = json!({
            "id": "lossreport://test/mujoco",
            "reportVersion": "0.1.0",
            "buildId": "build://test/mujoco",
            "coverage": {
                "sourceItemCount": 0,
                "reportedItemCount": 0,
                "complete": true
            },
            "entries": [],
            "summary": {"highestSeverity": "none", "buildAllowed": true}
        });
        let loss_digest = canonical_sha256(&loss).unwrap();
        let manifest = json!({
            "id": "build://test/mujoco",
            "manifestVersion": "0.1.0",
            "worldDefinitionDigest": world_digest,
            "evidenceGraphDigest": evidence_digest,
            "targetProfileDigest": target_digest,
            "buildIntentDigest": format!("sha256:{}", "1".repeat(64)),
            "compiler": {
                "name": "test",
                "version": "0.1.0",
                "digest": format!("sha256:{}", "2".repeat(64))
            },
            "modelSelections": [],
            "artifacts": [artifact.clone()],
            "lossReportDigest": loss_digest,
            "lockDigest": format!("sha256:{}", "3".repeat(64))
        });
        let manifest_digest = canonical_sha256(&manifest).unwrap();
        let conformance = json!({
            "id": "conformance://test/mujoco",
            "reportVersion": "0.1.0",
            "buildManifestDigest": manifest_digest,
            "targetProfileDigest": target_digest,
            "target": "mujoco",
            "executionEvidence": "executed",
            "runner": {
                "name": "test",
                "version": "0.1.0",
                "digest": format!("sha256:{}", "4".repeat(64))
            },
            "environment": {
                "os": "linux",
                "architecture": "x86_64",
                "runtime": "mujoco",
                "runtimeVersion": "3.6.0"
            },
            "testedArtifacts": [artifact],
            "tests": [
                {
                    "id": "test://worldspec/native-load",
                    "version": "0.1.0",
                    "result": "pass",
                    "evidenceArtifacts": []
                },
                {
                    "id": "test://worldspec/rigid-rest",
                    "version": "0.1.0",
                    "result": "pass",
                    "evidenceArtifacts": []
                }
            ],
            "summary": {
                "passed": 2,
                "failed": 0,
                "unknown": 0,
                "notRun": 0,
                "overall": "pass"
            },
            "generatedAt": "2026-07-28T00:00:00Z"
        });
        let certificate = json!({
            "id": "certificate://test/mujoco-l2",
            "certificateVersion": "0.1.0",
            "level": "L2",
            "assetDigest": canonical_sha256(&world).unwrap(),
            "targetProfileDigest": canonical_sha256(&target).unwrap(),
            "buildManifestDigest": canonical_sha256(&manifest).unwrap(),
            "lossReportDigest": canonical_sha256(&loss).unwrap(),
            "conformanceReportDigest": canonical_sha256(&conformance).unwrap(),
            "evidenceStatuses": ["generated"],
            "issuedAt": "2026-07-28T00:00:00Z",
            "issuer": "test",
            "valid": true,
            "invalidatedBy": [],
            "signatureStatus": "unsigned"
        });
        (certificate, world, target, manifest, loss, conformance)
    }

    #[test]
    fn l2_assessment_requires_all_digest_bound_evidence() {
        let (certificate, world, target, manifest, loss, conformance) = l2_documents();
        let result = assess_l2_bindings(
            &certificate,
            &world,
            &target,
            &manifest,
            &loss,
            &conformance,
        )
        .unwrap();
        assert!(result.eligible, "{:?}", result.diagnostics);
    }

    #[test]
    fn l2_assessment_detects_conformance_tampering() {
        let (certificate, world, target, manifest, loss, mut conformance) = l2_documents();
        conformance["tests"][0]["result"] = Value::String("fail".to_owned());
        let result = assess_l2_bindings(
            &certificate,
            &world,
            &target,
            &manifest,
            &loss,
            &conformance,
        )
        .unwrap();
        assert!(!result.eligible);
        assert!(
            result
                .diagnostics
                .iter()
                .any(|item| item.code == "CERT_CONFORMANCE_REPORT_DIGEST_MISMATCH")
        );
        assert!(
            result
                .diagnostics
                .iter()
                .any(|item| item.code == "CONFORMANCE_REQUIRED_TEST_NOT_PASSING")
        );
    }

    #[test]
    fn bundle_artifact_verification_detects_mutation() {
        let (_, _, _, manifest, _, _) = l2_documents();
        let root = std::env::temp_dir().join(format!("worldspec-cert-test-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("model.xml"), b"1234567").unwrap();
        let result = verify_bundle_artifacts(&manifest, &root);
        assert!(!result.eligible);
        assert!(
            result
                .diagnostics
                .iter()
                .any(|item| item.code == "BUNDLE_ARTIFACT_DIGEST_MISMATCH")
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn l3_assessment_binds_profiles_initial_state_and_five_runtime_witnesses() {
        let (_, world, target, manifest, loss, conformance) = l2_documents();
        let world_digest = canonical_sha256(&world).unwrap();
        let target_digest = canonical_sha256(&target).unwrap();
        let manifest_digest = canonical_sha256(&manifest).unwrap();
        let initial_state = json!({"snapshot": "locked"});
        let initial_state_digest = canonical_sha256(&initial_state).unwrap();
        let control = json!({
            "id": "controlprofile://test/h1",
            "profileVersion": "0.1.0"
        });
        let control_digest = canonical_sha256(&control).unwrap();
        let predicates = vec![
            json!({
                "id": "predicateprofile://test/stable",
                "predicateId": "predicate://worldspec/stable",
                "thresholds": {
                    "maximumLinearSpeed": 0.02,
                    "maximumAngularSpeed": 0.05,
                    "maximumPoseDrift": 0.002
                }
            }),
            json!({
                "id": "predicateprofile://test/finite",
                "predicateId": "predicate://worldspec/finite"
            }),
        ];
        let predicate_digests = predicates
            .iter()
            .map(|profile| canonical_sha256(profile).unwrap())
            .collect::<Vec<_>>();
        let task = json!({
            "id": "taskprofile://test/h1-kitchen",
            "worldDigest": world_digest,
            "robotRef": "entity://cube",
            "controlProfileDigest": control_digest,
            "initialStateDigest": initial_state_digest,
            "predicateProfiles": predicate_digests,
            "goals": [{
                "id": "goal://test/stable",
                "predicate": "predicate://worldspec/stable",
                "arguments": ["entity://cube"],
                "holdForSeconds": 0.5
            }],
            "safety": [{
                "id": "safety://test/finite",
                "predicate": "predicate://worldspec/finite",
                "mustRemain": "true",
                "arguments": ["entity://cube"]
            }],
            "execution": {
                "timeLimitSeconds": 5.0,
                "fixedInitialState": true
            },
            "certification": {
                "requiredRuns": 5,
                "requiredSuccesses": 5
            }
        });
        let task_digest = canonical_sha256(&task).unwrap();
        let mut runtime_records = Vec::new();
        let mut runs = Vec::new();
        for index in 0..5 {
            let epoch = format!("episode-{index}");
            let runtime = json!({
                "id": format!("runtime://test/{index}"),
                "worldDefinitionDigest": world_digest,
                "epoch": epoch,
                "initialSnapshot": {
                    "worldDefinitionDigest": world_digest,
                    "values": initial_state.clone()
                }
            });
            let runtime_digest = canonical_sha256(&runtime).unwrap();
            runtime_records.push(runtime);
            runs.push(json!({
                "index": index,
                "epoch": epoch,
                "result": "pass",
                "initialStateDigest": initial_state_digest,
                "runtimeRecordDigest": runtime_digest,
                "durationSeconds": 1.0,
                "obligations": [
                    {
                        "obligationRef": "goal://test/stable",
                        "kind": "goal",
                        "predicate": "predicate://worldspec/stable",
                        "arguments": ["entity://cube"],
                        "result": "pass",
                        "truth": "true",
                        "confidence": 1.0,
                        "robustness": 0.002,
                        "evaluatedForSeconds": 0.5,
                        "metrics": {
                            "linearSpeed": 0.0,
                            "angularSpeed": 0.0,
                            "poseDrift": 0.0,
                            "confidence": 1.0
                        },
                        "evidenceArtifacts": []
                    },
                    {
                        "obligationRef": "safety://test/finite",
                        "kind": "safety",
                        "predicate": "predicate://worldspec/finite",
                        "arguments": ["entity://cube"],
                        "result": "pass",
                        "truth": "true",
                        "confidence": 1.0,
                        "robustness": 1.0,
                        "evaluatedForSeconds": 1.0,
                        "violationCount": 0,
                        "metrics": {
                            "allFinite": true,
                            "confidence": 1.0
                        },
                        "evidenceArtifacts": []
                    }
                ],
                "diagnostics": []
            }));
        }
        let mut task_run = json!({
            "id": "taskrunreport://test/h1-kitchen",
            "taskProfileDigest": task_digest,
            "worldDefinitionDigest": world_digest,
            "targetProfileDigest": target_digest,
            "buildManifestDigest": manifest_digest,
            "controlProfileDigest": control_digest,
            "predicateProfileDigests": predicate_digests,
            "initialStateDigest": initial_state_digest,
            "executionEvidence": "executed",
            "environment": {
                "os": "linux",
                "architecture": "x86_64",
                "runtime": "mujoco",
                "runtimeVersion": "3.6.0"
            },
            "runs": runs,
            "summary": {
                "total": 5,
                "passed": 5,
                "failed": 0,
                "unknown": 0,
                "notRun": 0,
                "overall": "pass"
            }
        });
        let mut certificate = json!({
            "id": "certificate://test/h1-kitchen-l3",
            "level": "L3",
            "assetDigest": canonical_sha256(&world).unwrap(),
            "targetProfileDigest": canonical_sha256(&target).unwrap(),
            "buildManifestDigest": canonical_sha256(&manifest).unwrap(),
            "lossReportDigest": canonical_sha256(&loss).unwrap(),
            "conformanceReportDigest": canonical_sha256(&conformance).unwrap(),
            "taskProfileDigest": canonical_sha256(&task).unwrap(),
            "taskRunReportDigest": canonical_sha256(&task_run).unwrap(),
            "evidenceStatuses": ["generated"],
            "valid": true,
            "invalidatedBy": []
        });
        let result = assess_l3_bindings(
            &certificate,
            &world,
            &target,
            &manifest,
            &loss,
            &conformance,
            &task,
            &control,
            &predicates,
            &initial_state,
            &runtime_records,
            &task_run,
        )
        .unwrap();
        assert!(result.eligible, "{:?}", result.diagnostics);

        task_run["runs"][0]["obligations"][0]["metrics"]["linearSpeed"] = Value::from(1.0);
        certificate["taskRunReportDigest"] = Value::String(canonical_sha256(&task_run).unwrap());
        let tampered = assess_l3_bindings(
            &certificate,
            &world,
            &target,
            &manifest,
            &loss,
            &conformance,
            &task,
            &control,
            &predicates,
            &initial_state,
            &runtime_records,
            &task_run,
        )
        .unwrap();
        assert!(!tampered.eligible);
        assert!(
            tampered
                .diagnostics
                .iter()
                .any(|item| item.code == "TASK_PREDICATE_TRUTH_MISMATCH")
        );
    }

    #[test]
    fn l3_assessment_rejects_a_relabelled_five_of_five_claim() {
        let (_, world, target, manifest, loss, conformance) = l2_documents();
        let initial_state = json!({"snapshot": "locked"});
        let control = json!({"id": "controlprofile://test/h1"});
        let predicates = vec![json!({
            "id": "predicateprofile://test/stable",
            "predicateId": "predicate://worldspec/stable"
        })];
        let task = json!({
            "worldDigest": canonical_sha256(&world).unwrap(),
            "controlProfileDigest": canonical_sha256(&control).unwrap(),
            "initialStateDigest": canonical_sha256(&initial_state).unwrap(),
            "predicateProfiles": [canonical_sha256(&predicates[0]).unwrap()],
            "goals": [{
                "id": "goal://test/stable",
                "predicate": "predicate://worldspec/stable",
                "arguments": ["entity://cube"]
            }],
            "safety": [],
            "execution": {"timeLimitSeconds": 5.0, "fixedInitialState": true},
            "certification": {"requiredRuns": 5, "requiredSuccesses": 5}
        });
        let task_run = json!({
            "taskProfileDigest": canonical_sha256(&task).unwrap(),
            "worldDefinitionDigest": canonical_sha256(&world).unwrap(),
            "targetProfileDigest": canonical_sha256(&target).unwrap(),
            "buildManifestDigest": canonical_sha256(&manifest).unwrap(),
            "controlProfileDigest": canonical_sha256(&control).unwrap(),
            "predicateProfileDigests": [canonical_sha256(&predicates[0]).unwrap()],
            "initialStateDigest": canonical_sha256(&initial_state).unwrap(),
            "executionEvidence": "executed",
            "environment": {
                "os": "linux",
                "architecture": "x86_64",
                "runtime": "mujoco",
                "runtimeVersion": "3.6.0"
            },
            "runs": [],
            "summary": {
                "total": 5,
                "passed": 5,
                "failed": 0,
                "unknown": 0,
                "notRun": 0,
                "overall": "pass"
            }
        });
        let certificate = json!({
            "level": "L3",
            "assetDigest": canonical_sha256(&world).unwrap(),
            "targetProfileDigest": canonical_sha256(&target).unwrap(),
            "buildManifestDigest": canonical_sha256(&manifest).unwrap(),
            "lossReportDigest": canonical_sha256(&loss).unwrap(),
            "conformanceReportDigest": canonical_sha256(&conformance).unwrap(),
            "taskProfileDigest": canonical_sha256(&task).unwrap(),
            "taskRunReportDigest": canonical_sha256(&task_run).unwrap(),
            "evidenceStatuses": ["generated"],
            "valid": true,
            "invalidatedBy": []
        });
        let result = assess_l3_bindings(
            &certificate,
            &world,
            &target,
            &manifest,
            &loss,
            &conformance,
            &task,
            &control,
            &predicates,
            &initial_state,
            &[],
            &task_run,
        )
        .unwrap();
        assert!(!result.eligible);
        assert!(
            result
                .diagnostics
                .iter()
                .any(|item| item.code == "TASK_RUN_COUNT_MISMATCH")
        );
        assert!(
            result
                .diagnostics
                .iter()
                .any(|item| item.code == "TASK_SUCCESS_COUNT_INSUFFICIENT")
        );
    }
}
