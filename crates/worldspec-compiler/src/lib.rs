//! Deterministic reference compilers for the v0.1 MuJoCo and Three.js profiles.

use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashMap},
    fmt::{Display, Formatter},
    fs, io,
    path::{Path, PathBuf},
};
use worldspec_core::{canonical_json, canonical_sha256};

#[derive(Debug)]
pub enum CompilerError {
    Io(io::Error),
    Json(serde_json::Error),
    InvalidWorld(String),
}

impl Display for CompilerError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "compiler I/O error: {error}"),
            Self::Json(error) => write!(formatter, "compiler JSON error: {error}"),
            Self::InvalidWorld(error) => {
                write!(formatter, "invalid world for compilation: {error}")
            }
        }
    }
}

impl std::error::Error for CompilerError {}

impl From<io::Error> for CompilerError {
    fn from(value: io::Error) -> Self {
        Self::Io(value)
    }
}

impl From<serde_json::Error> for CompilerError {
    fn from(value: serde_json::Error) -> Self {
        Self::Json(value)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CompiledArtifact {
    pub path: String,
    pub media_type: String,
    pub digest: String,
    pub size_bytes: u64,
    pub role: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CompileSummary {
    pub target: String,
    pub artifacts: Vec<CompiledArtifact>,
    pub losses: Vec<Value>,
}

pub type ResourceMap = BTreeMap<String, Vec<u8>>;

fn values<'a>(world: &'a Value, key: &str) -> &'a [Value] {
    world
        .get(key)
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[])
}

fn field<'a>(value: &'a Value, key: &str) -> &'a str {
    value.get(key).and_then(Value::as_str).unwrap_or_default()
}

fn safe_name(id: &str) -> String {
    id.chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() {
                character
            } else {
                '_'
            }
        })
        .collect()
}

fn xml_escape(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('"', "&quot;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
}

fn number_list(value: Option<&Value>, fallback: &[f64]) -> Vec<f64> {
    value
        .and_then(Value::as_array)
        .map(|items| items.iter().filter_map(Value::as_f64).collect())
        .filter(|items: &Vec<f64>| items.len() == fallback.len())
        .unwrap_or_else(|| fallback.to_vec())
}

fn claim_nominals(world: &Value) -> HashMap<&str, &Value> {
    world
        .pointer("/evidenceGraph/claims")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|claim| Some((field(claim, "id"), claim.pointer("/assertion/nominal")?)))
        .collect()
}

fn entity_mass(world: &Value, entity_id: &str) -> Option<f64> {
    let claims = claim_nominals(world);
    values(world, "components")
        .iter()
        .find(|component| {
            field(component, "ownerEntity") == entity_id
                && field(component, "type") == "worldspec://component/physics.rigid_body"
        })
        .and_then(|component| component.pointer("/claimBindings/physics.mass"))
        .and_then(Value::as_str)
        .and_then(|claim_ref| claims.get(claim_ref))
        .and_then(|value| value.as_f64())
}

fn entity_mobility<'a>(world: &'a Value, entity_id: &str) -> &'a str {
    values(world, "components")
        .iter()
        .find(|component| {
            field(component, "ownerEntity") == entity_id
                && field(component, "type") == "worldspec://component/physics.rigid_body"
        })
        .and_then(|component| component.pointer("/properties/mobility"))
        .and_then(Value::as_str)
        .unwrap_or("static")
}

fn entity_dimensions(world: &Value, entity_id: &str) -> Option<Vec<f64>> {
    let claims = claim_nominals(world);
    for representation in values(world, "representations") {
        if field(representation, "subjectRef") != entity_id {
            continue;
        }
        let claim_refs = representation
            .get("claimRefs")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str);
        for claim_ref in claim_refs {
            if let Some(value) = claims.get(claim_ref) {
                let dimensions = number_list(Some(value), &[0.0, 0.0, 0.0]);
                if dimensions.iter().all(|number| *number > 0.0) {
                    return Some(dimensions);
                }
            }
        }
    }
    None
}

