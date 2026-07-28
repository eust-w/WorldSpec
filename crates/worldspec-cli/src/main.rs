use clap::{Parser, Subcommand, ValueEnum};
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    path::{Path, PathBuf},
    process::ExitCode,
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use worldspec_cas::{Cas, JobStatus};
use worldspec_cert::{
    CertificationAssessment, assess_l2_bindings, assess_l3_bindings, sign_certificate_with_seed,
    verify_bundle_artifacts,
};
use worldspec_compiler::{
    ResourceMap, compile_mujoco_with_resources, compile_threejs_with_resources,
    write_compile_summary,
};
use worldspec_core::{ValidationReport, canonical_json, canonical_sha256, validate_file};
use worldspec_forge::{
    DiagnosticSeverity, ForgeDiagnostic, RobotKinematicModel, diagnose_glb, diagnose_obj,
    diagnose_robot_xml, repair_obj_remove_degenerate, scan_source,
};

const DEFAULT_SOURCE_LIMIT_BYTES: u64 = 8_589_934_592;

#[derive(Parser, Debug)]
#[command(name = "worldspec", version, about = "WorldSpec 0.1 local CLI")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand, Debug)]
#[allow(clippy::large_enum_variant)]
enum Command {
    /// Ingest local immutable sources into the CAS and produce an AssetDraft.
    Ingest {
        #[arg(required = true)]
        inputs: Vec<PathBuf>,
        #[arg(long)]
        rights: PathBuf,
        #[arg(long)]
        output: PathBuf,
        #[arg(long)]
        candidate_output: Option<PathBuf>,
        #[arg(long, default_value = ".worldspec")]
        cas_root: PathBuf,
        #[arg(long, default_value = "schemas/0.1")]
        schema_dir: PathBuf,
    },
    /// Queue a generation job using an explicit GenerationProfile.
    Generate(JobSubmitArgs),
    /// Queue a fail-closed locomotion training job using an explicit profile.
    Train(JobSubmitArgs),
    /// Inspect a JSON document and compute its canonical digest.
    Inspect {
        input: PathBuf,
        #[arg(long)]
        schema: Option<String>,
        #[arg(long, default_value = "schemas/0.1")]
        schema_dir: PathBuf,
    },
    /// Resolve a CAS digest to bytes.
    Resolve {
        digest: String,
        #[arg(long)]
        output: PathBuf,
        #[arg(long, default_value = ".worldspec")]
        cas_root: PathBuf,
    },
    /// Diagnose or queue repair of an asset draft.
    Doctor {
        #[command(subcommand)]
        command: DoctorCommand,
    },
    /// Validate a JSON document against a schema and semantic invariants.
    Validate {
        input: PathBuf,
        #[arg(long, default_value = "world-definition.schema.json")]
        schema: String,
        #[arg(long, default_value = "schemas/0.1")]
        schema_dir: PathBuf,
        #[arg(long)]
        target_profile: Option<PathBuf>,
        #[arg(long, value_enum, default_value_t = OutputFormat::Text)]
        output: OutputFormat,
    },
    /// Compile a WorldDefinition into a local MuJoCo or Three.js bundle.
    Compile {
        #[arg(long)]
        input: PathBuf,
        #[arg(long)]
        target_profile: PathBuf,
        #[arg(long)]
        build_intent: PathBuf,
        #[arg(long)]
        output_dir: PathBuf,
        #[arg(long, default_value = ".worldspec")]
        cas_root: PathBuf,
        #[arg(long, default_value = "schemas/0.1")]
        schema_dir: PathBuf,
    },
    /// Validate and optionally Ed25519-sign a certificate document.
    Certify {
        /// Existing Certificate to validate/sign. Omit to issue L2 from bound evidence.
        input: Option<PathBuf>,
        #[arg(long)]
        output: PathBuf,
        /// Explicit issuer name when creating a new Certificate.
        #[arg(long)]
        issuer: Option<String>,
        /// Canonical WorldDefinition bound by a valid L2 certificate.
        #[arg(long)]
        world: Option<PathBuf>,
        /// TargetProfile used by the certified build.
        #[arg(long)]
        target_profile: Option<PathBuf>,
        /// BuildManifest emitted by the compiler.
        #[arg(long)]
        build_manifest: Option<PathBuf>,
        /// Complete LossReport emitted by the compiler.
        #[arg(long)]
        loss_report: Option<PathBuf>,
        /// Executed ConformanceReport for this exact build.
        #[arg(long)]
        conformance_report: Option<PathBuf>,
        /// TaskProfile required when issuing or validating an L3 certificate.
        #[arg(long)]
        task_profile: Option<PathBuf>,
        /// ControlProfile bound by an L3 TaskProfile.
        #[arg(long)]
        control_profile: Option<PathBuf>,
        /// PredicateProfile documents bound by an L3 TaskProfile.
        #[arg(long)]
        predicate_profile: Vec<PathBuf>,
        /// Canonical locked initial-state JSON for L3.
        #[arg(long)]
        initial_state: Option<PathBuf>,
        /// RuntimeRecord documents for every declared L3 run.
        #[arg(long)]
        runtime_record: Vec<PathBuf>,
        /// Executed TaskRunReport for L3.
        #[arg(long)]
        task_run_report: Option<PathBuf>,
        /// Directory containing all BuildManifest artifacts.
        #[arg(long)]
        bundle_dir: Option<PathBuf>,
        /// Optional machine-readable assessment, written on pass or failure.
        #[arg(long)]
        assessment_output: Option<PathBuf>,
        /// File containing a 32-byte Ed25519 seed as 64 lowercase hex digits.
        #[arg(long)]
        signing_key: Option<PathBuf>,
        #[arg(long)]
        public_key_id: Option<String>,
        #[arg(long, default_value = "schemas/0.1")]
        schema_dir: PathBuf,
    },
    /// Queue a bundle assembly job.
    Bundle(JobSubmitArgs),
    /// Inspect or cancel a local job.
    Job {
        #[command(subcommand)]
        command: JobCommand,
    },
}

#[derive(clap::Args, Debug)]
struct JobSubmitArgs {
    #[arg(long)]
    input: PathBuf,
    #[arg(long)]
    profile: PathBuf,
    #[arg(long)]
    output: PathBuf,
    #[arg(long, default_value = ".worldspec")]
    cas_root: PathBuf,
    #[arg(long, default_value_t = 3600)]
    timeout_seconds: u64,
    #[arg(long, default_value_t = 8_589_934_592_u64)]
    memory_bytes: u64,
    #[arg(long, default_value_t = 0)]
    gpu_count: u64,
}

#[derive(Subcommand, Debug)]
enum DoctorCommand {
    Diagnose {
        input: PathBuf,
        #[arg(long, default_value = "asset-draft.schema.json")]
        schema: String,
        #[arg(long, default_value = "schemas/0.1")]
        schema_dir: PathBuf,
        #[arg(long)]
        output: PathBuf,
    },
    Repair {
        input: PathBuf,
        #[arg(long)]
        output: PathBuf,
        #[arg(long)]
        derivation: PathBuf,
        #[arg(long, default_value = ".worldspec")]
        cas_root: PathBuf,
    },
}

#[derive(Subcommand, Debug)]
enum JobCommand {
    Get {
        id: String,
        #[arg(long, default_value = ".worldspec")]
        cas_root: PathBuf,
    },
    Cancel {
        id: String,
        #[arg(long, default_value = ".worldspec")]
        cas_root: PathBuf,
    },
    Wait {
        id: String,
        #[arg(long, default_value = ".worldspec")]
        cas_root: PathBuf,
        #[arg(long, default_value_t = 300)]
        timeout_seconds: u64,
    },
}

