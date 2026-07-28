//! Deterministic source security scanning and baseline OBJ Doctor.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Component, Path},
};

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

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "camelCase")]
pub struct RobotXmlMetrics {
    pub links: usize,
    pub bodies: usize,
    pub joints: usize,
    pub visuals: usize,
    pub collisions: usize,
    pub actuators: usize,
    pub cameras: usize,
    pub sensors: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct RobotXmlDoctorReport {
    pub format: String,
    pub source_digest: String,
    pub safe: bool,
    pub metrics: RobotXmlMetrics,
    pub named_objects: BTreeMap<String, Vec<String>>,
    pub unknown_elements: Vec<String>,
    pub kinematics: RobotKinematicModel,
    pub diagnostics: Vec<ForgeDiagnostic>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct RobotKinematicModel {
    pub name: String,
    pub links: Vec<RobotKinematicLink>,
    pub joints: Vec<RobotKinematicJoint>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct RobotKinematicLink {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_hint: Option<String>,
    pub translation: [f64; 3],
    pub rotation_wxyz: [f64; 4],
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct RobotKinematicJoint {
    pub name: String,
    pub joint_type: String,
    pub parent: String,
    pub child: String,
    pub axis: [f64; 3],
    #[serde(skip_serializing_if = "Option::is_none")]
    pub lower: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub upper: Option<f64>,
    pub translation: [f64; 3],
    pub rotation_wxyz: [f64; 4],
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct GlbDoctorReport {
    pub source_digest: String,
    pub valid: bool,
    pub version: Option<u32>,
    pub declared_length: Option<u32>,
    pub json_chunk_length: Option<u32>,
    pub nodes: usize,
    pub meshes: usize,
    pub materials: usize,
    pub textures: usize,
    pub images: usize,
    pub diagnostics: Vec<ForgeDiagnostic>,
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
    if let Some(package_path) = value.strip_prefix("package://") {
        return !package_path.is_empty()
            && !Path::new(package_path)
                .components()
                .any(|component| matches!(component, Component::ParentDir | Component::RootDir));
    }
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
        let uppercase = text.to_ascii_uppercase();
        if matches!(format, "urdf" | "mjcf")
            && ["<!DOCTYPE", "<!ENTITY", " SYSTEM ", " PUBLIC "]
                .iter()
                .any(|needle| uppercase.contains(needle))
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

fn xml_attributes(fragment: &str) -> BTreeMap<String, String> {
    let mut attributes = BTreeMap::new();
    let mut cursor = fragment;
    while let Some(equal) = cursor.find('=') {
        let before = &cursor[..equal];
        let Some(key) = before.split_whitespace().last() else {
            break;
        };
        let after = cursor[equal + 1..].trim_start();
        let Some(quote) = after
            .chars()
            .next()
            .filter(|value| matches!(value, '"' | '\''))
        else {
            cursor = &after[after.len().min(1)..];
            continue;
        };
        let value_start = quote.len_utf8();
        let remainder = &after[value_start..];
        let Some(end) = remainder.find(quote) else {
            break;
        };
        attributes.insert(key.to_owned(), remainder[..end].to_owned());
        cursor = &remainder[end + quote.len_utf8()..];
    }
    attributes
}

fn parse_numbers(value: Option<&String>, expected: usize) -> Option<Vec<f64>> {
    let values = value?
        .split_whitespace()
        .map(str::parse::<f64>)
        .collect::<Result<Vec<_>, _>>()
        .ok()?;
    (values.len() == expected && values.iter().all(|item| item.is_finite())).then_some(values)
}

fn inertia_is_valid(values: &[f64; 6]) -> bool {
    let [ixx, iyy, izz, ixy, ixz, iyz] = *values;
    if !values.iter().all(|value| value.is_finite()) || ixx <= 0.0 || iyy <= 0.0 || izz <= 0.0 {
        return false;
    }
    let second_minor = ixx * iyy - ixy * ixy;
    let determinant = ixx * iyy * izz + 2.0 * ixy * ixz * iyz
        - ixx * iyz * iyz
        - iyy * ixz * ixz
        - izz * ixy * ixy;
    second_minor > 0.0 && determinant > 0.0
}

fn check_inertia(
    format: &str,
    attributes: &BTreeMap<String, String>,
    diagnostics: &mut Vec<ForgeDiagnostic>,
) {
    let invalid = if format == "urdf" {
        let fields = ["ixx", "iyy", "izz", "ixy", "ixz", "iyz"];
        let values = fields
            .iter()
            .map(|field| attributes.get(*field)?.parse::<f64>().ok())
            .collect::<Option<Vec<_>>>();
        values.is_none_or(|values| {
            let values: [f64; 6] = values.try_into().expect("six inertia fields");
            !inertia_is_valid(&values)
        })
    } else if let Some(diagonal) = parse_numbers(attributes.get("diaginertia"), 3) {
        diagonal.iter().any(|value| *value <= 0.0)
            || diagonal[0] + diagonal[1] < diagonal[2]
            || diagonal[0] + diagonal[2] < diagonal[1]
            || diagonal[1] + diagonal[2] < diagonal[0]
    } else if let Some(full) = parse_numbers(attributes.get("fullinertia"), 6) {
        let values: [f64; 6] = full.try_into().expect("six inertia fields");
        !inertia_is_valid(&values)
    } else {
        true
    };
    let mass_invalid = attributes
        .get("mass")
        .and_then(|mass| mass.parse::<f64>().ok())
        .is_some_and(|mass| !mass.is_finite() || mass <= 0.0);
    if invalid || mass_invalid {
        diagnostics.push(diagnostic(
            "ROBOT_INERTIA_INVALID",
            DiagnosticSeverity::Fatal,
            "inertia must be finite, positive definite, and physically admissible",
            None,
        ));
    }
}

fn known_robot_elements(format: &str) -> BTreeSet<&'static str> {
    let values: &[&str] = if format == "urdf" {
        &[
            "robot",
            "link",
            "joint",
            "parent",
            "child",
            "origin",
            "axis",
            "limit",
            "dynamics",
            "calibration",
            "safety_controller",
            "visual",
            "collision",
            "geometry",
            "mesh",
            "box",
            "cylinder",
            "sphere",
            "inertial",
            "mass",
            "inertia",
            "material",
            "color",
            "texture",
            "transmission",
            "actuator",
            "hardwareinterface",
            "gazebo",
            "sensor",
            "camera",
        ]
    } else {
        &[
            "mujoco",
            "compiler",
            "option",
            "size",
            "visual",
            "statistic",
            "default",
            "asset",
            "mesh",
            "texture",
            "material",
            "hfield",
            "worldbody",
            "body",
            "frame",
            "inertial",
            "joint",
            "freejoint",
            "geom",
            "site",
            "camera",
            "light",
            "contact",
            "pair",
            "exclude",
            "equality",
            "weld",
            "connect",
            "tendon",
            "spatial",
            "fixed",
            "pulley",
            "actuator",
            "motor",
            "position",
            "velocity",
            "general",
            "cylinder",
            "muscle",
            "adhesion",
            "sensor",
            "accelerometer",
            "velocimeter",
            "gyro",
            "force",
            "torque",
            "touch",
            "rangefinder",
            "jointpos",
            "jointvel",
            "actuatorpos",
            "actuatorvel",
            "actuatorfrc",
            "framepos",
            "framequat",
            "plugin",
            "extension",
            "custom",
            "numeric",
            "text",
            "tuple",
            "keyframe",
            "key",
        ]
    };
    values.iter().copied().collect()
}

fn vector3(value: Option<&String>, fallback: [f64; 3]) -> [f64; 3] {
    parse_numbers(value, 3)
        .map(|items| [items[0], items[1], items[2]])
        .unwrap_or(fallback)
}

fn quaternion_wxyz(value: Option<&String>, fallback: [f64; 4]) -> [f64; 4] {
    parse_numbers(value, 4)
        .map(|items| [items[0], items[1], items[2], items[3]])
        .unwrap_or(fallback)
}

fn rpy_to_wxyz(rpy: [f64; 3]) -> [f64; 4] {
    let (roll, pitch, yaw) = (rpy[0] * 0.5, rpy[1] * 0.5, rpy[2] * 0.5);
    let (sr, cr) = roll.sin_cos();
    let (sp, cp) = pitch.sin_cos();
    let (sy, cy) = yaw.sin_cos();
    [
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    ]
}

#[derive(Debug)]
struct XmlFragment {
    tag: String,
    closing: bool,
    self_closing: bool,
    attributes: BTreeMap<String, String>,
}

fn xml_fragments(text: &str) -> Vec<XmlFragment> {
    let mut fragments = Vec::new();
    let mut cursor = text;
    while let Some(start) = cursor.find('<') {
        cursor = &cursor[start + 1..];
        let Some(end) = cursor.find('>') else {
            break;
        };
        let fragment = cursor[..end].trim();
        cursor = &cursor[end + 1..];
        if fragment.is_empty() || fragment.starts_with('?') || fragment.starts_with('!') {
            continue;
        }
        let closing = fragment.starts_with('/');
        let content = fragment.trim_start_matches('/').trim();
        let tag = content
            .split_whitespace()
            .next()
            .unwrap_or_default()
            .trim_end_matches('/')
            .rsplit(':')
            .next()
            .unwrap_or_default()
            .to_ascii_lowercase();
        fragments.push(XmlFragment {
            tag,
            closing,
            self_closing: content.ends_with('/'),
            attributes: xml_attributes(content),
        });
    }
    fragments
}

fn extract_urdf_kinematics(
    text: &str,
    diagnostics: &mut Vec<ForgeDiagnostic>,
) -> RobotKinematicModel {
    let mut model = RobotKinematicModel::default();
    let mut current: Option<RobotKinematicJoint> = None;
    for fragment in xml_fragments(text) {
        if fragment.closing {
            if fragment.tag == "joint"
                && let Some(joint) = current.take()
            {
                if joint.parent.is_empty() || joint.child.is_empty() {
                    diagnostics.push(diagnostic(
                        "ROBOT_JOINT_ENDPOINT_MISSING",
                        DiagnosticSeverity::Fatal,
                        format!("joint {} is missing parent or child", joint.name),
                        None,
                    ));
                } else {
                    model.joints.push(joint);
                }
            }
            continue;
        }
        match fragment.tag.as_str() {
            "robot" => {
                model.name = fragment
                    .attributes
                    .get("name")
                    .cloned()
                    .unwrap_or_else(|| "robot".to_owned());
            }
            "link" => {
                if let Some(name) = fragment.attributes.get("name") {
                    model.links.push(RobotKinematicLink {
                        name: name.clone(),
                        parent_hint: None,
                        translation: [0.0; 3],
                        rotation_wxyz: [1.0, 0.0, 0.0, 0.0],
                    });
                }
            }
            "joint" => {
                current = Some(RobotKinematicJoint {
                    name: fragment
                        .attributes
                        .get("name")
                        .cloned()
                        .unwrap_or_else(|| format!("joint_{}", model.joints.len())),
                    joint_type: fragment
                        .attributes
                        .get("type")
                        .cloned()
                        .unwrap_or_else(|| "fixed".to_owned()),
                    parent: String::new(),
                    child: String::new(),
                    axis: [1.0, 0.0, 0.0],
                    lower: None,
                    upper: None,
                    translation: [0.0; 3],
                    rotation_wxyz: [1.0, 0.0, 0.0, 0.0],
                });
            }
            "parent" => {
                if let (Some(joint), Some(link)) =
                    (current.as_mut(), fragment.attributes.get("link"))
                {
                    joint.parent.clone_from(link);
                }
            }
            "child" => {
                if let (Some(joint), Some(link)) =
                    (current.as_mut(), fragment.attributes.get("link"))
                {
                    joint.child.clone_from(link);
                }
            }
            "axis" => {
                if let Some(joint) = current.as_mut() {
                    joint.axis = vector3(fragment.attributes.get("xyz"), [1.0, 0.0, 0.0]);
                }
            }
            "limit" => {
                if let Some(joint) = current.as_mut() {
                    joint.lower = fragment
                        .attributes
                        .get("lower")
                        .and_then(|value| value.parse().ok());
                    joint.upper = fragment
                        .attributes
                        .get("upper")
                        .and_then(|value| value.parse().ok());
                }
            }
            "origin" => {
                if let Some(joint) = current.as_mut() {
                    joint.translation = vector3(fragment.attributes.get("xyz"), [0.0, 0.0, 0.0]);
                    joint.rotation_wxyz =
                        rpy_to_wxyz(vector3(fragment.attributes.get("rpy"), [0.0, 0.0, 0.0]));
                }
            }
            _ => {}
        }
        if fragment.self_closing
            && fragment.tag == "joint"
            && let Some(joint) = current.take()
        {
            if joint.parent.is_empty() || joint.child.is_empty() {
                diagnostics.push(diagnostic(
                    "ROBOT_JOINT_ENDPOINT_MISSING",
                    DiagnosticSeverity::Fatal,
                    format!("joint {} is missing parent or child", joint.name),
                    None,
                ));
            } else {
                model.joints.push(joint);
            }
        }
    }
    if let Some(joint) = current {
        diagnostics.push(diagnostic(
            "ROBOT_XML_MALFORMED",
            DiagnosticSeverity::Fatal,
            format!("joint {} is not closed", joint.name),
            None,
        ));
    }
    let known_links = model
        .links
        .iter()
        .map(|link| link.name.as_str())
        .collect::<BTreeSet<_>>();
    if known_links.len() != model.links.len() {
        diagnostics.push(diagnostic(
            "ROBOT_LINK_NAME_DUPLICATE",
            DiagnosticSeverity::Fatal,
            "robot link names must be unique",
            None,
        ));
    }
    let known_joints = model
        .joints
        .iter()
        .map(|joint| joint.name.as_str())
        .collect::<BTreeSet<_>>();
    if known_joints.len() != model.joints.len() {
        diagnostics.push(diagnostic(
            "ROBOT_JOINT_NAME_DUPLICATE",
            DiagnosticSeverity::Fatal,
            "robot joint names must be unique",
            None,
        ));
    }
    let mut joint_children = BTreeSet::new();
    for joint in &model.joints {
        if !known_links.contains(joint.parent.as_str())
            || !known_links.contains(joint.child.as_str())
        {
            diagnostics.push(diagnostic(
                "ROBOT_JOINT_ENDPOINT_UNKNOWN",
                DiagnosticSeverity::Fatal,
                format!(
                    "joint {} references unknown link {} -> {}",
                    joint.name, joint.parent, joint.child
                ),
                None,
            ));
        }
        if !joint_children.insert(joint.child.as_str()) {
            diagnostics.push(diagnostic(
                "ROBOT_LINK_MULTIPLE_PARENTS",
                DiagnosticSeverity::Fatal,
                format!("link {} is driven by multiple joints", joint.child),
                None,
            ));
        }
    }
    for link in &mut model.links {
        link.parent_hint = model
            .joints
            .iter()
            .find(|joint| joint.child == link.name)
            .map(|joint| joint.parent.clone());
    }
    model
}

fn extract_mjcf_kinematics(
    text: &str,
    diagnostics: &mut Vec<ForgeDiagnostic>,
) -> RobotKinematicModel {
    let mut model = RobotKinematicModel {
        name: "mujoco_model".to_owned(),
        ..RobotKinematicModel::default()
    };
    let mut body_stack = Vec::<String>::new();
    let mut child_has_joint = BTreeSet::new();
    let mut angle_scale = std::f64::consts::PI / 180.0;
    for fragment in xml_fragments(text) {
        if fragment.closing {
            if fragment.tag == "body" {
                body_stack.pop();
            }
            continue;
        }
        match fragment.tag.as_str() {
            "mujoco" => {
                if let Some(name) = fragment.attributes.get("model") {
                    model.name.clone_from(name);
                }
            }
            "compiler" => {
                if fragment.attributes.get("angle").map(String::as_str) == Some("radian") {
                    angle_scale = 1.0;
                }
            }
            "body" => {
                let name = fragment
                    .attributes
                    .get("name")
                    .cloned()
                    .unwrap_or_else(|| format!("body_{}", model.links.len()));
                let parent = body_stack.last().cloned();
                let translation = vector3(fragment.attributes.get("pos"), [0.0, 0.0, 0.0]);
                let rotation =
                    quaternion_wxyz(fragment.attributes.get("quat"), [1.0, 0.0, 0.0, 0.0]);
                model.links.push(RobotKinematicLink {
                    name: name.clone(),
                    parent_hint: parent,
                    translation,
                    rotation_wxyz: rotation,
                });
                body_stack.push(name);
                if fragment.self_closing {
                    body_stack.pop();
                }
            }
            "joint" | "freejoint" => {
                let Some(child) = body_stack.last().cloned() else {
                    continue;
                };
                if !child_has_joint.insert(child.clone()) {
                    diagnostics.push(diagnostic(
                        "MJCF_MULTI_DOF_BODY_NATIVE",
                        DiagnosticSeverity::Warning,
                        format!(
                            "body {child} has multiple joints; only the first maps to the canonical placement graph"
                        ),
                        None,
                    ));
                    continue;
                }
                let link = model
                    .links
                    .iter()
                    .find(|link| link.name == child)
                    .expect("body stack resolves to a link");
                let parent = link
                    .parent_hint
                    .clone()
                    .unwrap_or_else(|| "world".to_owned());
                let joint_type = if fragment.tag == "freejoint" {
                    "free".to_owned()
                } else {
                    fragment
                        .attributes
                        .get("type")
                        .cloned()
                        .unwrap_or_else(|| "hinge".to_owned())
                };
                let range = parse_numbers(fragment.attributes.get("range"), 2);
                let range_scale = if joint_type == "hinge" {
                    angle_scale
                } else {
                    1.0
                };
                model.joints.push(RobotKinematicJoint {
                    name: fragment
                        .attributes
                        .get("name")
                        .cloned()
                        .unwrap_or_else(|| format!("joint_{}", model.joints.len())),
                    joint_type,
                    parent,
                    child,
                    axis: vector3(fragment.attributes.get("axis"), [0.0, 0.0, 1.0]),
                    lower: range.as_ref().map(|items| items[0] * range_scale),
                    upper: range.as_ref().map(|items| items[1] * range_scale),
                    translation: link.translation,
                    rotation_wxyz: link.rotation_wxyz,
                });
            }
            _ => {}
        }
    }
    let known_links = model
        .links
        .iter()
        .map(|link| link.name.as_str())
        .collect::<BTreeSet<_>>();
    if known_links.len() != model.links.len() {
        diagnostics.push(diagnostic(
            "ROBOT_LINK_NAME_DUPLICATE",
            DiagnosticSeverity::Fatal,
            "MJCF body names must be unique for canonical mapping",
            None,
        ));
    }
    let known_joints = model
        .joints
        .iter()
        .map(|joint| joint.name.as_str())
        .collect::<BTreeSet<_>>();
    if known_joints.len() != model.joints.len() {
        diagnostics.push(diagnostic(
            "ROBOT_JOINT_NAME_DUPLICATE",
            DiagnosticSeverity::Fatal,
            "MJCF joint names must be unique for canonical mapping",
            None,
        ));
    }
    model
}

/// Diagnose the safe structural subset of URDF or MJCF without resolving resources.
pub fn diagnose_robot_xml(format: &str, payload: &[u8]) -> RobotXmlDoctorReport {
    let source_digest = format!("sha256:{:x}", Sha256::digest(payload));
    let scan = scan_source(format, payload, u64::MAX);
    let mut diagnostics = scan.diagnostics.clone();
    let mut metrics = RobotXmlMetrics::default();
    let mut names: BTreeMap<String, Vec<String>> = BTreeMap::new();
    let mut unknown = BTreeSet::new();
    let known = known_robot_elements(format);
    let Ok(text) = std::str::from_utf8(payload) else {
        return RobotXmlDoctorReport {
            format: format.to_owned(),
            source_digest,
            safe: false,
            metrics,
            named_objects: names,
            unknown_elements: Vec::new(),
            kinematics: RobotKinematicModel::default(),
            diagnostics,
        };
    };
    let mut cursor = text;
    while let Some(start) = cursor.find('<') {
        cursor = &cursor[start + 1..];
        let Some(end) = cursor.find('>') else {
            diagnostics.push(diagnostic(
                "ROBOT_XML_MALFORMED",
                DiagnosticSeverity::Fatal,
                "unterminated XML element",
                None,
            ));
            break;
        };
        let fragment = cursor[..end].trim();
        cursor = &cursor[end + 1..];
        if fragment.is_empty()
            || fragment.starts_with('/')
            || fragment.starts_with('?')
            || fragment.starts_with('!')
        {
            continue;
        }
        let tag = fragment
            .split_whitespace()
            .next()
            .unwrap_or_default()
            .trim_end_matches('/');
        let local_tag = tag.rsplit(':').next().unwrap_or(tag).to_ascii_lowercase();
        let attributes = xml_attributes(fragment);
        if !known.contains(local_tag.as_str()) {
            unknown.insert(tag.to_owned());
        }
        if let Some(name) = attributes.get("name") {
            names
                .entry(local_tag.clone())
                .or_default()
                .push(name.clone());
        }
        match (format, local_tag.as_str()) {
            ("urdf", "link") => metrics.links += 1,
            ("mjcf", "body") => metrics.bodies += 1,
            (_, "joint" | "freejoint") => metrics.joints += 1,
            ("urdf", "visual") => metrics.visuals += 1,
            ("urdf", "collision") => metrics.collisions += 1,
            ("mjcf", "geom") => {
                metrics.visuals += 1;
                metrics.collisions += 1;
            }
            ("urdf", "actuator")
            | (
                "mjcf",
                "motor" | "position" | "velocity" | "general" | "cylinder" | "muscle" | "adhesion",
            ) => {
                metrics.actuators += 1;
            }
            (_, "camera") => metrics.cameras += 1,
            ("urdf", "sensor") => metrics.sensors += 1,
            (
                "mjcf",
                "accelerometer" | "velocimeter" | "gyro" | "force" | "torque" | "touch"
                | "rangefinder" | "jointpos" | "jointvel" | "actuatorpos" | "actuatorvel"
                | "actuatorfrc" | "framepos" | "framequat",
            ) => metrics.sensors += 1,
            ("urdf", "inertia") | ("mjcf", "inertial") => {
                check_inertia(format, &attributes, &mut diagnostics);
            }
            ("urdf", "mass") => {
                let invalid = attributes
                    .get("value")
                    .and_then(|value| value.parse::<f64>().ok())
                    .is_none_or(|value| !value.is_finite() || value <= 0.0);
                if invalid {
                    diagnostics.push(diagnostic(
                        "ROBOT_MASS_INVALID",
                        DiagnosticSeverity::Fatal,
                        "URDF mass value must be finite and greater than zero",
                        None,
                    ));
                }
            }
            _ => {}
        }
    }
    if metrics.links + metrics.bodies == 0 {
        diagnostics.push(diagnostic(
            "ROBOT_BODY_MISSING",
            DiagnosticSeverity::Fatal,
            "robot description contains no link or body",
            None,
        ));
    }
    if !unknown.is_empty() {
        diagnostics.push(diagnostic(
            "ROBOT_NATIVE_ELEMENTS_PRESERVED",
            DiagnosticSeverity::Warning,
            format!(
                "{} unknown element(s) require Native Payload preservation",
                unknown.len()
            ),
            None,
        ));
    }
    let kinematics = if format == "urdf" {
        extract_urdf_kinematics(text, &mut diagnostics)
    } else {
        extract_mjcf_kinematics(text, &mut diagnostics)
    };
    let safe = !diagnostics.iter().any(|item| {
        matches!(
            item.severity,
            DiagnosticSeverity::Error | DiagnosticSeverity::Fatal
        )
    });
    RobotXmlDoctorReport {
        format: format.to_owned(),
        source_digest,
        safe,
        metrics,
        named_objects: names,
        unknown_elements: unknown.into_iter().collect(),
        kinematics,
        diagnostics,
    }
}

fn little_u32(bytes: &[u8]) -> Option<u32> {
    Some(u32::from_le_bytes(bytes.get(..4)?.try_into().ok()?))
}

/// Validate the GLB container and inspect its JSON table counts.
pub fn diagnose_glb(payload: &[u8]) -> GlbDoctorReport {
    let source_digest = format!("sha256:{:x}", Sha256::digest(payload));
    let mut report = GlbDoctorReport {
        source_digest,
        valid: false,
        version: None,
        declared_length: None,
        json_chunk_length: None,
        nodes: 0,
        meshes: 0,
        materials: 0,
        textures: 0,
        images: 0,
        diagnostics: Vec::new(),
    };
    if payload.len() < 20 || &payload[..4] != b"glTF" {
        report.diagnostics.push(diagnostic(
            "GLB_HEADER_INVALID",
            DiagnosticSeverity::Fatal,
            "GLB requires a 12-byte glTF header and at least one chunk",
            None,
        ));
        return report;
    }
    report.version = little_u32(&payload[4..8]);
    report.declared_length = little_u32(&payload[8..12]);
    let chunk_length = little_u32(&payload[12..16]).unwrap_or_default();
    report.json_chunk_length = Some(chunk_length);
    if report.version != Some(2)
        || report.declared_length != Some(payload.len() as u32)
        || &payload[16..20] != b"JSON"
        || 20_usize.saturating_add(chunk_length as usize) > payload.len()
    {
        report.diagnostics.push(diagnostic(
            "GLB_CONTAINER_INVALID",
            DiagnosticSeverity::Fatal,
            "GLB version, declared length, or JSON chunk is invalid",
            None,
        ));
        return report;
    }
    let json_bytes = &payload[20..20 + chunk_length as usize];
    let Ok(document) = serde_json::from_slice::<serde_json::Value>(json_bytes) else {
        report.diagnostics.push(diagnostic(
            "GLB_JSON_INVALID",
            DiagnosticSeverity::Fatal,
            "GLB JSON chunk is not valid JSON",
            None,
        ));
        return report;
    };
    let count = |key: &str| {
        document
            .get(key)
            .and_then(serde_json::Value::as_array)
            .map_or(0, Vec::len)
    };
    report.nodes = count("nodes");
    report.meshes = count("meshes");
    report.materials = count("materials");
    report.textures = count("textures");
    report.images = count("images");
    report.valid = true;
    report
}

#[cfg(test)]
mod tests {
    use super::{
        diagnose_glb, diagnose_obj, diagnose_robot_xml, repair_obj_remove_degenerate, scan_source,
    };
    use std::collections::BTreeSet;

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

    #[test]
    fn requires_bounded_expansion_for_archives() {
        let scan = scan_source("openusd", b"PK\x03\x04payload", 1024);
        assert!(!scan.safe);
        assert_eq!(
            scan.diagnostics[0].code,
            "ARCHIVE_REQUIRES_ISOLATED_EXPANSION"
        );
    }

    #[test]
    fn accepts_ros_package_uri_but_rejects_remote_uri() {
        let package = br#"<robot><mesh filename="package://demo/meshes/link.obj"/></robot>"#;
        assert!(scan_source("urdf", package, 1024).safe);
        let remote = br#"<robot><mesh filename="https://example.com/link.obj"/></robot>"#;
        assert!(!scan_source("urdf", remote, 1024).safe);
    }

    #[test]
    fn committed_security_corpus_remains_rejected_or_repairable() {
        let external_obj =
            include_bytes!("../../../examples/negative/source-security/external-reference.obj");
        assert!(!scan_source("obj", external_obj, 4096).safe);
        let xxe = include_bytes!("../../../examples/negative/source-security/external-entity.urdf");
        assert!(!scan_source("urdf", xxe, 4096).safe);
        let degenerate =
            include_bytes!("../../../examples/negative/source-security/degenerate.obj");
        let report = diagnose_obj(degenerate);
        assert_eq!(report.metrics.degenerate_faces, 1);
        let repaired = repair_obj_remove_degenerate(degenerate).unwrap();
        assert_eq!(repaired.removed_degenerate_faces, 1);
    }

    #[test]
    fn diagnoses_committed_urdf_and_mjcf_examples() {
        let urdf = include_bytes!("../../../examples/ingestion/robot/simple.urdf");
        let report = diagnose_robot_xml("urdf", urdf);
        assert!(report.safe, "{:?}", report.diagnostics);
        assert_eq!(report.metrics.links, 2);
        assert_eq!(report.metrics.joints, 1);
        assert_eq!(report.kinematics.joints[0].parent, "base");
        assert_eq!(report.kinematics.joints[0].child, "arm");
        assert_eq!(report.kinematics.joints[0].joint_type, "revolute");

        let mjcf = include_bytes!("../../../examples/ingestion/robot/simple.mjcf");
        let report = diagnose_robot_xml("mjcf", mjcf);
        assert!(report.safe, "{:?}", report.diagnostics);
        assert_eq!(report.metrics.bodies, 2);
        assert_eq!(report.metrics.joints, 1);
        assert_eq!(report.metrics.cameras, 1);
        assert_eq!(report.kinematics.joints[0].parent, "base");
        assert_eq!(report.kinematics.joints[0].child, "arm");
        assert!(
            (report.kinematics.joints[0].lower.unwrap() + std::f64::consts::FRAC_PI_2).abs() < 1e-9
        );
    }

    #[test]
    fn rejects_physically_invalid_inertia() {
        let source =
            include_bytes!("../../../examples/negative/source-security/malformed-inertia.urdf");
        let report = diagnose_robot_xml("urdf", source);
        assert!(!report.safe);
        assert!(
            report
                .diagnostics
                .iter()
                .any(|item| item.code == "ROBOT_INERTIA_INVALID")
        );
    }

    #[test]
    fn rejects_duplicate_links_multiple_parents_and_invalid_mass() {
        let duplicate = br#"
          <robot name="invalid">
            <link name="base"/>
            <link name="base"/>
            <link name="child"/>
            <link name="other"/>
            <joint name="first" type="fixed">
              <parent link="base"/><child link="child"/>
            </joint>
            <joint name="second" type="fixed">
              <parent link="other"/><child link="child"/>
            </joint>
          </robot>
        "#;
        let report = diagnose_robot_xml("urdf", duplicate);
        assert!(!report.safe);
        let codes = report
            .diagnostics
            .iter()
            .map(|item| item.code.as_str())
            .collect::<BTreeSet<_>>();
        assert!(codes.contains("ROBOT_LINK_NAME_DUPLICATE"));
        assert!(codes.contains("ROBOT_LINK_MULTIPLE_PARENTS"));

        let invalid_mass =
            br#"<robot><link name="base"><inertial><mass value="0"/></inertial></link></robot>"#;
        let report = diagnose_robot_xml("urdf", invalid_mass);
        assert!(!report.safe);
        assert!(
            report
                .diagnostics
                .iter()
                .any(|item| item.code == "ROBOT_MASS_INVALID")
        );
    }

    #[test]
    fn diagnoses_minimal_glb_container() {
        let document = br#"{"asset":{"version":"2.0"},"nodes":[{}],"meshes":[{"primitives":[]}]}"#;
        let padded = (document.len() + 3) & !3;
        let mut glb = Vec::new();
        glb.extend_from_slice(b"glTF");
        glb.extend_from_slice(&2_u32.to_le_bytes());
        glb.extend_from_slice(&(20_u32 + padded as u32).to_le_bytes());
        glb.extend_from_slice(&(padded as u32).to_le_bytes());
        glb.extend_from_slice(b"JSON");
        glb.extend_from_slice(document);
        glb.resize(20 + padded, b' ');
        let report = diagnose_glb(&glb);
        assert!(report.valid, "{:?}", report.diagnostics);
        assert_eq!(report.nodes, 1);
        assert_eq!(report.meshes, 1);
    }
}