fn relation_for_entity<'a>(world: &'a Value, root_frame: &str) -> Option<&'a Value> {
    values(world, "relations")
        .iter()
        .find(|relation| field(relation, "childFrame") == root_frame)
}

fn representation_for_entity<'a>(
    world: &'a Value,
    entity_id: &str,
    preferred_role: &str,
) -> Option<&'a Value> {
    values(world, "representations")
        .iter()
        .find(|item| {
            field(item, "subjectRef") == entity_id && field(item, "role") == preferred_role
        })
        .or_else(|| {
            values(world, "representations").iter().find(|item| {
                field(item, "subjectRef") == entity_id && field(item, "role") == "visual"
            })
        })
}

fn source_format_for_digest<'a>(world: &'a Value, digest: &str) -> Option<&'a str> {
    values(world, "nativePayloads")
        .iter()
        .find(|payload| field(payload, "digest") == digest)
        .map(|payload| field(payload, "sourceFormat"))
}

fn representation_scale(representation: &Value) -> Vec<f64> {
    number_list(representation.pointer("/mapping/scale"), &[1.0, 1.0, 1.0])
}

fn append_unresolved_ingestion_losses(world: &Value, target: &str, losses: &mut Vec<Value>) {
    if world
        .pointer("/metadata/ingestion/unitStatus")
        .and_then(Value::as_str)
        == Some("unknown")
    {
        losses.push(json!({
            "id": format!("loss://{target}/ingestion/unit-scale"),
            "sourceRef": field(world, "id"),
            "capability": "capability://worldspec/canonical-unit-scale",
            "status": "unsupported",
            "targetBinding": target,
            "rationale": "The imported source unit has not been confirmed.",
            "consequence": "The bundle may be inspected, but cannot receive L2 certification."
        }));
    }
}

#[derive(Debug, Clone)]
struct MujocoMeshBinding {
    name: String,
    relative_path: String,
    scale: Vec<f64>,
    collision_authoritative: bool,
}

fn materialize_mujoco_meshes(
    world: &Value,
    output: &Path,
    resources: &ResourceMap,
    losses: &mut Vec<Value>,
) -> Result<(BTreeMap<String, MujocoMeshBinding>, Vec<CompiledArtifact>), CompilerError> {
    let mut bindings = BTreeMap::new();
    let mut artifacts = Vec::new();
    let mut written = BTreeMap::<String, String>::new();
    for entity in values(world, "entities") {
        let entity_id = field(entity, "id");
        let Some(representation) = representation_for_entity(world, entity_id, "collision") else {
            continue;
        };
        let digest = field(representation, "resourceDigest");
        let Some(bytes) = resources.get(digest) else {
            continue;
        };
        let source_format = source_format_for_digest(world, digest).unwrap_or_default();
        if source_format != "obj" {
            losses.push(json!({
                "id": format!("loss://mujoco/{}/mesh-format", safe_name(entity_id)),
                "sourceRef": field(representation, "id"),
                "capability": "capability://worldspec/mesh-format",
                "status": "unsupported",
                "targetBinding": "mujoco://asset/mesh",
                "rationale": format!("The reference MuJoCo compiler only materializes OBJ; source format is {source_format}."),
                "consequence": "A diagnostic primitive is emitted instead of the source mesh."
            }));
            continue;
        }
        let path = written.entry(digest.to_owned()).or_insert_with(|| {
            format!(
                "assets/{}.obj",
                digest.trim_start_matches("sha256:").to_ascii_lowercase()
            )
        });
        if !artifacts
            .iter()
            .any(|artifact: &CompiledArtifact| artifact.path == *path)
        {
            artifacts.push(write_artifact(output, path, "model/obj", "mesh", bytes)?);
        }
        let collision_authoritative = field(representation, "role") == "collision";
        if !collision_authoritative {
            losses.push(json!({
                "id": format!("loss://mujoco/{}/visual-only-mesh", safe_name(entity_id)),
                "sourceRef": field(representation, "id"),
                "capability": "capability://worldspec/collision-shape",
                "status": "unsupported",
                "targetBinding": format!("mujoco://geom/{}", safe_name(entity_id)),
                "rationale": "Only a visual representation exists; it is emitted with collision disabled.",
                "consequence": "The source shape is visible but cannot be used for physical task certification."
            }));
        }
        bindings.insert(
            entity_id.to_owned(),
            MujocoMeshBinding {
                name: format!("mesh_{}", safe_name(entity_id)),
                relative_path: path.clone(),
                scale: representation_scale(representation),
                collision_authoritative,
            },
        );
    }
    Ok((bindings, artifacts))
}