#[derive(Clone, Copy, Debug, ValueEnum)]
enum OutputFormat {
    Text,
    Json,
}

fn read_json(path: &Path) -> Result<Value, String> {
    let raw = fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    serde_json::from_str(&raw)
        .map_err(|error| format!("cannot parse {} as JSON: {error}", path.display()))
}

fn write_json(path: &Path, value: &Value) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| format!("output has no parent: {}", path.display()))?;
    fs::create_dir_all(parent)
        .map_err(|error| format!("cannot create {}: {error}", parent.display()))?;
    let mut bytes = serde_json::to_vec_pretty(value)
        .map_err(|error| format!("cannot serialize JSON: {error}"))?;
    bytes.push(b'\n');
    fs::write(path, bytes).map_err(|error| format!("cannot write {}: {error}", path.display()))
}

fn print_report(report: &ValidationReport, format: OutputFormat) -> Result<(), String> {
    match format {
        OutputFormat::Json => {
            let rendered = serde_json::to_string_pretty(report)
                .map_err(|error| format!("cannot serialize validation report: {error}"))?;
            println!("{rendered}");
        }
        OutputFormat::Text => {
            println!(
                "{}: {} ({})",
                if report.valid { "VALID" } else { "INVALID" },
                report.schema,
                report.diagnostics.len()
            );
            for diagnostic in &report.diagnostics {
                println!(
                    "{:?} {} path={} object={} {}",
                    diagnostic.severity,
                    diagnostic.code,
                    diagnostic.path.as_deref().unwrap_or("-"),
                    diagnostic.object_ref.as_deref().unwrap_or("-"),
                    diagnostic.message
                );
            }
        }
    }
    Ok(())
}

fn format_for(path: &Path) -> Result<&'static str, String> {
    let extension = path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    match extension.as_str() {
        "glb" => Ok("glb"),
        "obj" => Ok("obj"),
        "urdf" => Ok("urdf"),
        "mjcf" => Ok("mjcf"),
        "xml" => Ok("mjcf"),
        "step" | "stp" => Ok("step"),
        "iges" | "igs" => Ok("iges"),
        "usd" | "usda" | "usdc" | "usdz" => Ok("openusd"),
        "png" | "jpg" | "jpeg" | "webp" => Ok("image"),
        "mp4" | "mov" | "mkv" | "webm" => Ok("video"),
        _ => Err(format!("unsupported input format: {}", path.display())),
    }
}

fn media_type(format: &str) -> &'static str {
    match format {
        "glb" => "model/gltf-binary",
        "obj" => "model/obj",
        "urdf" | "mjcf" => "application/xml",
        "step" | "iges" => "model/step",
        "openusd" => "model/vnd.usd",
        "image" => "image/*",
        "video" => "video/*",
        _ => "application/octet-stream",
    }
}

fn local_id(kind: &str, operation: &str) -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!("{kind}://local/{operation}-{nanos}")
}

fn visual_world_candidate(
    format: &str,
    resource_digest: &str,
    rights_status: &str,
    display_name: &str,
) -> Value {
    let suffix = resource_digest.trim_start_matches("sha256:");
    let root_entity = format!("entity://ingest/{suffix}/world");
    let asset_entity = format!("entity://ingest/{suffix}/asset");
    let root_frame = format!("frame://ingest/{suffix}/world");
    let asset_frame = format!("frame://ingest/{suffix}/asset");
    let evidence = format!("evidence://ingest/{suffix}/source");
    let representation = format!("representation://ingest/{suffix}/visual");
    json!({
        "id": format!("world://ingest/{suffix}"),
        "specVersion": "0.1.0",
        "conventions": {
            "lengthUnit": "meter",
            "massUnit": "kilogram",
            "timeUnit": "second",
            "angleUnit": "radian",
            "handedness": "right",
            "upAxis": "+Z",
            "forwardAxis": "+X",
            "quaternionOrder": "wxyz"
        },
        "rootEntity": root_entity,
        "rootFrame": root_frame,
        "entities": [
            {
                "id": root_entity,
                "kind": "spatial",
                "displayName": "World",
                "rootFrame": root_frame
            },
            {
                "id": asset_entity,
                "kind": "spatial",
                "displayName": display_name,
                "ownerEntity": root_entity,
                "rootFrame": asset_frame,
                "tags": ["imported", format]
            }
        ],
        "frames": [
            {
                "id": root_frame,
                "ownerEntity": root_entity,
                "role": "world"
            },
            {
                "id": asset_frame,
                "ownerEntity": asset_entity,
                "role": "canonical_root"
            }
        ],
        "components": [],
        "relations": [
            {
                "id": format!("relation://ingest/{suffix}/placement"),
                "type": "worldspec://relation/frame.fixed",
                "schemaVersion": "0.1.0",
                "endpoints": {
                    "parent": root_frame,
                    "child": asset_frame
                },
                "parentFrame": root_frame,
                "childFrame": asset_frame,
                "transform": {
                    "translation": [0.0, 0.0, 0.0],
                    "rotationWxyz": [1.0, 0.0, 0.0, 0.0]
                }
            }
        ],
        "representations": [
            {
                "id": representation,
                "subjectRef": asset_entity,
                "role": "visual",
                "type": if format == "glb" {"gltf_binary_pbr"} else {"triangle_mesh"},
                "anchorFrame": asset_frame,
                "resourceDigest": resource_digest,
                "fidelity": "source"
            }
        ],
        "models": [],
        "evidenceGraph": {
            "sources": [
                {
                    "id": evidence,
                    "kind": "source_asset",
                    "digest": resource_digest,
                    "rightsStatus": rights_status,
                    "notes": "Imported immutable visual source; scale and physical properties are unresolved."
                }
            ],
            "claims": [],
            "derivations": []
        },
        "clockDomains": [
            {
                "id": format!("clock://ingest/{suffix}/simulation"),
                "kind": "simulation",
                "unit": "second",
                "synchronizationPolicy": "authoritative"
            }
        ],
        "stateChannels": [],
        "initialState": [],
        "nativePayloads": [
            {
                "id": format!("native://ingest/{suffix}/{format}"),
                "sourceFormat": format,
                "sourceVersion": if format == "glb" {"2.0"} else {"unknown"},
                "digest": resource_digest,
                "namespace": "worldspec.ingestion.source",
                "rightsStatus": rights_status,
                "targetScope": [format]
            }
        ],
        "metadata": {
            "ingestion": {
                "format": format,
                "unitStatus": "unknown",
                "physicsStatus": "unresolved"
            }
        }
    })
}

fn id_segments(names: impl Iterator<Item = String>) -> BTreeMap<String, String> {
    let mut result = BTreeMap::new();
    let mut used = BTreeSet::new();
    for (index, name) in names.enumerate() {
        let base = name
            .chars()
            .map(|character| {
                if character.is_ascii_alphanumeric() || matches!(character, '-' | '_') {
                    character.to_ascii_lowercase()
                } else {
                    '-'
                }
            })
            .collect::<String>()
            .trim_matches('-')
            .to_owned();
        let base = if base.is_empty() {
            format!("item-{index}")
        } else {
            base
        };
        let mut candidate = base.clone();
        let mut suffix = 2;
        while !used.insert(candidate.clone()) {
            candidate = format!("{base}-{suffix}");
            suffix += 1;
        }
        result.insert(name, candidate);
    }
    result
}

