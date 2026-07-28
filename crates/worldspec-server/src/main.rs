use clap::Parser;
use std::{
    net::{IpAddr, Ipv4Addr, SocketAddr},
    path::PathBuf,
};
use worldspec_cas::Cas;
use worldspec_server::{AppState, router};

#[derive(Parser, Debug)]
#[command(name = "worldspec-server", version)]
struct Args {
    #[arg(long, default_value = ".worldspec")]
    cas_root: PathBuf,

    #[arg(long, default_value = "schemas/0.1")]
    schema_dir: PathBuf,

    #[arg(long, default_value_t = 8090)]
    port: u16,

    /// Explicitly bind a non-loopback address. This deployment mode has no
    /// authentication and is not intended for untrusted networks.
    #[arg(long)]
    bind: Option<IpAddr>,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args = Args::parse();
    let address = SocketAddr::new(
        args.bind.unwrap_or(IpAddr::V4(Ipv4Addr::LOCALHOST)),
        args.port,
    );
    let listener = tokio::net::TcpListener::bind(address).await?;
    let state = AppState {
        cas: Cas::open(args.cas_root)?,
        schema_dir: args.schema_dir,
    };
    println!("WorldSpec API listening on http://{address}");
    axum::serve(listener, router(state))
        .with_graceful_shutdown(shutdown_signal())
        .await?;
    Ok(())
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
}