fn write_artifact(
    output: &Path,
    path: &str,
    media_type: &str,
    role: &str,
    bytes: &[u8],
) -> Result<CompiledArtifact, CompilerError> {
    let destination = output.join(path);
    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(&destination, bytes)?;
    Ok(CompiledArtifact {
        path: path.to_owned(),
        media_type: media_type.to_owned(),
        digest: format!("sha256:{:x}", Sha256::digest(bytes)),
        size_bytes: bytes.len() as u64,
        role: role.to_owned(),
    })
}

fn transform(relation: Option<&Value>) -> (Vec<f64>, Vec<f64>) {
    let translation = number_list(
        relation.and_then(|item| item.pointer("/transform/translation")),
        &[0.0, 0.0, 0.0],
    );
    let quaternion = number_list(
        relation.and_then(|item| item.pointer("/transform/rotationWxyz")),
        &[1.0, 0.0, 0.0, 0.0],
    );
    (translation, quaternion)
}

fn append_mujoco_body(
    xml: &mut String,
    world: &Value,
    entity: &Value,
    children: &HashMap<&str, Vec<&Value>>,
    mesh_bindings: &BTreeMap<String, MujocoMeshBinding>,
    losses: &mut Vec<Value>,
    depth: usize,
) {
    let id = field(entity, "id");
    let root_frame = field(entity, "rootFrame");
    let relation = relation_for_entity(world, root_frame);
    let (position, quaternion) = transform(relation);
    let indent = "  ".repeat(depth);
    xml.push_str(&format!(
        "{indent}<body name=\"{}\" pos=\"{} {} {}\" quat=\"{} {} {} {}\">\n",
        xml_escape(&safe_name(id)),
        position[0],
        position[1],
        position[2],
        quaternion[0],
        quaternion[1],
        quaternion[2],
        quaternion[3]
    ));

    let relation_type = relation.map(|item| field(item, "type")).unwrap_or_default();
    if relation_type.ends_with("joint.prismatic") {
        let axis = number_list(
            relation.and_then(|item| item.pointer("/parameters/axis")),
            &[1.0, 0.0, 0.0],
        );
        let lower = relation
            .and_then(|item| item.pointer("/parameters/lower"))
            .and_then(Value::as_f64)
            .unwrap_or(0.0);
        let upper = relation
            .and_then(|item| item.pointer("/parameters/upper"))
            .and_then(Value::as_f64)
            .unwrap_or(1.0);
        xml.push_str(&format!(
            "{indent}  <joint name=\"{}\" type=\"slide\" axis=\"{} {} {}\" range=\"{} {}\"/>\n",
            xml_escape(&safe_name(field(relation.unwrap(), "id"))),
            axis[0],
            axis[1],
            axis[2],
            lower,
            upper
        ));
    } else if relation_type.ends_with("joint.revolute") {
        let axis = number_list(
            relation.and_then(|item| item.pointer("/parameters/axis")),
            &[0.0, 0.0, 1.0],
        );
        let lower = relation
            .and_then(|item| item.pointer("/parameters/lower"))
            .and_then(Value::as_f64)
            .unwrap_or(-std::f64::consts::PI);
        let upper = relation
            .and_then(|item| item.pointer("/parameters/upper"))
            .and_then(Value::as_f64)
            .unwrap_or(std::f64::consts::PI);
        xml.push_str(&format!(
            "{indent}  <joint name=\"{}\" type=\"hinge\" axis=\"{} {} {}\" range=\"{} {}\"/>\n",
            xml_escape(&safe_name(field(relation.unwrap(), "id"))),
            axis[0],
            axis[1],
            axis[2],
            lower,
            upper
        ));
    } else if relation_type.ends_with("joint.ball") {
        xml.push_str(&format!(
            "{indent}  <joint name=\"{}\" type=\"ball\"/>\n",
            xml_escape(&safe_name(field(relation.unwrap(), "id")))
        ));
    } else if entity_mobility(world, id) == "dynamic" {
        xml.push_str(&format!(
            "{indent}  <freejoint name=\"{}_free\"/>\n",
            xml_escape(&safe_name(id))
        ));
        losses.push(json!({
            "id": format!("loss://mujoco/{name}/dynamic-placement", name = safe_name(id)),
            "sourceRef": relation.map(|value| field(value, "id")).unwrap_or(id),
            "capability": "capability://worldspec/dynamic-placement",
            "status": "converted",
            "targetBinding": format!("mujoco://body/{name}", name = safe_name(id)),
            "rationale": "A dynamic rigid body with a fixed initial placement is lowered to a MuJoCo free joint.",
            "consequence": "The placement initializes the free body but does not constrain it after simulation starts."
        }));
    }

    let mass = entity_mass(world, id);
    let mass_attribute = mass
        .map(|value| format!(" mass=\"{value}\""))
        .unwrap_or_default();
    if let Some(binding) = mesh_bindings.get(id) {
        let collision_attributes = if binding.collision_authoritative {
            ""
        } else {
            " contype=\"0\" conaffinity=\"0\""
        };
        xml.push_str(&format!(
            "{indent}  <geom name=\"{}_geom\" type=\"mesh\" mesh=\"{}\"{}{} rgba=\"0.55 0.65 0.8 1\"/>\n",
            xml_escape(&safe_name(id)),
            xml_escape(&binding.name),
            mass_attribute,
            collision_attributes
        ));
    } else {
        let dimensions = entity_dimensions(world, id);
        let size = dimensions
            .as_ref()
            .map(|values| values.iter().map(|value| value / 2.0).collect::<Vec<_>>())
            .unwrap_or_else(|| vec![0.1, 0.1, 0.1]);
        if dimensions.is_none() {
            losses.push(json!({
                "id": format!("loss://mujoco/{name}/collision-fallback", name = safe_name(id)),
                "sourceRef": id,
                "capability": "capability://worldspec/collision-shape",
                "status": "approximated",
                "targetBinding": format!("mujoco://geom/{name}", name = safe_name(id)),
                "rationale": "No resolved collision resource or dimensions were available; a 0.2 m diagnostic box was emitted.",
                "consequence": "Collision behavior is diagnostic only and cannot be used for task certification."
            }));
        }
        xml.push_str(&format!(
            "{indent}  <geom name=\"{}_geom\" type=\"box\" size=\"{} {} {}\"{} rgba=\"0.55 0.65 0.8 1\"/>\n",
            xml_escape(&safe_name(id)),
            size[0],
            size[1],
            size[2],
            mass_attribute
        ));
    }

    if let Some(entity_children) = children.get(id) {
        for child in entity_children {
            append_mujoco_body(
                xml,
                world,
                child,
                children,
                mesh_bindings,
                losses,
                depth + 1,
            );
        }
    }
    xml.push_str(&format!("{indent}</body>\n"));
}