fn robot_world_candidate(
    format: &str,
    resource_digest: &str,
    rights_status: &str,
    kinematics: &RobotKinematicModel,
) -> Result<Value, String> {
    if kinematics.links.is_empty() {
        return Err("robot kinematics contains no link or body".to_owned());
    }
    let unsupported = kinematics
        .joints
        .iter()
        .filter(|joint| {
            !matches!(
                (format, joint.joint_type.as_str()),
                ("urdf", "fixed" | "revolute" | "continuous" | "prismatic")
                    | ("mjcf", "fixed" | "hinge" | "slide" | "ball")
            )
        })
        .map(|joint| format!("{}:{}", joint.name, joint.joint_type))
        .collect::<Vec<_>>();
    if !unsupported.is_empty() {
        return Err(format!(
            "unsupported canonical joint types: {}",
            unsupported.join(", ")
        ));
    }

    let suffix = resource_digest.trim_start_matches("sha256:");
    let segments = id_segments(
        kinematics
            .links
            .iter()
            .map(|link| link.name.clone())
            .chain(kinematics.joints.iter().map(|joint| joint.name.clone())),
    );
    let world_entity = format!("entity://ingest/{suffix}/world");
    let robot_entity = format!("entity://ingest/{suffix}/robot");
    let world_frame = format!("frame://ingest/{suffix}/world");
    let evidence = format!("evidence://ingest/{suffix}/source");
    let clock = format!("clock://ingest/{suffix}/simulation");
    let link_entity = |name: &str| {
        format!(
            "entity://ingest/{suffix}/robot/link/{}",
            segments.get(name).expect("validated robot link segment")
        )
    };
    let link_frame = |name: &str| {
        format!(
            "frame://ingest/{suffix}/robot/link/{}",
            segments.get(name).expect("validated robot link segment")
        )
    };

    let mut entities = vec![
        json!({
            "id": world_entity,
            "kind": "spatial",
            "displayName": "World",
            "rootFrame": world_frame
        }),
        json!({
            "id": robot_entity,
            "kind": "logical",
            "displayName": if kinematics.name.is_empty() {"Imported robot"} else {kinematics.name.as_str()},
            "ownerEntity": world_entity,
            "tags": ["imported", "robot", format]
        }),
    ];
    let mut frames = vec![json!({
        "id": world_frame,
        "ownerEntity": world_entity,
        "role": "world"
    })];
    let mut components = Vec::new();
    for link in &kinematics.links {
        let entity = link_entity(&link.name);
        let frame = link_frame(&link.name);
        entities.push(json!({
            "id": entity,
            "kind": "spatial",
            "displayName": link.name,
            "ownerEntity": robot_entity,
            "rootFrame": frame,
            "tags": ["imported", "robot-link"]
        }));
        frames.push(json!({
            "id": frame,
            "ownerEntity": entity,
            "role": "canonical_root"
        }));
        components.push(json!({
            "id": format!("component://ingest/{suffix}/robot/link/{}/kinematics", segments[&link.name]),
            "type": "worldspec://component/kinematics.link",
            "schemaVersion": "0.1.0",
            "ownerEntity": entity,
            "anchorFrame": frame,
            "properties": {
                "sourceFormat": format,
                "sourceName": link.name
            }
        }));
    }

    let joint_by_child = kinematics
        .joints
        .iter()
        .map(|joint| (joint.child.as_str(), joint))
        .collect::<BTreeMap<_, _>>();
    let mut relations = Vec::new();
    let mut state_channels = Vec::new();
    let mut initial_state = Vec::new();
    for link in &kinematics.links {
        let child_frame = link_frame(&link.name);
        if let Some(joint) = joint_by_child.get(link.name.as_str()) {
            let parent_frame = if joint.parent == "world" {
                world_frame.clone()
            } else {
                link_frame(&joint.parent)
            };
            let relation_type = match joint.joint_type.as_str() {
                "fixed" => "frame.fixed",
                "revolute" | "continuous" | "hinge" => "frame.joint.revolute",
                "prismatic" | "slide" => "frame.joint.prismatic",
                "ball" => "frame.joint.ball",
                _ => unreachable!("unsupported joint types were rejected"),
            };
            let relation_id = format!(
                "relation://ingest/{suffix}/robot/joint/{}",
                segments[&joint.name]
            );
            let mut relation = json!({
                "id": relation_id,
                "type": format!("worldspec://relation/{relation_type}"),
                "schemaVersion": "0.1.0",
                "endpoints": {
                    "parent": parent_frame,
                    "child": child_frame
                },
                "parentFrame": parent_frame,
                "childFrame": child_frame,
                "transform": {
                    "translation": joint.translation,
                    "rotationWxyz": joint.rotation_wxyz
                }
            });
            if relation_type != "frame.fixed" {
                let channel_id = format!(
                    "state://ingest/{suffix}/robot/joint/{}/position",
                    segments[&joint.name]
                );
                let mut parameters = json!({"axis": joint.axis});
                if let Some(lower) = joint.lower {
                    parameters["lower"] = Value::from(lower);
                }
                if let Some(upper) = joint.upper {
                    parameters["upper"] = Value::from(upper);
                }
                if joint.joint_type == "continuous" {
                    parameters["continuous"] = Value::Bool(true);
                }
                relation["parameters"] = parameters;
                relation["stateChannels"] = json!([channel_id]);
                state_channels.push(json!({
                    "id": channel_id,
                    "subjectRef": relation_id,
                    "property": "joint.position",
                    "valueType": "number",
                    "unit": if relation_type == "frame.joint.prismatic" {"meter"} else {"radian"},
                    "clockDomain": clock,
                    "interpolation": "linear",
                    "sourceKind": "simulated"
                }));
                initial_state.push(json!({
                    "channelRef": channel_id,
                    "value": 0.0
                }));
            }
            relations.push(relation);
        } else {
            let parent_frame = link
                .parent_hint
                .as_deref()
                .map(link_frame)
                .unwrap_or_else(|| world_frame.clone());
            relations.push(json!({
                "id": format!("relation://ingest/{suffix}/robot/fixed/{}", segments[&link.name]),
                "type": "worldspec://relation/frame.fixed",
                "schemaVersion": "0.1.0",
                "endpoints": {
                    "parent": parent_frame,
                    "child": child_frame
                },
                "parentFrame": parent_frame,
                "childFrame": child_frame,
                "transform": {
                    "translation": link.translation,
                    "rotationWxyz": link.rotation_wxyz
                }
            }));
        }
    }

    let component_ids = components
        .iter()
        .filter_map(|component| component.get("id").cloned())
        .collect::<Vec<_>>();
    Ok(json!({
        "id": format!("world://ingest/{suffix}"),
        "specVersion": "0.1.0",
        "conventions": {
            "lengthUnit": "meter",
            "massUnit": "kilogram",
            "timeUnit": "second",
            "angleUnit": "radian",
            "handedness": "right",
            "upAxis": "+Z",
            "forwardAxis": "+X",
            "quaternionOrder": "wxyz"
        },
        "rootEntity": world_entity,
        "rootFrame": world_frame,
        "entities": entities,
        "frames": frames,
        "components": components,
        "relations": relations,
        "representations": [],
        "models": [{
            "id": format!("model://ingest/{suffix}/robot/kinematics"),
            "subjectRef": robot_entity,
            "family": "robot_kinematics",
            "purpose": ["robot_structure_import"],
            "assumptions": ["source_kinematic_tree", "source_units_are_si"],
            "validityDomain": {
                "purpose": ["robot_structure_import"],
                "unsupported": ["resolved_visuals", "resolved_collisions", "complete_dynamics", "native_transmissions"]
            },
            "activates": {
                "components": component_ids,
                "representations": []
            }
        }],
        "evidenceGraph": {
            "sources": [{
                "id": evidence,
                "kind": "source_asset",
                "digest": resource_digest,
                "rightsStatus": rights_status,
                "notes": "Imported immutable robot description; canonical kinematics are mapped while unresolved and unknown native data remain in the source payload."
            }],
            "claims": [],
            "derivations": []
        },
        "clockDomains": [{
            "id": clock,
            "kind": "simulation",
            "unit": "second",
            "synchronizationPolicy": "authoritative"
        }],
        "stateChannels": state_channels,
        "initialState": initial_state,
        "nativePayloads": [{
            "id": format!("native://ingest/{suffix}/{format}"),
            "sourceFormat": format,
            "sourceVersion": "source",
            "digest": resource_digest,
            "namespace": "worldspec.ingestion.robot-source",
            "rightsStatus": rights_status,
            "targetScope": [format]
        }],
        "metadata": {
            "ingestion": {
                "format": format,
                "unitStatus": "source_standard",
                "physicsStatus": "unresolved",
                "robotStructureStatus": "imported_partial"
            }
        }
    }))
}

