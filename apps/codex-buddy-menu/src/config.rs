use std::{
    collections::HashMap,
    env, fs, io,
    path::{Path, PathBuf},
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Mode {
    Auto,
    Ble,
    Wifi,
}

impl Mode {
    pub fn title(self) -> &'static str {
        match self {
            Mode::Auto => "Auto",
            Mode::Ble => "BLE",
            Mode::Wifi => "WiFi",
        }
    }

    pub fn from_config(value: &str) -> Mode {
        match value {
            "ble" => Mode::Ble,
            "wifi" => Mode::Wifi,
            _ => Mode::Auto,
        }
    }

    pub fn as_config(self) -> &'static str {
        match self {
            Mode::Auto => "auto",
            Mode::Ble => "ble",
            Mode::Wifi => "wifi",
        }
    }

    pub fn all() -> [Mode; 3] {
        [Mode::Auto, Mode::Ble, Mode::Wifi]
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Language {
    En,
    Zh,
}

impl Language {
    pub fn from_config(value: &str) -> Language {
        match value {
            "zh" | "zh-CN" | "cn" => Language::Zh,
            _ => Language::En,
        }
    }

    pub fn as_config(self) -> &'static str {
        match self {
            Language::En => "en",
            Language::Zh => "zh",
        }
    }

    pub fn title(self) -> &'static str {
        match self {
            Language::En => "English",
            Language::Zh => "中文",
        }
    }

    pub fn toggled(self) -> Language {
        match self {
            Language::En => Language::Zh,
            Language::Zh => Language::En,
        }
    }

    pub fn all() -> [Language; 2] {
        [Language::En, Language::Zh]
    }
}

#[derive(Clone, Debug)]
pub struct Config {
    pub mode: Mode,
    pub language: Language,
    pub session_cwd: PathBuf,
    pub wifi_port: u16,
    pub ble_port: u16,
    pub ble_device_name: String,
    pub ble_pair_code: String,
    pub bridge_port: u16,
    pub interval: f32,
    pub wifi_token: String,
    pub auto_start: bool,
    pub auto_restart: bool,
}

#[derive(Clone, Debug)]
pub struct DaemonCommand {
    pub program: PathBuf,
    pub base_args: Vec<String>,
    pub pythonpath: Option<PathBuf>,
    pub hook_binary: Option<PathBuf>,
}

impl Config {
    pub fn load(project_root: &Path) -> Config {
        let values = read_config_file(&config_path());
        Config {
            mode: Mode::from_config(values.get("mode").map(String::as_str).unwrap_or("auto")),
            language: Language::from_config(
                values.get("language").map(String::as_str).unwrap_or("en"),
            ),
            session_cwd: values
                .get("session_cwd")
                .map(PathBuf::from)
                .unwrap_or_else(|| project_root.to_path_buf()),
            wifi_port: parse_u16(values.get("wifi_port"), 47392),
            ble_port: parse_u16(values.get("ble_port"), 47391),
            ble_device_name: values
                .get("ble_device_name")
                .filter(|value| !value.trim().is_empty())
                .cloned()
                .unwrap_or_else(|| "Codex-Buddy".to_string()),
            ble_pair_code: values.get("ble_pair_code").cloned().unwrap_or_default(),
            bridge_port: parse_u16(values.get("bridge_port"), 47393),
            interval: values
                .get("interval")
                .and_then(|value| value.parse::<f32>().ok())
                .filter(|value| *value >= 0.25)
                .unwrap_or(2.0),
            wifi_token: values.get("wifi_token").cloned().unwrap_or_default(),
            auto_start: parse_bool(values.get("auto_start"), true),
            auto_restart: parse_bool(values.get("auto_restart"), true),
        }
    }

    pub fn save(&self) -> std::io::Result<()> {
        let path = config_path();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let payload = format!(
            "mode={}\nlanguage={}\nsession_cwd={}\nwifi_port={}\nble_port={}\nble_device_name={}\nble_pair_code={}\nbridge_port={}\ninterval={}\nwifi_token={}\nauto_start={}\nauto_restart={}\n",
            self.mode.as_config(),
            self.language.as_config(),
            self.session_cwd.display(),
            self.wifi_port,
            self.ble_port,
            self.ble_device_name,
            self.ble_pair_code,
            self.bridge_port,
            self.interval,
            self.wifi_token,
            self.auto_start,
            self.auto_restart
        );
        fs::write(path, payload)
    }
}

pub fn app_bundle_path() -> Option<PathBuf> {
    let exe = env::current_exe().ok()?;
    let macos = exe.parent()?;
    let contents = macos.parent()?;
    let app = contents.parent()?;
    if app.extension().and_then(|ext| ext.to_str()) == Some("app") {
        Some(app.to_path_buf())
    } else {
        None
    }
}