pub fn compile_mujoco(
    world: &Value,
    output: impl AsRef<Path>,
) -> Result<CompileSummary, CompilerError> {
    compile_mujoco_with_resources(world, output, &ResourceMap::new())
}

pub fn compile_mujoco_with_resources(
    world: &Value,
    output: impl AsRef<Path>,
    resources: &ResourceMap,
) -> Result<CompileSummary, CompilerError> {
    let output = output.as_ref();
    fs::create_dir_all(output)?;
    let root_entity = field(world, "rootEntity");
    if root_entity.is_empty() {
        return Err(CompilerError::InvalidWorld(
            "rootEntity is missing".to_owned(),
        ));
    }
    let entities = values(world, "entities");
    let entity_by_id = entities
        .iter()
        .map(|entity| (field(entity, "id"), entity))
        .collect::<HashMap<_, _>>();
    let mut children = HashMap::<&str, Vec<&Value>>::new();
    for entity in entities {
        if let Some(owner) = entity.get("ownerEntity").and_then(Value::as_str) {
            children.entry(owner).or_default().push(entity);
        }
    }
    for items in children.values_mut() {
        items.sort_by_key(|entity| field(entity, "id"));
    }

    let mut losses = Vec::new();
    append_unresolved_ingestion_losses(world, "mujoco", &mut losses);
    let (mesh_bindings, mut artifacts) =
        materialize_mujoco_meshes(world, output, resources, &mut losses)?;
    let mut xml = String::from(
        "<mujoco model=\"worldspec\">\n  <compiler angle=\"radian\" coordinate=\"local\"/>\n  <option timestep=\"0.002\"/>\n",
    );
    if !mesh_bindings.is_empty() {
        xml.push_str("  <asset>\n");
        let mut unique_meshes = BTreeMap::new();
        for binding in mesh_bindings.values() {
            unique_meshes
                .entry(binding.name.as_str())
                .or_insert(binding);
        }
        for binding in unique_meshes.values() {
            xml.push_str(&format!(
                "    <mesh name=\"{}\" file=\"{}\" scale=\"{} {} {}\"/>\n",
                xml_escape(&binding.name),
                xml_escape(&binding.relative_path),
                binding.scale[0],
                binding.scale[1],
                binding.scale[2]
            ));
        }
        xml.push_str("  </asset>\n");
    }
    xml.push_str("  <worldbody>\n");
    if let Some(root_children) = children.get(root_entity) {
        for child in root_children {
            append_mujoco_body(
                &mut xml,
                world,
                child,
                &children,
                &mesh_bindings,
                &mut losses,
                2,
            );
        }
    } else if !entity_by_id.contains_key(root_entity) {
        return Err(CompilerError::InvalidWorld(
            "rootEntity does not resolve".to_owned(),
        ));
    }
    xml.push_str("  </worldbody>\n</mujoco>\n");
    artifacts.insert(
        0,
        write_artifact(
            output,
            "model.xml",
            "application/mujoco+xml",
            "entrypoint",
            xml.as_bytes(),
        )?,
    );
    Ok(CompileSummary {
        target: "mujoco".to_owned(),
        artifacts,
        losses,
    })
}