fn ingest(
    inputs: Vec<PathBuf>,
    rights_path: PathBuf,
    output: PathBuf,
    candidate_output: Option<PathBuf>,
    cas_root: PathBuf,
    schema_dir: PathBuf,
) -> Result<bool, String> {
    let cas = Cas::open(cas_root).map_err(|error| error.to_string())?;
    let rights = read_json(&rights_path)?;
    validate_document(&schema_dir, "rights.schema.json", &rights, None)?;
    let rights_ref = rights
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| "RightsSpec.id is required".to_owned())?;
    let rights_status = rights
        .get("status")
        .and_then(Value::as_str)
        .ok_or_else(|| "RightsSpec.status is required".to_owned())?;
    let rights_bytes = canonical_json(&rights).map_err(|error| error.to_string())?;
    let rights_digest = cas
        .put_bytes(&rights_bytes, Some("application/vnd.worldspec.rights+json"))
        .map_err(|error| error.to_string())?;

    let mut items = Vec::new();
    let mut diagnostics = Vec::new();
    for input in inputs {
        let format = format_for(&input)?;
        let size = fs::metadata(&input)
            .map_err(|error| format!("cannot inspect {}: {error}", input.display()))?
            .len();
        if size > DEFAULT_SOURCE_LIMIT_BYTES {
            return Err(format!(
                "{} is {size} bytes; source limit is {DEFAULT_SOURCE_LIMIT_BYTES}",
                input.display()
            ));
        }
        let bytes = fs::read(&input)
            .map_err(|error| format!("cannot read {}: {error}", input.display()))?;
        let scan = scan_source(format, &bytes, DEFAULT_SOURCE_LIMIT_BYTES);
        diagnostics.extend(scan.diagnostics.iter().map(forge_diagnostic_json));
        if !scan.safe {
            return Err(format!(
                "source security scan rejected {}: {}",
                input.display(),
                serde_json::to_string(&scan.diagnostics).map_err(|error| error.to_string())?
            ));
        }
        let digest = cas
            .put_bytes(&bytes, Some(media_type(format)))
            .map_err(|error| error.to_string())?;
        let name = input
            .file_name()
            .and_then(|value| value.to_str())
            .ok_or_else(|| format!("input has no valid file name: {}", input.display()))?;
        items.push(json!({
            "id": format!("source://local/{}", digest.trim_start_matches("sha256:")),
            "digest": digest,
            "mediaType": media_type(format),
            "format": format,
            "logicalPath": format!("source/{name}")
        }));
    }
    let bundle_identity = canonical_sha256(&json!({
        "bundleVersion": "0.1.0",
        "items": items,
        "rightsRef": rights_ref,
        "rightsDigest": rights_digest,
        "nativePayloads": []
    }))
    .map_err(|error| error.to_string())?;
    let identity_suffix = bundle_identity.trim_start_matches("sha256:");
    let mut source_bundle = json!({
        "id": format!("sourcebundle://local/{identity_suffix}"),
        "bundleVersion": "0.1.0",
        "items": items,
        "rightsRef": rights_ref,
        "rightsDigest": rights_digest,
        "nativePayloads": []
    });
    let bundle_digest = canonical_sha256(&source_bundle).map_err(|error| error.to_string())?;
    source_bundle["bundleDigest"] = Value::String(bundle_digest);
    let candidate_item = source_bundle["items"]
        .as_array()
        .filter(|items| items.len() == 1)
        .and_then(|items| items.first());
    let mut candidate_kind = None;
    let candidate = if let Some(item) = candidate_item {
        let format = item["format"].as_str().unwrap_or_default();
        let digest = item["digest"].as_str().unwrap_or_default();
        match format {
            "obj" | "glb" => {
                candidate_kind = Some("visual");
                Some(visual_world_candidate(
                    format,
                    digest,
                    rights_status,
                    item["logicalPath"].as_str().unwrap_or("Imported asset"),
                ))
            }
            "urdf" | "mjcf" => {
                let bytes = cas.get_bytes(digest).map_err(|error| error.to_string())?;
                let report = diagnose_robot_xml(format, &bytes);
                diagnostics.extend(report.diagnostics.iter().map(forge_diagnostic_json));
                if report.safe {
                    match robot_world_candidate(format, digest, rights_status, &report.kinematics) {
                        Ok(candidate) => {
                            candidate_kind = Some("robot");
                            Some(candidate)
                        }
                        Err(message) => {
                            diagnostics.push(forge_diagnostic_json(&ForgeDiagnostic {
                                code: "ROBOT_CANONICAL_MAPPING_BLOCKED".to_owned(),
                                severity: DiagnosticSeverity::Error,
                                message,
                                line: None,
                            }));
                            None
                        }
                    }
                } else {
                    None
                }
            }
            _ => None,
        }
    } else {
        None
    };
    if let Some(candidate) = candidate.as_ref() {
        validate_document(&schema_dir, "world-definition.schema.json", candidate, None)?;
    }
    let mut draft = json!({
        "id": format!("assetdraft://local/{}", source_bundle["bundleDigest"].as_str().unwrap_or(identity_suffix).trim_start_matches("sha256:")),
        "specVersion": "0.1.0",
        "sourceBundle": source_bundle,
        "status": "needs_review",
        "diagnostics": diagnostics,
        "unresolved": []
    });
    if candidate.is_none() {
        draft["unresolved"]
            .as_array_mut()
            .expect("unresolved is an array")
            .push(json!({
                "code": "INGESTION_ADAPTER_REQUIRED",
                "question": "Run or complete the format-specific ingestion adapter to create a candidate WorldDefinition.",
                "impact": "blocking"
            }));
    } else if candidate_kind == Some("visual") {
        draft["unresolved"]
            .as_array_mut()
            .expect("unresolved is an array")
            .push(json!({
                "code": "UNIT_CONFIRMATION_REQUIRED",
                "question": "Confirm source units and canonical scale before L1 validation.",
                "impact": "blocking"
            }));
    } else if candidate_kind == Some("robot") {
        draft["unresolved"]
            .as_array_mut()
            .expect("unresolved is an array")
            .push(json!({
                "code": "ROBOT_RESOURCE_RESOLUTION_REQUIRED",
                "question": "Resolve package-local visual, collision, actuator, and sensor resources before target-load certification.",
                "impact": "blocking"
            }));
    }
    if let Some(candidate) = candidate {
        draft["candidateWorldDefinition"] = candidate;
        draft["unresolved"]
            .as_array_mut()
            .expect("unresolved is an array")
            .push(json!({
                "code": "PHYSICS_GENERATION_REQUIRED",
                "question": "Select collision, mass, center-of-mass, and inertia evidence before physics compilation.",
                "impact": "blocking"
            }));
    }
    if let (Some(path), Some(candidate)) = (
        candidate_output.as_ref(),
        draft.get("candidateWorldDefinition"),
    ) {
        write_json(path, candidate)?;
    }
    write_json(&output, &draft)?;
    println!(
        "{}",
        canonical_sha256(&draft).map_err(|error| error.to_string())?
    );
    Ok(true)
}

