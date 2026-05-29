use std::{
    fs,
    path::{Path, PathBuf},
};

use crate::config::home_dir;

pub const LABEL: &str = "local.codex-buddy.menu";

pub fn plist_path() -> PathBuf {
    home_dir()
        .join("Library/LaunchAgents")
        .join(format!("{LABEL}.plist"))
}

pub fn is_enabled() -> bool {
    plist_path().exists()
}

pub fn install(app_path: &Path) -> std::io::Result<()> {
    let plist = plist_path();
    if let Some(parent) = plist.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(plist, launch_agent_plist(app_path))
}

pub fn uninstall() -> std::io::Result<()> {
    let plist = plist_path();
    if plist.exists() {
        fs::remove_file(plist)?;
    }
    Ok(())
}

fn launch_agent_plist(app_path: &Path) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>{}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
"#,
        escape_plist(LABEL),
        escape_plist(&app_path.display().to_string())
    )
}

fn escape_plist(value: &str) -> String {
    value
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}