fn pad_to_4(bytes: &mut Vec<u8>, padding: u8) {
    while !bytes.len().is_multiple_of(4) {
        bytes.push(padding);
    }
}

fn cube_binary() -> (Vec<u8>, usize) {
    let positions: [[f32; 3]; 8] = [
        [-0.5, -0.5, -0.5],
        [0.5, -0.5, -0.5],
        [0.5, 0.5, -0.5],
        [-0.5, 0.5, -0.5],
        [-0.5, -0.5, 0.5],
        [0.5, -0.5, 0.5],
        [0.5, 0.5, 0.5],
        [-0.5, 0.5, 0.5],
    ];
    let indices: [u16; 36] = [
        0, 2, 1, 0, 3, 2, 4, 5, 6, 4, 6, 7, 0, 1, 5, 0, 5, 4, 1, 2, 6, 1, 6, 5, 2, 3, 7, 2, 7, 6,
        3, 0, 4, 3, 4, 7,
    ];
    let mut binary = Vec::new();
    for position in positions {
        for value in position {
            binary.extend_from_slice(&value.to_le_bytes());
        }
    }
    let index_offset = binary.len();
    for index in indices {
        binary.extend_from_slice(&index.to_le_bytes());
    }
    pad_to_4(&mut binary, 0);
    (binary, index_offset)
}