fn submit_job(operation: &str, args: JobSubmitArgs) -> Result<bool, String> {
    let cas = Cas::open(args.cas_root).map_err(|error| error.to_string())?;
    let input_bytes = fs::read(&args.input)
        .map_err(|error| format!("cannot read {}: {error}", args.input.display()))?;
    let input_digest = cas
        .put_bytes(&input_bytes, Some("application/octet-stream"))
        .map_err(|error| error.to_string())?;
    let profile = read_json(&args.profile)?;
    let profile_bytes = canonical_json(&profile).map_err(|error| error.to_string())?;
    let profile_digest = cas
        .put_bytes(
            &profile_bytes,
            Some("application/vnd.worldspec.profile+json"),
        )
        .map_err(|error| error.to_string())?;
    let id = local_id("job", operation);
    let mut spec = json!({
        "id": id,
        "protocolVersion": "0.1.0",
        "operation": operation,
        "inputs": [{
            "id": local_id("artifact", "input"),
            "digest": input_digest,
            "mediaType": "application/octet-stream",
            "path": args.input.file_name().and_then(|value| value.to_str()).unwrap_or("input")
        }],
        "profileDigests": [profile_digest],
        "limits": {
            "timeoutSeconds": args.timeout_seconds,
            "memoryBytes": args.memory_bytes,
            "gpuCount": args.gpu_count
        },
        "submittedAt": jiff::Timestamp::now().to_string()
    });
    let job_digest = canonical_sha256(&spec).map_err(|error| error.to_string())?;
    spec["jobDigest"] = Value::String(job_digest);
    let spec_bytes = canonical_json(&spec).map_err(|error| error.to_string())?;
    let stored_digest = cas
        .put_bytes(&spec_bytes, Some("application/vnd.worldspec.job+json"))
        .map_err(|error| error.to_string())?;
    cas.create_job(
        spec["id"].as_str().unwrap_or_default(),
        operation,
        &stored_digest,
    )
    .map_err(|error| error.to_string())?;
    write_json(&args.output, &spec)?;
    println!("{}", spec["id"].as_str().unwrap_or_default());
    Ok(true)
}

fn forge_diagnostic_json(diagnostic: &ForgeDiagnostic) -> Value {
    let mut details = serde_json::Map::new();
    if let Some(line) = diagnostic.line {
        details.insert("line".to_owned(), json!(line));
    }
    let severity = match diagnostic.severity {
        DiagnosticSeverity::Info => "info",
        DiagnosticSeverity::Warning => "warning",
        DiagnosticSeverity::Error => "error",
        DiagnosticSeverity::Fatal => "fatal",
    };
    let mut value = json!({
        "code": diagnostic.code,
        "severity": severity,
        "message": diagnostic.message
    });
    if !details.is_empty() {
        value["details"] = Value::Object(details);
    }
    value
}

fn diagnose_asset(
    input: &Path,
    schema: &str,
    schema_dir: &Path,
    output: &Path,
) -> Result<bool, String> {
    let format = format_for(input).ok();
    if format == Some("obj") {
        let bytes =
            fs::read(input).map_err(|error| format!("cannot read {}: {error}", input.display()))?;
        let scan = scan_source("obj", &bytes, DEFAULT_SOURCE_LIMIT_BYTES);
        let doctor = diagnose_obj(&bytes);
        let valid = scan.safe
            && !doctor.diagnostics.iter().any(|item| {
                matches!(
                    item.severity,
                    DiagnosticSeverity::Error | DiagnosticSeverity::Fatal
                )
            });
        write_json(
            output,
            &json!({
                "kind": "obj-doctor-report",
                "sourceScan": scan,
                "doctor": doctor,
                "valid": valid
            }),
        )?;
        return Ok(valid);
    }
    if matches!(format, Some("urdf" | "mjcf")) {
        let format = format.expect("matched robot format");
        let bytes =
            fs::read(input).map_err(|error| format!("cannot read {}: {error}", input.display()))?;
        let report = diagnose_robot_xml(format, &bytes);
        let valid = report.safe;
        write_json(
            output,
            &json!({
                "kind": "robot-xml-doctor-report",
                "doctor": report
            }),
        )?;
        return Ok(valid);
    }
    if format == Some("glb") {
        let bytes =
            fs::read(input).map_err(|error| format!("cannot read {}: {error}", input.display()))?;
        let report = diagnose_glb(&bytes);
        let valid = report.valid;
        write_json(
            output,
            &json!({
                "kind": "glb-doctor-report",
                "doctor": report
            }),
        )?;
        return Ok(valid);
    }
    let document = read_json(input)?;
    let report =
        validate_file(schema_dir, schema, &document, None).map_err(|error| error.to_string())?;
    write_json(
        output,
        &serde_json::to_value(&report).map_err(|error| error.to_string())?,
    )?;
    Ok(report.valid)
}

fn repair_obj(
    input: &Path,
    output: &Path,
    derivation_path: &Path,
    cas_root: &Path,
) -> Result<bool, String> {
    if format_for(input)? != "obj" {
        return Err("v0.1 local repair currently supports OBJ only".to_owned());
    }
    let source =
        fs::read(input).map_err(|error| format!("cannot read {}: {error}", input.display()))?;
    let scan = scan_source("obj", &source, DEFAULT_SOURCE_LIMIT_BYTES);
    if !scan.safe {
        return Err(format!("source security scan rejected {}", input.display()));
    }
    let result = repair_obj_remove_degenerate(&source)?;
    let cas = Cas::open(cas_root).map_err(|error| error.to_string())?;
    let stored_source = cas
        .put_bytes(&source, Some("model/obj"))
        .map_err(|error| error.to_string())?;
    let stored_repaired = cas
        .put_bytes(&result.payload, Some("model/obj"))
        .map_err(|error| error.to_string())?;
    if stored_source != result.source_digest || stored_repaired != result.repaired_digest {
        return Err("CAS digest disagrees with Doctor derivation".to_owned());
    }
    if let Some(parent) = output.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("cannot create {}: {error}", parent.display()))?;
    }
    fs::write(output, &result.payload)
        .map_err(|error| format!("cannot write {}: {error}", output.display()))?;
    write_json(derivation_path, &result.derivation)?;
    println!("{}", result.repaired_digest);
    Ok(true)
}

fn decode_seed(path: &Path) -> Result<[u8; 32], String> {
    let value = fs::read_to_string(path)
        .map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    let value = value.trim();
    if value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("signing key must contain exactly 64 hexadecimal characters".to_owned());
    }
    let mut seed = [0_u8; 32];
    for (index, byte) in seed.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|error| format!("invalid signing key: {error}"))?;
    }
    Ok(seed)
}

fn require_path(value: Option<PathBuf>, flag: &str) -> Result<PathBuf, String> {
    value.ok_or_else(|| format!("{flag} is required for this valid certificate"))
}

