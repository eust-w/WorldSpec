//! Digest-bound optional Ed25519 certificate signing.

use base64::{Engine, engine::general_purpose::URL_SAFE_NO_PAD};
use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use rand_core::OsRng;
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, fs, path::Path};
use worldspec_core::{CanonicalError, canonical_json, canonical_sha256};

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

/// Verify all immutable document bindings required before an L2 certificate can be valid.
pub fn assess_l2_bindings(
    certificate: &Value,
    world: &Value,
    target_profile: &Value,
    build_manifest: &Value,
    loss_report: &Value,
    conformance_report: &Value,
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

    if string(certificate, "/level") != Some("L2") {
        diagnostics.push(diagnostic(
            "CERT_LEVEL_NOT_L2",
            "this assessment only authorizes an L2 certificate",
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
        assess_l2_bindings, generate_signing_key, sign_certificate, verify_bundle_artifacts,
        verify_certificate,
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
}