fn build_glb(world: &Value, losses: &mut Vec<Value>) -> Result<Vec<u8>, CompilerError> {
    let (binary, index_offset) = cube_binary();
    let root_entity = field(world, "rootEntity");
    let mut nodes = vec![json!({
        "name": "worldspec_axis_mapping",
        "rotation": [
            -std::f64::consts::FRAC_1_SQRT_2,
            0.0,
            0.0,
            std::f64::consts::FRAC_1_SQRT_2
        ],
        "children": []
    })];
    let mut entity_node = BTreeMap::<&str, usize>::new();
    for entity in values(world, "entities") {
        let id = field(entity, "id");
        if id == root_entity || field(entity, "kind") != "spatial" {
            continue;
        }
        let relation = relation_for_entity(world, field(entity, "rootFrame"));
        let (translation, quaternion) = transform(relation);
        let dimensions = entity_dimensions(world, id).unwrap_or_else(|| {
            losses.push(json!({
                "id": format!("loss://threejs/{name}/visual-fallback", name = safe_name(id)),
                "sourceRef": id,
                "capability": "capability://worldspec/visual-representation",
                "status": "approximated",
                "targetBinding": format!("gltf://node/{name}", name = safe_name(id)),
                "rationale": "No resolved visual resource or dimensions were available; a 0.2 m diagnostic box was emitted.",
                "consequence": "The preview communicates placement and identity but not source visual fidelity."
            }));
            vec![0.2, 0.2, 0.2]
        });
        let node_index = nodes.len();
        nodes.push(json!({
            "name": safe_name(id),
            "mesh": 0,
            "translation": translation,
            "rotation": [quaternion[1], quaternion[2], quaternion[3], quaternion[0]],
            "scale": dimensions,
            "extras": {"worldspecId": id}
        }));
        entity_node.insert(id, node_index);
    }
    for entity in values(world, "entities") {
        let id = field(entity, "id");
        let Some(&node_index) = entity_node.get(id) else {
            continue;
        };
        let owner = entity.get("ownerEntity").and_then(Value::as_str);
        let parent_index = owner
            .and_then(|owner| entity_node.get(owner).copied())
            .unwrap_or(0);
        let children = nodes[parent_index]
            .as_object_mut()
            .unwrap()
            .entry("children")
            .or_insert_with(|| json!([]))
            .as_array_mut()
            .unwrap();
        children.push(Value::from(node_index));
    }
    let gltf = json!({
        "asset": {"version": "2.0", "generator": "WorldSpec Three.js reference compiler 0.1.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "meshes": [{
            "primitives": [{
                "attributes": {"POSITION": 0},
                "indices": 1,
                "material": 0
            }]
        }],
        "materials": [{
            "name": "worldspec_diagnostic_material",
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.2, 0.45, 0.8, 1.0],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.65
            }
        }],
        "buffers": [{"byteLength": binary.len()}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": index_offset, "target": 34962},
            {"buffer": 0, "byteOffset": index_offset, "byteLength": 72, "target": 34963}
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 8,
                "type": "VEC3",
                "min": [-0.5, -0.5, -0.5],
                "max": [0.5, 0.5, 0.5]
            },
            {
                "bufferView": 1,
                "componentType": 5123,
                "count": 36,
                "type": "SCALAR"
            }
        ]
    });
    let mut json_bytes =
        canonical_json(&gltf).map_err(|error| CompilerError::InvalidWorld(error.to_string()))?;
    pad_to_4(&mut json_bytes, b' ');
    let total_length = 12 + 8 + json_bytes.len() + 8 + binary.len();
    let mut glb = Vec::with_capacity(total_length);
    glb.extend_from_slice(&0x46546C67_u32.to_le_bytes());
    glb.extend_from_slice(&2_u32.to_le_bytes());
    glb.extend_from_slice(&(total_length as u32).to_le_bytes());
    glb.extend_from_slice(&(json_bytes.len() as u32).to_le_bytes());
    glb.extend_from_slice(&0x4E4F534A_u32.to_le_bytes());
    glb.extend_from_slice(&json_bytes);
    glb.extend_from_slice(&(binary.len() as u32).to_le_bytes());
    glb.extend_from_slice(&0x004E4942_u32.to_le_bytes());
    glb.extend_from_slice(&binary);
    Ok(glb)
}