fn issue_l2_candidate(
    world_path: &Path,
    target_profile_path: &Path,
    build_manifest_path: &Path,
    loss_report_path: &Path,
    conformance_report_path: &Path,
    issuer: &str,
) -> Result<Value, String> {
    let world = read_json(world_path)?;
    let target = read_json(target_profile_path)?;
    let manifest = read_json(build_manifest_path)?;
    let loss = read_json(loss_report_path)?;
    let conformance = read_json(conformance_report_path)?;
    let world_digest = canonical_sha256(&world).map_err(|error| error.to_string())?;
    let target_digest = canonical_sha256(&target).map_err(|error| error.to_string())?;
    let manifest_digest = canonical_sha256(&manifest).map_err(|error| error.to_string())?;
    let loss_digest = canonical_sha256(&loss).map_err(|error| error.to_string())?;
    let conformance_digest = canonical_sha256(&conformance).map_err(|error| error.to_string())?;
    let identity = manifest_digest.trim_start_matches("sha256:");
    let evidence_statuses = world
        .pointer("/evidenceGraph/claims")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|claim| claim.get("status").and_then(Value::as_str))
        .map(str::to_owned)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .map(Value::String)
        .collect::<Vec<_>>();
    Ok(json!({
        "id": format!("certificate://local/l2/{identity}"),
        "certificateVersion": "0.1.0",
        "level": "L2",
        "assetDigest": world_digest,
        "targetProfileDigest": target_digest,
        "buildManifestDigest": manifest_digest,
        "lossReportDigest": loss_digest,
        "conformanceReportDigest": conformance_digest,
        "evidenceStatuses": evidence_statuses,
        "issuedAt": jiff::Timestamp::now().to_string(),
        "issuer": issuer,
        "valid": true,
        "invalidatedBy": [],
        "signatureStatus": "unsigned"
    }))
}

#[allow(clippy::too_many_arguments)]
fn issue_l3_candidate(
    world_path: &Path,
    target_profile_path: &Path,
    build_manifest_path: &Path,
    loss_report_path: &Path,
    conformance_report_path: &Path,
    task_profile_path: &Path,
    task_run_report_path: &Path,
    issuer: &str,
) -> Result<Value, String> {
    let world = read_json(world_path)?;
    let target = read_json(target_profile_path)?;
    let manifest = read_json(build_manifest_path)?;
    let loss = read_json(loss_report_path)?;
    let conformance = read_json(conformance_report_path)?;
    let task = read_json(task_profile_path)?;
    let task_run = read_json(task_run_report_path)?;
    let task_run_digest = canonical_sha256(&task_run).map_err(|error| error.to_string())?;
    let identity = task_run_digest.trim_start_matches("sha256:");
    let evidence_statuses = world
        .pointer("/evidenceGraph/claims")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|claim| claim.get("status").and_then(Value::as_str))
        .map(str::to_owned)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .map(Value::String)
        .collect::<Vec<_>>();
    Ok(json!({
        "id": format!("certificate://local/l3/{identity}"),
        "certificateVersion": "0.1.0",
        "level": "L3",
        "assetDigest": canonical_sha256(&world).map_err(|error| error.to_string())?,
        "targetProfileDigest": canonical_sha256(&target).map_err(|error| error.to_string())?,
        "buildManifestDigest": canonical_sha256(&manifest).map_err(|error| error.to_string())?,
        "lossReportDigest": canonical_sha256(&loss).map_err(|error| error.to_string())?,
        "conformanceReportDigest": canonical_sha256(&conformance).map_err(|error| error.to_string())?,
        "taskProfileDigest": canonical_sha256(&task).map_err(|error| error.to_string())?,
        "taskRunReportDigest": task_run_digest,
        "evidenceStatuses": evidence_statuses,
        "issuedAt": jiff::Timestamp::now().to_string(),
        "issuer": issuer,
        "valid": true,
        "invalidatedBy": [],
        "signatureStatus": "unsigned"
    }))
}

#[allow(clippy::too_many_arguments)]
fn assess_certificate_for_issue(
    certificate: &Value,
    world_path: Option<PathBuf>,
    target_profile_path: Option<PathBuf>,
    build_manifest_path: Option<PathBuf>,
    loss_report_path: Option<PathBuf>,
    conformance_report_path: Option<PathBuf>,
    task_profile_path: Option<PathBuf>,
    control_profile_path: Option<PathBuf>,
    predicate_profile_paths: Vec<PathBuf>,
    initial_state_path: Option<PathBuf>,
    runtime_record_paths: Vec<PathBuf>,
    task_run_report_path: Option<PathBuf>,
    bundle_dir: Option<PathBuf>,
    assessment_output: Option<&Path>,
    schema_dir: &Path,
) -> Result<(), String> {
    if certificate.get("valid").and_then(Value::as_bool) != Some(true) {
        return Ok(());
    }
    let level = match certificate.get("level").and_then(Value::as_str) {
        Some(level @ ("L2" | "L3")) => level,
        _ => return Ok(()),
    };
    let world = read_json(&require_path(world_path, "--world")?)?;
    let target_profile = read_json(&require_path(target_profile_path, "--target-profile")?)?;
    let build_manifest = read_json(&require_path(build_manifest_path, "--build-manifest")?)?;
    let loss_report = read_json(&require_path(loss_report_path, "--loss-report")?)?;
    let conformance_report = read_json(&require_path(
        conformance_report_path,
        "--conformance-report",
    )?)?;
    let bundle_dir = require_path(bundle_dir, "--bundle-dir")?;
    validate_document(schema_dir, "world-definition.schema.json", &world, None)?;
    validate_document(
        schema_dir,
        "target-profile.schema.json",
        &target_profile,
        None,
    )?;
    validate_document(
        schema_dir,
        "build-manifest.schema.json",
        &build_manifest,
        None,
    )?;
    validate_document(
        schema_dir,
        "loss-report.schema.json",
        &loss_report,
        Some(&target_profile),
    )?;
    validate_document(
        schema_dir,
        "conformance-report.schema.json",
        &conformance_report,
        None,
    )?;
    let bundle_assessment = verify_bundle_artifacts(&build_manifest, bundle_dir);
    let binding_assessment = if level == "L2" {
        assess_l2_bindings(
            certificate,
            &world,
            &target_profile,
            &build_manifest,
            &loss_report,
            &conformance_report,
        )
        .map_err(|error| error.to_string())?
    } else {
        let task_profile = read_json(&require_path(task_profile_path, "--task-profile")?)?;
        let control_profile = read_json(&require_path(control_profile_path, "--control-profile")?)?;
        if predicate_profile_paths.is_empty() {
            return Err("--predicate-profile is required at least once for L3".to_owned());
        }
        if runtime_record_paths.is_empty() {
            return Err("--runtime-record is required at least once for L3".to_owned());
        }
        let predicate_profiles = predicate_profile_paths
            .iter()
            .map(|path| read_json(path))
            .collect::<Result<Vec<_>, _>>()?;
        let initial_state = read_json(&require_path(initial_state_path, "--initial-state")?)?;
        let runtime_records = runtime_record_paths
            .iter()
            .map(|path| read_json(path))
            .collect::<Result<Vec<_>, _>>()?;
        let task_run_report = read_json(&require_path(task_run_report_path, "--task-run-report")?)?;
        validate_document(schema_dir, "task-profile.schema.json", &task_profile, None)?;
        validate_document(
            schema_dir,
            "control-profile.schema.json",
            &control_profile,
            None,
        )?;
        for predicate_profile in &predicate_profiles {
            validate_document(
                schema_dir,
                "predicate-profile.schema.json",
                predicate_profile,
                None,
            )?;
        }
        for runtime_record in &runtime_records {
            validate_document(
                schema_dir,
                "runtime-record.schema.json",
                runtime_record,
                None,
            )?;
        }
        validate_document(
            schema_dir,
            "task-run-report.schema.json",
            &task_run_report,
            None,
        )?;
        assess_l3_bindings(
            certificate,
            &world,
            &target_profile,
            &build_manifest,
            &loss_report,
            &conformance_report,
            &task_profile,
            &control_profile,
            &predicate_profiles,
            &initial_state,
            &runtime_records,
            &task_run_report,
        )
        .map_err(|error| error.to_string())?
    };
    let mut diagnostics = bundle_assessment.diagnostics;
    diagnostics.extend(binding_assessment.diagnostics);
    let assessment = CertificationAssessment {
        eligible: diagnostics.is_empty(),
        diagnostics,
    };
    if let Some(path) = assessment_output {
        write_json(
            path,
            &serde_json::to_value(&assessment).map_err(|error| error.to_string())?,
        )?;
    }
    if assessment.eligible {
        Ok(())
    } else {
        Err(serde_json::to_string_pretty(&assessment).map_err(|error| error.to_string())?)
    }
}