pub fn resource_dir() -> Option<PathBuf> {
    app_bundle_path().map(|app| app.join("Contents/Resources"))
}

pub fn project_root() -> PathBuf {
    if let Ok(root) = env::var("CODEX_BUDDY_PROJECT_ROOT") {
        return PathBuf::from(root);
    }
    if let Some(app) = app_bundle_path() {
        if let Some(parent) = app.parent().and_then(Path::parent) {
            if parent.join("daemon/src/codex_buddy").exists() {
                return parent.to_path_buf();
            }
        }
    }
    let current = env::current_dir().unwrap_or_else(|_| home_dir());
    if current.join("daemon/src/codex_buddy").exists() {
        current
    } else {
        home_dir()
    }
}

pub fn python_path(project_root: &Path) -> PathBuf {
    let venv = project_root.join(".venv/bin/python");
    if venv.exists() {
        return venv;
    }
    for candidate in [
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
    ] {
        let path = PathBuf::from(candidate);
        if path.exists() {
            return path;
        }
    }
    PathBuf::from("python3")
}

pub fn daemon_command(project_root: &Path) -> DaemonCommand {
    if let Some(binary) = daemon_binary_path(project_root) {
        return DaemonCommand {
            program: binary.clone(),
            base_args: Vec::new(),
            pythonpath: None,
            hook_binary: Some(binary),
        };
    }
    let python = python_path(project_root);
    DaemonCommand {
        program: python,
        base_args: vec!["-m".to_string(), "codex_buddy.cli".to_string()],
        pythonpath: Some(daemon_src_path(project_root)),
        hook_binary: None,
    }
}

pub fn daemon_binary_path(project_root: &Path) -> Option<PathBuf> {
    if let Some(resources) = resource_dir() {
        let bundled = resources.join("codex-buddy-daemon");
        if bundled.exists() {
            return Some(bundled);
        }
    }
    let local = project_root.join("tools/codex-buddy-daemon");
    if local.exists() {
        Some(local)
    } else {
        None
    }
}

pub fn daemon_src_path(project_root: &Path) -> PathBuf {
    if let Some(resources) = resource_dir() {
        let bundled = resources.join("daemon/src");
        if bundled.exists() {
            return bundled;
        }
    }
    project_root.join("daemon/src")
}

pub fn ble_bridge_app_path(project_root: &Path) -> PathBuf {
    if let Some(resources) = resource_dir() {
        let bundled = resources.join("CodexBuddyBridge.app");
        if bundled.exists() {
            return stage_bundled_ble_bridge_app(&bundled).unwrap_or(bundled);
        }
    }
    project_root.join("tools/CodexBuddyBridge.app")
}

fn stage_bundled_ble_bridge_app(bundled: &Path) -> io::Result<PathBuf> {
    let staged = home_dir()
        .join("Library")
        .join("Application Support")
        .join("CodexBuddy")
        .join("CodexBuddyBridge.app");
    copy_dir_contents(bundled, &staged)?;
    Ok(staged)
}

fn copy_dir_contents(source: &Path, destination: &Path) -> io::Result<()> {
    fs::create_dir_all(destination)?;
    fs::set_permissions(destination, fs::metadata(source)?.permissions())?;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let source_path = entry.path();
        let destination_path = destination.join(entry.file_name());
        let metadata = entry.metadata()?;
        if metadata.is_dir() {
            copy_dir_contents(&source_path, &destination_path)?;
        } else {
            fs::copy(&source_path, &destination_path)?;
            fs::set_permissions(&destination_path, metadata.permissions())?;
        }
    }
    Ok(())
}

pub fn preferences_binary_path(project_root: &Path) -> PathBuf {
    if let Ok(exe) = env::current_exe() {
        if let Some(macos) = exe.parent() {
            let bundled = macos.join("codex-buddy-preferences");
            if bundled.exists() {
                return bundled;
            }
        }
    }
    project_root.join("apps/codex-buddy-menu/target/release/codex-buddy-preferences")
}

pub fn config_path() -> PathBuf {
    home_dir().join(".codex").join("codex-buddy-menu.env")
}

pub fn home_dir() -> PathBuf {
    env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn read_config_file(path: &Path) -> HashMap<String, String> {
    let Ok(content) = fs::read_to_string(path) else {
        return HashMap::new();
    };
    content
        .lines()
        .filter_map(|line| line.split_once('='))
        .map(|(key, value)| (key.trim().to_string(), value.trim().to_string()))
        .collect()
}

fn parse_u16(value: Option<&String>, fallback: u16) -> u16 {
    value
        .and_then(|value| value.parse::<u16>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(fallback)
}

fn parse_bool(value: Option<&String>, fallback: bool) -> bool {
    match value.map(|value| value.as_str()) {
        Some("1" | "true" | "yes" | "on") => true,
        Some("0" | "false" | "no" | "off") => false,
        _ => fallback,
    }
}