pub fn compile_threejs(
    world: &Value,
    output: impl AsRef<Path>,
) -> Result<CompileSummary, CompilerError> {
    compile_threejs_with_resources(world, output, &ResourceMap::new())
}

pub fn compile_threejs_with_resources(
    world: &Value,
    output: impl AsRef<Path>,
    resources: &ResourceMap,
) -> Result<CompileSummary, CompilerError> {
    let output = output.as_ref();
    fs::create_dir_all(output)?;
    let mut losses = Vec::new();
    append_unresolved_ingestion_losses(world, "threejs", &mut losses);
    let source_glb = values(world, "representations")
        .iter()
        .filter(|item| {
            field(item, "role") == "visual"
                && field(item, "type") == "gltf_binary_pbr"
                && source_format_for_digest(world, field(item, "resourceDigest")) == Some("glb")
        })
        .filter_map(|item| {
            let digest = field(item, "resourceDigest");
            Some((item, resources.get(digest)?))
        })
        .collect::<Vec<_>>();
    let (glb, source_binding) = if source_glb.len() == 1 {
        let (representation, bytes) = source_glb[0];
        losses.push(json!({
            "id": "loss://threejs/source-glb/stable-id-wrapper",
            "sourceRef": field(representation, "id"),
            "capability": "capability://worldspec/stable-id-binding",
            "status": "converted",
            "targetBinding": "threejs://scene/source-root",
            "rationale": "The source GLB is preserved byte-for-byte and its root is bound to the WorldSpec entity by the scene manifest.",
            "consequence": "Source-internal node names remain native and are not rewritten."
        }));
        (
            bytes.to_vec(),
            Some(json!({
                "entityRef": field(representation, "subjectRef"),
                "representationRef": field(representation, "id"),
                "strategy": "manifest_root_binding"
            })),
        )
    } else {
        (build_glb(world, &mut losses)?, None)
    };
    let mut artifacts = vec![write_artifact(
        output,
        "scene.glb",
        "model/gltf-binary",
        "scene",
        &glb,
    )?];
    let manifest = json!({
        "specVersion": "0.1.0",
        "worldDigest": canonical_sha256(world)
            .map_err(|error| CompilerError::InvalidWorld(error.to_string()))?,
        "coordinateMapping": {
            "source": {"handedness": "right", "up": "+Z", "forward": "+X"},
            "target": {"handedness": "right", "up": "+Y", "forward": "-Z"},
            "rootRotationXDegrees": -90
        },
        "scene": "scene.glb",
        "sourceSceneBinding": source_binding,
        "stableIds": values(world, "entities")
            .iter()
            .map(|entity| (field(entity, "id"), safe_name(field(entity, "id"))))
            .collect::<BTreeMap<_, _>>()
    });
    let manifest_bytes = canonical_json(&manifest)
        .map_err(|error| CompilerError::InvalidWorld(error.to_string()))?;
    artifacts.push(write_artifact(
        output,
        "scene-manifest.json",
        "application/vnd.worldspec.threejs-scene+json",
        "manifest",
        &manifest_bytes,
    )?);
    Ok(CompileSummary {
        target: "threejs".to_owned(),
        artifacts,
        losses,
    })
}

pub fn write_compile_summary(
    summary: &CompileSummary,
    output: impl AsRef<Path>,
) -> Result<PathBuf, CompilerError> {
    let path = output.as_ref().join("compile-summary.json");
    let mut bytes = serde_json::to_vec_pretty(summary)?;
    bytes.push(b'\n');
    fs::write(&path, bytes)?;
    Ok(path)
}