fn terminal(status: &JobStatus) -> bool {
    matches!(
        status,
        JobStatus::Succeeded | JobStatus::Failed | JobStatus::Cancelled | JobStatus::TimedOut
    )
}

fn validate_document(
    schema_dir: &Path,
    schema: &str,
    document: &Value,
    target: Option<&Value>,
) -> Result<(), String> {
    let report =
        validate_file(schema_dir, schema, document, target).map_err(|error| error.to_string())?;
    if report.valid {
        Ok(())
    } else {
        Err(serde_json::to_string_pretty(&report).map_err(|error| error.to_string())?)
    }
}

fn artifact_ref(
    index: usize,
    target: &str,
    artifact: &worldspec_compiler::CompiledArtifact,
) -> Value {
    json!({
        "id": format!("artifact://local/{target}/{index}"),
        "digest": artifact.digest,
        "mediaType": artifact.media_type,
        "path": artifact.path,
        "sizeBytes": artifact.size_bytes,
        "role": artifact.role
    })
}

fn compile_local(
    input: PathBuf,
    target_profile_path: PathBuf,
    build_intent_path: PathBuf,
    output_dir: PathBuf,
    cas_root: PathBuf,
    schema_dir: PathBuf,
) -> Result<bool, String> {
    let world = read_json(&input)?;
    let target_profile = read_json(&target_profile_path)?;
    let build_intent = read_json(&build_intent_path)?;
    validate_document(&schema_dir, "world-definition.schema.json", &world, None)?;
    validate_document(
        &schema_dir,
        "target-profile.schema.json",
        &target_profile,
        None,
    )?;
    validate_document(&schema_dir, "build-intent.schema.json", &build_intent, None)?;

    let target = target_profile
        .get("target")
        .and_then(Value::as_str)
        .ok_or_else(|| "TargetProfile.target is required".to_owned())?;
    fs::create_dir_all(&output_dir)
        .map_err(|error| format!("cannot create {}: {error}", output_dir.display()))?;
    let cas = Cas::open(cas_root).map_err(|error| error.to_string())?;
    let mut resources = ResourceMap::new();
    let resource_digests = world
        .get("representations")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|item| item.get("resourceDigest").and_then(Value::as_str))
        .chain(
            world
                .get("nativePayloads")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(|item| item.get("digest").and_then(Value::as_str)),
        )
        .collect::<BTreeSet<_>>();
    for digest in resource_digests {
        if cas.verify(digest).map_err(|error| error.to_string())? {
            resources.insert(
                digest.to_owned(),
                cas.get_bytes(digest).map_err(|error| error.to_string())?,
            );
        }
    }
    let mut summary = match target {
        "mujoco" => compile_mujoco_with_resources(&world, &output_dir, &resources),
        "threejs" => compile_threejs_with_resources(&world, &output_dir, &resources),
        other => return Err(format!("unsupported certified target: {other}")),
    }
    .map_err(|error| error.to_string())?;

    let world_id = world
        .get("id")
        .and_then(Value::as_str)
        .unwrap_or("world://unknown");
    let existing_capabilities = summary
        .losses
        .iter()
        .filter_map(|entry| entry.get("capability").and_then(Value::as_str))
        .map(str::to_owned)
        .collect::<std::collections::HashSet<_>>();
    for capability in target_profile
        .get("capabilities")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
    {
        let support = capability
            .get("support")
            .and_then(Value::as_str)
            .unwrap_or("unsupported");
        let id = capability
            .get("id")
            .and_then(Value::as_str)
            .unwrap_or_default();
        if support == "exact" || existing_capabilities.contains(id) {
            continue;
        }
        summary.losses.push(json!({
            "id": format!("loss://{target}/target-profile/{}", id.replace("://", "_").replace('/', "_")),
            "sourceRef": world_id,
            "capability": id,
            "status": support,
            "targetBinding": target,
            "rationale": capability.get("notes").and_then(Value::as_str).unwrap_or("The TargetProfile declares non-exact support."),
            "consequence": "Consumers must evaluate this declared degradation before using the bundle."
        }));
    }
    write_compile_summary(&summary, &output_dir).map_err(|error| error.to_string())?;

    let world_digest = canonical_sha256(&world).map_err(|error| error.to_string())?;
    let evidence_digest =
        canonical_sha256(&world["evidenceGraph"]).map_err(|error| error.to_string())?;
    let target_digest = canonical_sha256(&target_profile).map_err(|error| error.to_string())?;
    let intent_digest = canonical_sha256(&build_intent).map_err(|error| error.to_string())?;
    let build_identity = canonical_sha256(&json!({
        "worldDefinitionDigest": world_digest,
        "targetProfileDigest": target_digest,
        "buildIntentDigest": intent_digest,
        "compilerVersion": env!("CARGO_PKG_VERSION")
    }))
    .map_err(|error| error.to_string())?;
    let identity_suffix = build_identity.trim_start_matches("sha256:");
    let build_id = format!("build://local/{target}/{identity_suffix}");
    let loss_count = summary.losses.len();
    let build_allowed = !summary.losses.iter().any(|entry| {
        matches!(
            entry.get("status").and_then(Value::as_str),
            Some("dropped" | "unsupported")
        )
    });
    let loss_report = json!({
        "id": format!("lossreport://local/{target}/{identity_suffix}"),
        "reportVersion": "0.1.0",
        "buildId": build_id,
        "coverage": {
            "sourceItemCount": loss_count,
            "reportedItemCount": loss_count,
            "complete": true
        },
        "entries": summary.losses,
        "summary": {
            "highestSeverity": if loss_count == 0 {"none"} else {"warning"},
            "buildAllowed": build_allowed
        }
    });
    validate_document(
        &schema_dir,
        "loss-report.schema.json",
        &loss_report,
        Some(&target_profile),
    )?;
    write_json(&output_dir.join("loss-report.json"), &loss_report)?;
    let loss_digest = canonical_sha256(&loss_report).map_err(|error| error.to_string())?;

    let lock = json!({
        "lockVersion": "0.1.0",
        "worldDefinitionDigest": world_digest,
        "evidenceGraphDigest": evidence_digest,
        "targetProfileDigest": target_digest,
        "buildIntentDigest": intent_digest,
        "compiler": {
            "name": "worldspec-compiler",
            "version": env!("CARGO_PKG_VERSION")
        }
    });
    write_json(&output_dir.join("worldspec.lock.json"), &lock)?;
    let lock_digest = canonical_sha256(&lock).map_err(|error| error.to_string())?;
    let compiler_digest = canonical_sha256(&json!({
        "name": "worldspec-compiler",
        "version": env!("CARGO_PKG_VERSION")
    }))
    .map_err(|error| error.to_string())?;
    let artifacts = summary
        .artifacts
        .iter()
        .enumerate()
        .map(|(index, artifact)| artifact_ref(index, target, artifact))
        .collect::<Vec<_>>();
    let model_selections = world
        .get("models")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .map(|model| {
            json!({
                "subjectRef": model["subjectRef"],
                "family": model["family"],
                "modelRef": model["id"]
            })
        })
        .collect::<Vec<_>>();
    let manifest = json!({
        "id": build_id,
        "manifestVersion": "0.1.0",
        "worldDefinitionDigest": world_digest,
        "evidenceGraphDigest": evidence_digest,
        "targetProfileDigest": target_digest,
        "buildIntentDigest": intent_digest,
        "compiler": {
            "name": "worldspec-compiler",
            "version": env!("CARGO_PKG_VERSION"),
            "digest": compiler_digest
        },
        "modelSelections": model_selections,
        "artifacts": artifacts,
        "lossReportDigest": loss_digest,
        "lockDigest": lock_digest
    });
    validate_document(&schema_dir, "build-manifest.schema.json", &manifest, None)?;
    write_json(&output_dir.join("build-manifest.json"), &manifest)?;
    println!(
        "{}",
        canonical_sha256(&manifest).map_err(|error| error.to_string())?
    );
    Ok(true)
}

