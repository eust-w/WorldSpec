use clap::{Parser, Subcommand, ValueEnum};
use serde_json::Value;
use std::{
    fs,
    path::{Path, PathBuf},
    process::ExitCode,
};
use worldspec_core::{ValidationReport, validate_file};

#[derive(Parser, Debug)]
#[command(
    name = "worldspec",
    version,
    about = "WorldSpec 0.1 deterministic validation CLI"
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand, Debug)]
enum Command {
    /// Validate a JSON document against a schema and supported semantic invariants.
    Validate {
        /// JSON instance to validate.
        input: PathBuf,

        /// Schema file name from the schema catalog.
        #[arg(long, default_value = "world-definition.schema.json")]
        schema: String,

        /// Directory containing the WorldSpec schema catalog.
        #[arg(long, default_value = "schemas/0.1")]
        schema_dir: PathBuf,

        /// Optional TargetProfile used for LossReport coverage checks.
        #[arg(long)]
        target_profile: Option<PathBuf>,

        /// Diagnostic output format.
        #[arg(long, value_enum, default_value_t = OutputFormat::Text)]
        output: OutputFormat,
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
                let path = diagnostic.path.as_deref().unwrap_or("-");
                let object_ref = diagnostic.object_ref.as_deref().unwrap_or("-");
                println!(
                    "{:?} {} path={} object={} {}",
                    diagnostic.severity, diagnostic.code, path, object_ref, diagnostic.message
                );
            }
        }
    }
    Ok(())
}

fn run() -> Result<bool, String> {
    let cli = Cli::parse();
    match cli.command {
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
