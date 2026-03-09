#!/bin/bash
# =============================================================================
# build-tauri.sh — builds the .deb installer only
# Run from project root: ~/portfolio/localcowork-lite
# =============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
LIB_RS="$PROJECT_ROOT/frontend/src-tauri/src/lib.rs"
CONF="$PROJECT_ROOT/frontend/src-tauri/tauri.conf.json"
PYTHON="$PROJECT_ROOT/.venv/bin/python"

echo ""
echo "=================================================="
echo " LocalCowork Lite — Tauri .deb Build"
echo "=================================================="

# ── Step 1: Set bundle targets to deb only ────────────────────────────────
echo ""
echo "[1/3] Configuring tauri.conf.json — deb only..."

"$PYTHON" - << 'PYEOF'
import json

conf_path = "frontend/src-tauri/tauri.conf.json"
with open(conf_path) as f:
    conf = json.load(f)

# deb only — skip AppImage and rpm
conf['bundle']['targets'] = ['deb']

# ensure both sidecars are registered
conf['bundle']['externalBin'] = [
    'binaries/llama-server',
    'binaries/uvicorn-backend',
]

with open(conf_path, 'w') as f:
    json.dump(conf, f, indent=2)

print("      ✓ targets = ['deb'], externalBin updated")
PYEOF

# ── Step 2: Write lib.rs ──────────────────────────────────────────────────
echo ""
echo "[2/3] Writing src-tauri/src/lib.rs..."

cat > "$LIB_RS" << 'RUST'
use std::sync::Mutex;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;

pub struct AppState {
    pub model_process:   Mutex<Option<CommandChild>>,
    pub backend_process: Mutex<Option<CommandChild>>,
}

#[tauri::command]
async fn get_backend_status() -> Result<String, String> {
    match reqwest::get("http://localhost:8000/health").await {
        Ok(r) if r.status().is_success() => Ok("ok".to_string()),
        _ => Err("backend not ready".to_string()),
    }
}

#[tauri::command]
async fn get_model_status() -> Result<String, String> {
    match reqwest::get("http://localhost:8080/health").await {
        Ok(r) if r.status().is_success() => Ok("ok".to_string()),
        _ => Err("model not ready".to_string()),
    }
}

fn spawn_model_server(app: &AppHandle, state: &State<AppState>) {
    match app.shell()
        .sidecar("llama-server").unwrap()
        .args([
            "-hf", "Qwen/Qwen2.5-7B-Instruct-GGUF:Q4_K_M",
            "--port", "8080",
            "--host", "127.0.0.1",
            "--ctx-size", "8192",
            "--n-gpu-layers", "35",
            "--flash-attn", "on",
            "--temp", "0.1",
            "--top-p", "0.1",
            "--repeat-penalty", "1.1",
        ])
        .spawn()
    {
        Ok((_, child)) => {
            *state.model_process.lock().unwrap() = Some(child);
            println!("✓ llama-server started");
        }
        Err(e) => eprintln!("✗ llama-server failed: {e}"),
    }
}

fn spawn_backend(app: &AppHandle, state: &State<AppState>) {
    // Set HOME explicitly — Tauri may launch sidecars without a proper HOME
    let home = std::env::var("HOME")
        .or_else(|_| std::env::var("LOGNAME").map(|u| format!("/home/{}", u)))
        .unwrap_or_else(|_| "/tmp".to_string());

    let data_dir = format!("{}/.local/share/localcowork-lite", home);
    std::fs::create_dir_all(&data_dir).ok();

    match app.shell()
        .sidecar("uvicorn-backend").unwrap()
        .env("PYTHONUNBUFFERED", "1")
        .env("HOME", &home)
        // Tell the backend where to store its data
        .env("LOCALCOWORK_DATA_DIR", &data_dir)
        .current_dir(&data_dir)
        .spawn()
    {
        Ok((_, child)) => {
            *state.backend_process.lock().unwrap() = Some(child);
            println!("✓ backend started, data_dir={}", data_dir);
        }
        Err(e) => eprintln!("✗ backend failed: {e}"),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(AppState {
            model_process:   Mutex::new(None),
            backend_process: Mutex::new(None),
        })
        .setup(|app| {
            let handle = app.handle().clone();
            let state  = app.state::<AppState>();
            spawn_model_server(&handle, &state);
            // Give model 3s head start before backend tries to connect
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_secs(3));
                let state = handle.state::<AppState>();
                spawn_backend(&handle, &state);
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let state = window.state::<AppState>();
                if let Some(child) = state.model_process.lock().unwrap().take() {
                    let _ = child.kill();
                };
                if let Some(child) = state.backend_process.lock().unwrap().take() {
                    let _ = child.kill();
                };
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_backend_status,
            get_model_status,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
RUST

echo "      ✓ lib.rs written"

# ── Step 3: Build ─────────────────────────────────────────────────────────
echo ""
echo "[3/3] Running cargo tauri build (deb only, ~5-10 min)..."
rm -rf /tmp/localcowork-lite  # prevent 'no space left' on AppImage bundling

cd "$PROJECT_ROOT/frontend"
cargo tauri build

echo ""
echo "=================================================="
DEB=$(find "$PROJECT_ROOT/frontend/src-tauri/target/release/bundle/deb" -name "*.deb" | head -1)
echo " .deb ready:"
echo "   $DEB"
echo ""
echo " Install:"
echo "   sudo dpkg -i \"$DEB\""
echo "=================================================="
echo ""