fn run() -> Result<bool, String> {
    let cli = Cli::parse();
    match cli.command {
        Command::Ingest {
            inputs,
            rights,
            output,
            candidate_output,
            cas_root,
            schema_dir,
        } => ingest(
            inputs,
            rights,
            output,
            candidate_output,
            cas_root,
            schema_dir,
        ),
        Command::Generate(args) => submit_job("generate", args),
        Command::Train(args) => submit_job("train", args),
        Command::Inspect {
            input,
            schema,
            schema_dir,
        } => {
            let document = read_json(&input)?;
            if let Some(schema) = schema {
                let report = validate_file(schema_dir, &schema, &document, None)
                    .map_err(|error| error.to_string())?;
                print_report(&report, OutputFormat::Text)?;
                if !report.valid {
                    return Ok(false);
                }
            }
            println!(
                "{}",
                canonical_sha256(&document).map_err(|error| error.to_string())?
            );
            Ok(true)
        }
        Command::Resolve {
            digest,
            output,
            cas_root,
        } => {
            let cas = Cas::open(cas_root).map_err(|error| error.to_string())?;
            let bytes = cas.get_bytes(&digest).map_err(|error| error.to_string())?;
            fs::write(&output, bytes)
                .map_err(|error| format!("cannot write {}: {error}", output.display()))?;
            Ok(true)
        }
        Command::Doctor { command } => match command {
            DoctorCommand::Diagnose {
                input,
                schema,
                schema_dir,
                output,
            } => diagnose_asset(&input, &schema, &schema_dir, &output),
            DoctorCommand::Repair {
                input,
                output,
                derivation,
                cas_root,
            } => repair_obj(&input, &output, &derivation, &cas_root),
        },
        Command::Validate {
            input,
            schema,
            schema_dir,
            target_profile,
            output,
        } => {
            let instance = read_json(&input)?;
            let target_profile = target_profile.as_deref().map(read_json).transpose()?;
            let report = validate_file(schema_dir, &schema, &instance, target_profile.as_ref())
                .map_err(|error| error.to_string())?;
            print_report(&report, output)?;
            Ok(report.valid)
        }
        Command::Compile {
            input,
            target_profile,
            build_intent,
            output_dir,
            cas_root,
            schema_dir,
        } => compile_local(
            input,
            target_profile,
            build_intent,
            output_dir,
            cas_root,
            schema_dir,
        ),
        Command::Certify {
            input,
            output,
            issuer,
            world,
            target_profile,
            build_manifest,
            loss_report,
            conformance_report,
            task_profile,
            control_profile,
            predicate_profile,
            initial_state,
            runtime_record,
            task_run_report,
            bundle_dir,
            assessment_output,
            signing_key,
            public_key_id,
            schema_dir,
        } => {
            let mut certificate = if let Some(input) = input {
                read_json(&input)?
            } else {
                let issuer = issuer
                    .as_deref()
                    .ok_or_else(|| "--issuer is required when issuing a certificate".to_owned())?;
                if task_profile.is_some() || task_run_report.is_some() {
                    issue_l3_candidate(
                        &require_path(world.clone(), "--world")?,
                        &require_path(target_profile.clone(), "--target-profile")?,
                        &require_path(build_manifest.clone(), "--build-manifest")?,
                        &require_path(loss_report.clone(), "--loss-report")?,
                        &require_path(conformance_report.clone(), "--conformance-report")?,
                        &require_path(task_profile.clone(), "--task-profile")?,
                        &require_path(task_run_report.clone(), "--task-run-report")?,
                        issuer,
                    )?
                } else {
                    issue_l2_candidate(
                        &require_path(world.clone(), "--world")?,
                        &require_path(target_profile.clone(), "--target-profile")?,
                        &require_path(build_manifest.clone(), "--build-manifest")?,
                        &require_path(loss_report.clone(), "--loss-report")?,
                        &require_path(conformance_report.clone(), "--conformance-report")?,
                        issuer,
                    )?
                }
            };
            assess_certificate_for_issue(
                &certificate,
                world,
                target_profile,
                build_manifest,
                loss_report,
                conformance_report,
                task_profile,
                control_profile,
                predicate_profile,
                initial_state,
                runtime_record,
                task_run_report,
                bundle_dir,
                assessment_output.as_deref(),
                &schema_dir,
            )?;
            if let Some(path) = signing_key {
                let key_id = public_key_id.ok_or_else(|| {
                    "--public-key-id is required when --signing-key is used".to_owned()
                })?;
                sign_certificate_with_seed(&mut certificate, &decode_seed(&path)?, &key_id)
                    .map_err(|error| error.to_string())?;
            } else {
                certificate["signatureStatus"] = Value::String("unsigned".to_owned());
                certificate
                    .as_object_mut()
                    .expect("certificate must be an object")
                    .remove("signature");
            }
            let report = validate_file(schema_dir, "certificate.schema.json", &certificate, None)
                .map_err(|error| error.to_string())?;
            if !report.valid {
                print_report(&report, OutputFormat::Text)?;
                return Ok(false);
            }
            write_json(&output, &certificate)?;
            Ok(true)
        }
        Command::Bundle(args) => submit_job("bundle", args),
        Command::Job { command } => match command {
            JobCommand::Get { id, cas_root } => {
                let record = Cas::open(cas_root)
                    .map_err(|error| error.to_string())?
                    .get_job(&id)
                    .map_err(|error| error.to_string())?
                    .ok_or_else(|| format!("job not found: {id}"))?;
                println!(
                    "{}",
                    serde_json::to_string_pretty(&record).map_err(|error| error.to_string())?
                );
                Ok(true)
            }
            JobCommand::Cancel { id, cas_root } => {
                let changed = Cas::open(cas_root)
                    .map_err(|error| error.to_string())?
                    .request_cancel(&id)
                    .map_err(|error| error.to_string())?;
                Ok(changed)
            }
            JobCommand::Wait {
                id,
                cas_root,
                timeout_seconds,
            } => {
                let cas = Cas::open(cas_root).map_err(|error| error.to_string())?;
                let deadline = SystemTime::now() + Duration::from_secs(timeout_seconds);
                loop {
                    let record = cas
                        .get_job(&id)
                        .map_err(|error| error.to_string())?
                        .ok_or_else(|| format!("job not found: {id}"))?;
                    if terminal(&record.status) {
                        println!(
                            "{}",
                            serde_json::to_string_pretty(&record)
                                .map_err(|error| error.to_string())?
                        );
                        return Ok(record.status == JobStatus::Succeeded);
                    }
                    if SystemTime::now() >= deadline {
                        return Err(format!("timed out waiting for job: {id}"));
                    }
                    thread::sleep(Duration::from_millis(250));
                }
            }
        },
    }
}

fn main() -> ExitCode {
    match run() {
        Ok(true) => ExitCode::SUCCESS,
        Ok(false) => ExitCode::from(1),
        Err(error) => {
            eprintln!("worldspec: {error}");
            ExitCode::from(2)
        }
    }
}
