use clap::{Parser, Subcommand, ValueEnum};
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
    process::ExitCode,
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use worldspec_cas::{Cas, JobStatus};
use worldspec_cert::sign_certificate_with_seed;
use worldspec_compiler::{compile_mujoco, compile_threejs, write_compile_summary};
use worldspec_core::{ValidationReport, canonical_json, canonical_sha256, validate_file};
use worldspec_forge::{
    DiagnosticSeverity, ForgeDiagnostic, diagnose_obj, repair_obj_remove_degenerate, scan_source,
};

const DEFAULT_SOURCE_LIMIT_BYTES: u64 = 8_589_934_592;

#[derive(Parser, Debug)]
#[command(name = "worldspec", version, about = "WorldSpec 0.1 local CLI")]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// Ingest local immutable sources into the CAS and produce an AssetDraft.
    Ingest {
        #[arg(required = true)]
        inputs: Vec<PathBuf>,
        #[arg(long)]
        rights: PathBuf,
        #[arg(long)]
        output: PathBuf,
        #[arg(long, default_value = ".worldspec")]
        cas_root: PathBuf,
        #[arg(long, default_value = "schemas/0.1")]
        schema_dir: PathBuf,
    },
    /// Queue a generation job using an explicit GenerationProfile.
    Generate(JobSubmitArgs),
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
        #[arg(long, default_value = "schemas/0.1")]
        schema_dir: PathBuf,
    },
    /// Validate and optionally Ed25519-sign a certificate document.
    Certify {
        input: PathBuf,
        #[arg(long)]
        output: PathBuf,
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
        "glb" | "gltf" => Ok("glb"),
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

fn ingest(
    inputs: Vec<PathBuf>,
    rights_path: PathBuf,
    output: PathBuf,
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
    let rights_bytes = canonical_json(&rights).map_err(|error| error.to_string())?;
    cas.put_bytes(&rights_bytes, Some("application/vnd.worldspec.rights+json"))
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
    let mut source_bundle = json!({
        "id": local_id("sourcebundle", "ingest"),
        "bundleVersion": "0.1.0",
        "items": items,
        "rightsRef": rights_ref,
        "nativePayloads": []
    });
    let bundle_digest = canonical_sha256(&source_bundle).map_err(|error| error.to_string())?;
    source_bundle["bundleDigest"] = Value::String(bundle_digest);
    let draft = json!({
        "id": local_id("assetdraft", "ingest"),
        "specVersion": "0.1.0",
        "sourceBundle": source_bundle,
        "status": "needs_review",
        "diagnostics": diagnostics,
        "unresolved": [{
            "code": "INGESTION_ADAPTER_REQUIRED",
            "question": "Run the format-specific ingestion adapter to create a candidate WorldDefinition.",
            "impact": "blocking"
        }]
    });
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
    if format_for(input).ok() == Some("obj") {
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
    let mut summary = match target {
        "mujoco" => compile_mujoco(&world, &output_dir),
        "threejs" => compile_threejs(&world, &output_dir),
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
            cas_root,
            schema_dir,
        } => ingest(inputs, rights, output, cas_root, schema_dir),
        Command::Generate(args) => submit_job("generate", args),
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
            schema_dir,
        } => compile_local(input, target_profile, build_intent, output_dir, schema_dir),
        Command::Certify {
            input,
            output,
            signing_key,
            public_key_id,
            schema_dir,
        } => {
            let mut certificate = read_json(&input)?;
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
