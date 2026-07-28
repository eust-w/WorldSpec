//! Deterministic source security scanning and baseline OBJ Doctor.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::path::{Component, Path};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum DiagnosticSeverity {
    Info,
    Warning,
    Error,
    Fatal,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ForgeDiagnostic {
    pub code: String,
    pub severity: DiagnosticSeverity,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub line: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SourceScan {
    pub format: String,
    pub digest: String,
    pub size_bytes: u64,
    pub safe: bool,
    pub diagnostics: Vec<ForgeDiagnostic>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ObjMetrics {
    pub vertices: usize,
    pub faces: usize,
    pub degenerate_faces: usize,
    pub malformed_lines: usize,
    pub bounds_min: Option<[f64; 3]>,
    pub bounds_max: Option<[f64; 3]>,
    pub extent: Option<[f64; 3]>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ObjDoctorReport {
    pub source_digest: String,
    pub metrics: ObjMetrics,
    pub diagnostics: Vec<ForgeDiagnostic>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ObjRepairResult {
    pub source_digest: String,
    pub repaired_digest: String,
    pub removed_degenerate_faces: usize,
    pub payload: Vec<u8>,
    pub derivation: serde_json::Value,
}

fn diagnostic(
    code: &str,
    severity: DiagnosticSeverity,
    message: impl Into<String>,
    line: Option<usize>,
) -> ForgeDiagnostic {
    ForgeDiagnostic {
        code: code.to_owned(),
        severity,
        message: message.into(),
        line,
    }
}

fn is_safe_relative_reference(value: &str) -> bool {
    if value.contains("://") || value.starts_with('/') || value.starts_with('\\') {
        return false;
    }
    !Path::new(value)
        .components()
        .any(|component| matches!(component, Component::ParentDir | Component::RootDir))
}

fn references_for(format: &str, text: &str) -> Vec<(usize, String)> {
    let mut references = Vec::new();
    for (line_index, line) in text.lines().enumerate() {
        let trimmed = line.trim();
        if format == "obj" && trimmed.starts_with("mtllib ") {
            references.push((line_index + 1, trimmed[7..].trim().to_owned()));
        }
        if matches!(format, "urdf" | "mjcf") {
            for attribute in ["filename=\"", "file=\""] {
                let mut remainder = trimmed;
                while let Some(start) = remainder.find(attribute) {
                    remainder = &remainder[start + attribute.len()..];
                    if let Some(end) = remainder.find('"') {
                        references.push((line_index + 1, remainder[..end].to_owned()));
                        remainder = &remainder[end + 1..];
                    } else {
                        break;
                    }
                }
            }
        }
    }
    references
}

/// Scan raw source bytes before any third-party parser is invoked.
pub fn scan_source(format: &str, payload: &[u8], max_bytes: u64) -> SourceScan {
    let mut diagnostics = Vec::new();
    if payload.len() as u64 > max_bytes {
        diagnostics.push(diagnostic(
            "SOURCE_SIZE_LIMIT_EXCEEDED",
            DiagnosticSeverity::Fatal,
            format!("source is {} bytes; limit is {max_bytes}", payload.len()),
            None,
        ));
    }
    if payload.starts_with(b"PK\x03\x04") {
        diagnostics.push(diagnostic(
            "ARCHIVE_REQUIRES_ISOLATED_EXPANSION",
            DiagnosticSeverity::Error,
            "archive input must be expanded by the bounded archive worker",
            None,
        ));
    }
    if let Ok(text) = std::str::from_utf8(payload) {
        if matches!(format, "urdf" | "mjcf")
            && ["<!DOCTYPE", "<!ENTITY", " SYSTEM ", " PUBLIC "]
                .iter()
                .any(|needle| text.to_ascii_uppercase().contains(needle))
        {
            diagnostics.push(diagnostic(
                "XML_EXTERNAL_ENTITY_FORBIDDEN",
                DiagnosticSeverity::Fatal,
                "DOCTYPE, ENTITY, SYSTEM, and PUBLIC declarations are forbidden",
                None,
            ));
        }
        for (line, reference) in references_for(format, text) {
            if !is_safe_relative_reference(&reference) {
                diagnostics.push(diagnostic(
                    "EXTERNAL_REFERENCE_FORBIDDEN",
                    DiagnosticSeverity::Fatal,
                    format!("unsafe external reference: {reference}"),
                    Some(line),
                ));
            }
        }
    } else if matches!(format, "obj" | "urdf" | "mjcf") {
        diagnostics.push(diagnostic(
            "SOURCE_TEXT_ENCODING_INVALID",
            DiagnosticSeverity::Fatal,
            "text source is not valid UTF-8",
            None,
        ));
    }
    let safe = !diagnostics.iter().any(|item| {
        matches!(
            item.severity,
            DiagnosticSeverity::Error | DiagnosticSeverity::Fatal
        )
    });
    SourceScan {
        format: format.to_owned(),
        digest: format!("sha256:{:x}", Sha256::digest(payload)),
        size_bytes: payload.len() as u64,
        safe,
        diagnostics,
    }
}

fn parse_vertex(line: &str) -> Option<[f64; 3]> {
    let mut values = line.split_whitespace().skip(1).map(str::parse::<f64>);
    Some([
        values.next()?.ok()?,
        values.next()?.ok()?,
        values.next()?.ok()?,
    ])
}

fn parse_face(line: &str) -> Option<Vec<usize>> {
    line.split_whitespace()
        .skip(1)
        .map(|token| token.split('/').next()?.parse::<usize>().ok())
        .collect()
}

fn area_squared(a: [f64; 3], b: [f64; 3], c: [f64; 3]) -> f64 {
    let ab = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    let ac = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
    let cross = [
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    ];
    cross.iter().map(|value| value * value).sum()
}

fn face_is_degenerate(face: &[usize], vertices: &[[f64; 3]]) -> bool {
    if face.len() < 3 {
        return true;
    }
    if face
        .iter()
        .any(|index| *index == 0 || *index > vertices.len())
    {
        return true;
    }
    if face.windows(2).any(|pair| pair[0] == pair[1]) {
        return true;
    }
    let first = vertices[face[0] - 1];
    (1..face.len() - 1).all(|index| {
        area_squared(
            first,
            vertices[face[index] - 1],
            vertices[face[index + 1] - 1],
        ) < 1.0e-24
    })
}

pub fn diagnose_obj(payload: &[u8]) -> ObjDoctorReport {
    let source_digest = format!("sha256:{:x}", Sha256::digest(payload));
    let Ok(text) = std::str::from_utf8(payload) else {
        return ObjDoctorReport {
            source_digest,
            metrics: ObjMetrics {
                vertices: 0,
                faces: 0,
                degenerate_faces: 0,
                malformed_lines: 1,
                bounds_min: None,
                bounds_max: None,
                extent: None,
            },
            diagnostics: vec![diagnostic(
                "OBJ_TEXT_ENCODING_INVALID",
                DiagnosticSeverity::Fatal,
                "OBJ is not valid UTF-8",
                None,
            )],
        };
    };
    let mut vertices = Vec::new();
    let mut faces = Vec::new();
    let mut malformed = 0;
    let mut diagnostics = Vec::new();
    for (line_index, line) in text.lines().enumerate() {
        let trimmed = line.trim();
        if trimmed.starts_with("v ") {
            if let Some(vertex) = parse_vertex(trimmed) {
                vertices.push(vertex);
            } else {
                malformed += 1;
                diagnostics.push(diagnostic(
                    "OBJ_VERTEX_MALFORMED",
                    DiagnosticSeverity::Error,
                    "vertex requires three finite numbers",
                    Some(line_index + 1),
                ));
            }
        } else if trimmed.starts_with("f ") {
            if let Some(face) = parse_face(trimmed) {
                faces.push((line_index + 1, face));
            } else {
                malformed += 1;
                diagnostics.push(diagnostic(
                    "OBJ_FACE_MALFORMED",
                    DiagnosticSeverity::Error,
                    "face contains an unsupported or invalid vertex index",
                    Some(line_index + 1),
                ));
            }
        }
    }
    let degenerate = faces
        .iter()
        .filter(|(_, face)| face_is_degenerate(face, &vertices))
        .count();
    if degenerate > 0 {
        diagnostics.push(diagnostic(
            "OBJ_DEGENERATE_FACES",
            DiagnosticSeverity::Warning,
            format!("{degenerate} degenerate face(s) found"),
            None,
        ));
    }
    let (bounds_min, bounds_max, extent) = if vertices.is_empty() {
        (None, None, None)
    } else {
        let mut minimum = [f64::INFINITY; 3];
        let mut maximum = [f64::NEG_INFINITY; 3];
        for vertex in &vertices {
            for axis in 0..3 {
                minimum[axis] = minimum[axis].min(vertex[axis]);
                maximum[axis] = maximum[axis].max(vertex[axis]);
            }
        }
        (
            Some(minimum),
            Some(maximum),
            Some([
                maximum[0] - minimum[0],
                maximum[1] - minimum[1],
                maximum[2] - minimum[2],
            ]),
        )
    };
    ObjDoctorReport {
        source_digest,
        metrics: ObjMetrics {
            vertices: vertices.len(),
            faces: faces.len(),
            degenerate_faces: degenerate,
            malformed_lines: malformed,
            bounds_min,
            bounds_max,
            extent,
        },
        diagnostics,
    }
}

pub fn repair_obj_remove_degenerate(payload: &[u8]) -> Result<ObjRepairResult, String> {
    let text = std::str::from_utf8(payload).map_err(|error| error.to_string())?;
    let vertices = text
        .lines()
        .filter(|line| line.trim().starts_with("v "))
        .filter_map(|line| parse_vertex(line.trim()))
        .collect::<Vec<_>>();
    let mut output = String::new();
    let mut removed = 0;
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.starts_with("f ")
            && parse_face(trimmed).is_none_or(|face| face_is_degenerate(&face, &vertices))
        {
            removed += 1;
            continue;
        }
        output.push_str(line);
        output.push('\n');
    }
    let source_digest = format!("sha256:{:x}", Sha256::digest(payload));
    let repaired = output.into_bytes();
    let repaired_digest = format!("sha256:{:x}", Sha256::digest(&repaired));
    Ok(ObjRepairResult {
        source_digest: source_digest.clone(),
        repaired_digest: repaired_digest.clone(),
        removed_degenerate_faces: removed,
        payload: repaired,
        derivation: serde_json::json!({
            "id": format!("derivation://doctor/obj-remove-degenerate/{}", repaired_digest.trim_start_matches("sha256:")),
            "method": "obj_remove_degenerate_faces",
            "methodVersion": env!("CARGO_PKG_VERSION"),
            "sourceDigest": source_digest,
            "outputDigest": repaired_digest,
            "removedFaces": removed,
            "sourceModified": false
        }),
    })
}

#[cfg(test)]
mod tests {
    use super::{diagnose_obj, repair_obj_remove_degenerate, scan_source};

    #[test]
    fn rejects_external_xml_entities_and_paths() {
        let xml = br#"<!DOCTYPE robot [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
        <robot><mesh filename="../../secret.obj"/></robot>"#;
        let scan = scan_source("urdf", xml, 1024);
        assert!(!scan.safe);
        let codes = scan
            .diagnostics
            .iter()
            .map(|item| item.code.as_str())
            .collect::<Vec<_>>();
        assert!(codes.contains(&"XML_EXTERNAL_ENTITY_FORBIDDEN"));
        assert!(codes.contains(&"EXTERNAL_REFERENCE_FORBIDDEN"));
    }

    #[test]
    fn diagnoses_and_repairs_degenerate_obj_without_mutating_source() {
        let source = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\nf 1 1 2\n";
        let report = diagnose_obj(source);
        assert_eq!(report.metrics.faces, 2);
        assert_eq!(report.metrics.degenerate_faces, 1);
        let repaired = repair_obj_remove_degenerate(source).unwrap();
        assert_eq!(repaired.removed_degenerate_faces, 1);
        assert_ne!(repaired.source_digest, repaired.repaired_digest);
        assert_eq!(source, b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\nf 1 1 2\n");
    }

    #[test]
    fn enforces_source_size_before_parser() {
        let scan = scan_source("obj", b"12345", 4);
        assert!(!scan.safe);
        assert_eq!(scan.diagnostics[0].code, "SOURCE_SIZE_LIMIT_EXCEEDED");
    }
}