#[cfg(test)]
mod tests {
    use super::{
        ResourceMap, compile_mujoco, compile_mujoco_with_resources, compile_threejs,
        compile_threejs_with_resources,
    };
    use serde_json::{Value, json};
    use sha2::{Digest, Sha256};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn world() -> Value {
        serde_json::from_str(include_str!("../../../examples/minimal-cube/world.json")).unwrap()
    }

    fn temporary(name: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "worldspec-compiler-{name}-{}",
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ))
    }

    #[test]
    fn output_is_deterministic() {
        let first = temporary("first");
        let second = temporary("second");
        let first_mujoco = compile_mujoco(&world(), &first).unwrap();
        let second_mujoco = compile_mujoco(&world(), &second).unwrap();
        assert_eq!(
            first_mujoco.artifacts[0].digest,
            second_mujoco.artifacts[0].digest
        );
        let first_three = compile_threejs(&world(), &first).unwrap();
        let second_three = compile_threejs(&world(), &second).unwrap();
        assert_eq!(
            first_three.artifacts[0].digest,
            second_three.artifacts[0].digest
        );
        std::fs::remove_dir_all(first).unwrap();
        std::fs::remove_dir_all(second).unwrap();
    }

    #[test]
    fn materializes_resolved_obj_for_mujoco() {
        let output = temporary("obj-resource");
        let mut world = world();
        let bytes = include_bytes!("../../../examples/minimal-cube/source/cube.obj").to_vec();
        let digest = format!("sha256:{:x}", Sha256::digest(&bytes));
        world["representations"] = json!([{
            "id": "representation://cube/source-visual",
            "subjectRef": "entity://cube/body",
            "role": "visual",
            "type": "triangle_mesh",
            "anchorFrame": "frame://cube/body",
            "resourceDigest": digest,
            "fidelity": "source"
        }]);
        world["nativePayloads"] = json!([{
            "id": "native://cube/source-obj",
            "sourceFormat": "obj",
            "sourceVersion": "unknown",
            "digest": digest,
            "namespace": "worldspec.test",
            "rightsStatus": "cleared"
        }]);
        let resources = ResourceMap::from([(digest, bytes)]);
        let summary = compile_mujoco_with_resources(&world, &output, &resources).unwrap();
        assert!(summary.artifacts.iter().any(|item| item.role == "mesh"));
        let xml = std::fs::read_to_string(output.join("model.xml")).unwrap();
        assert!(xml.contains("<mesh name="));
        assert!(xml.contains("contype=\"0\" conaffinity=\"0\""));
        std::fs::remove_dir_all(output).unwrap();
    }

    #[test]
    fn preserves_single_resolved_source_glb_byte_for_byte() {
        let source_output = temporary("source-glb");
        let output = temporary("resolved-glb");
        compile_threejs(&world(), &source_output).unwrap();
        let source = std::fs::read(source_output.join("scene.glb")).unwrap();
        let digest = format!("sha256:{:x}", Sha256::digest(&source));
        let mut imported = world();
        imported["representations"] = json!([{
            "id": "representation://cube/source-glb",
            "subjectRef": "entity://cube/body",
            "role": "visual",
            "type": "gltf_binary_pbr",
            "anchorFrame": "frame://cube/body",
            "resourceDigest": digest,
            "fidelity": "source"
        }]);
        imported["nativePayloads"] = json!([{
            "id": "native://cube/source-glb",
            "sourceFormat": "glb",
            "sourceVersion": "2.0",
            "digest": digest,
            "namespace": "worldspec.test",
            "rightsStatus": "cleared"
        }]);
        let resources = ResourceMap::from([(digest, source.clone())]);
        compile_threejs_with_resources(&imported, &output, &resources).unwrap();
        assert_eq!(source, std::fs::read(output.join("scene.glb")).unwrap());
        std::fs::remove_dir_all(source_output).unwrap();
        std::fs::remove_dir_all(output).unwrap();
    }
}
