use std::{
    fs::{self, OpenOptions},
    io::{Read, Write},
    path::PathBuf,
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, SystemTime},
};

use codex_buddy_menu::{
    config::{
        app_bundle_path, ble_bridge_app_path, config_path, daemon_command, daemon_src_path,
        preferences_binary_path, project_root, Config, DaemonCommand, Language, Mode,
    },
    launch_agent, network,
};
#[cfg(target_os = "macos")]
use tao::platform::macos::{ActivationPolicy, EventLoopExtMacOS, EventLoopWindowTargetExtMacOS};
use tao::{
    event::{Event, StartCause},
    event_loop::{ControlFlow, EventLoop, EventLoopBuilder, EventLoopProxy, EventLoopWindowTarget},
};
use tray_icon::{
    menu::{Menu, MenuEvent, MenuItem, PredefinedMenuItem, Submenu},
    Icon, TrayIcon, TrayIconBuilder,
};

const TRAY_ICON_SIZE: u32 = 32;
const TRAY_ICON_RGBA: &[u8] = include_bytes!("../assets/tray-icon-32.rgba");

struct MenuItems {
    status: MenuItem,
    detail: MenuItem,
    last_line: MenuItem,
    start: MenuItem,
    stop: MenuItem,
    restart: MenuItem,
    guide_menu: Submenu,
    guide_ble: MenuItem,
    guide_wifi: MenuItem,
    guide_check: MenuItem,
    connection_menu: Submenu,
    auto_start_menu: Submenu,
    auto_restart_menu: Submenu,
    launch_at_login_menu: Submenu,
    language_menu: Submenu,
    mode_auto: MenuItem,
    mode_ble: MenuItem,
    mode_wifi: MenuItem,
    auto_start_on: MenuItem,
    auto_start_off: MenuItem,
    auto_restart_on: MenuItem,
    auto_restart_off: MenuItem,
    launch_at_login_on: MenuItem,
    launch_at_login_off: MenuItem,
    language_en: MenuItem,
    language_zh: MenuItem,
    preferences: MenuItem,
    configure: MenuItem,
    doctor: MenuItem,
    logs: MenuItem,
    diagnostics: MenuItem,
    install: MenuItem,
    uninstall: MenuItem,
    quit: MenuItem,
}

struct AppState {
    project_root: PathBuf,
    daemon: DaemonCommand,
    daemon_src: PathBuf,
    ble_bridge_app: PathBuf,
    preferences_bin: PathBuf,
    log_path: PathBuf,
    config: Config,
    child: Option<Child>,
    tray: Option<TrayIcon>,
    menu_items: Option<MenuItems>,
    last_line: String,
    last_heartbeat: Option<SystemTime>,
    config_mtime: Option<SystemTime>,
}

#[derive(Debug)]
enum UserEvent {
    Menu(String),
    Tick,
}

impl AppState {
    fn new() -> AppState {
        let project_root = project_root();
        let daemon = daemon_command(&project_root);
        let daemon_src = daemon_src_path(&project_root);
        let ble_bridge_app = ble_bridge_app_path(&project_root);
        let preferences_bin = preferences_binary_path(&project_root);
        let log_path = PathBuf::from("/tmp/codex-buddy-menu.log");
        let config = Config::load(&project_root);
        let config_mtime = config_modified_time();
        AppState {
            project_root,
            daemon,
            daemon_src,
            ble_bridge_app,
            preferences_bin,
            log_path,
            config,
            child: None,
            tray: None,
            menu_items: None,
            last_line: "not started".to_string(),
            last_heartbeat: None,
            config_mtime,
        }
    }

    fn init_tray(&mut self, proxy: EventLoopProxy<UserEvent>) {
        MenuEvent::set_event_handler(Some(move |event: MenuEvent| {
            let _ = proxy.send_event(UserEvent::Menu(event.id.0));
        }));

        let menu = Menu::new();
        let status = MenuItem::with_id("status", "Status: stopped", false, None);
        let detail = MenuItem::with_id(
            "detail",
            "Ports: WiFi 47392, BLE 47391, Bridge 47393",
            false,
            None,
        );
        let last_line = MenuItem::with_id("last_line", "Last: not started", false, None);
        let start = MenuItem::with_id("start", "Start Bridge", true, None);
        let stop = MenuItem::with_id("stop", "Stop Bridge", false, None);
        let restart = MenuItem::with_id("restart", "Restart Bridge", true, None);
        let guide_menu = Submenu::with_id("guide_menu", "Connection Guide", true);
        let guide_ble = MenuItem::with_id("guide_ble", "Connect with BLE...", true, None);
        let guide_wifi = MenuItem::with_id("guide_wifi", "Connect with WiFi...", true, None);
        let guide_check = MenuItem::with_id("guide_check", "Check current connection", true, None);
        let connection_menu = Submenu::with_id("connection_menu", "Connection Mode: Auto", true);
        let auto_start_menu =
            Submenu::with_id("auto_start_menu", "Start bridge on launch: On", true);
        let auto_restart_menu =
            Submenu::with_id("auto_restart_menu", "Restart bridge on crash: On", true);
        let launch_at_login_menu =
            Submenu::with_id("launch_at_login_menu", "Launch app at login: Off", true);
        let language_menu = Submenu::with_id("language_menu", "Language: English", true);
        let mode_auto = MenuItem::with_id("mode_auto", "Auto", true, None);
        let mode_ble = MenuItem::with_id("mode_ble", "BLE only", true, None);
        let mode_wifi = MenuItem::with_id("mode_wifi", "WiFi only", true, None);
        let auto_start_on = MenuItem::with_id("auto_start_on", "On", true, None);
        let auto_start_off = MenuItem::with_id("auto_start_off", "Off", true, None);
        let auto_restart_on = MenuItem::with_id("auto_restart_on", "On", true, None);
        let auto_restart_off = MenuItem::with_id("auto_restart_off", "Off", true, None);
        let launch_at_login_on = MenuItem::with_id("launch_at_login_on", "On", true, None);
        let launch_at_login_off = MenuItem::with_id("launch_at_login_off", "Off", true, None);
        let language_en = MenuItem::with_id("language_en", "English", true, None);
        let language_zh = MenuItem::with_id("language_zh", "中文", true, None);
        let preferences = MenuItem::with_id("preferences", "Preferences...", true, None);
        let configure = MenuItem::with_id("configure", "Configure Ports...", true, None);
        let doctor = MenuItem::with_id("doctor", "Run Doctor", true, None);
        let logs = MenuItem::with_id("logs", "Open Logs", true, None);
        let diagnostics = MenuItem::with_id("diagnostics", "Copy Diagnostics", true, None);
        let install = MenuItem::with_id("install_hook", "Install Desktop Hook...", true, None);
        let uninstall =
            MenuItem::with_id("uninstall_hook", "Uninstall Desktop Hook...", true, None);
        let quit = MenuItem::with_id("quit", "Quit", true, None);

        let _ = connection_menu.append_items(&[&mode_auto, &mode_wifi, &mode_ble]);
        let _ = auto_start_menu.append_items(&[&auto_start_on, &auto_start_off]);
        let _ = auto_restart_menu.append_items(&[&auto_restart_on, &auto_restart_off]);
        let _ = launch_at_login_menu.append_items(&[&launch_at_login_on, &launch_at_login_off]);
        let _ = language_menu.append_items(&[&language_en, &language_zh]);
        let _ = guide_menu.append_items(&[&guide_ble, &guide_wifi, &guide_check]);

        let _ = menu.append_items(&[
            &status,
            &detail,
            &last_line,
            &PredefinedMenuItem::separator(),
            &start,
            &stop,
            &restart,
            &PredefinedMenuItem::separator(),
            &guide_menu,
            &PredefinedMenuItem::separator(),
            &connection_menu,
            &auto_start_menu,
            &auto_restart_menu,
            &launch_at_login_menu,
            &language_menu,
            &PredefinedMenuItem::separator(),
            &preferences,
            &configure,
            &PredefinedMenuItem::separator(),
            &doctor,
            &logs,
            &diagnostics,
            &PredefinedMenuItem::separator(),
            &install,
            &uninstall,
            &PredefinedMenuItem::separator(),
            &quit,
        ]);

        let items = MenuItems {
            status,
            detail,
            last_line,
            start,
            stop,
            restart,
            guide_menu,
            guide_ble,
            guide_wifi,
            guide_check,
            connection_menu,
            auto_start_menu,
            auto_restart_menu,
            launch_at_login_menu,
            language_menu,
            mode_auto,
            mode_ble,
            mode_wifi,
            auto_start_on,
            auto_start_off,
            auto_restart_on,
            auto_restart_off,
            launch_at_login_on,
            launch_at_login_off,
            language_en,
            language_zh,
            preferences,
            configure,
            doctor,
            logs,
            diagnostics,
            install,
            uninstall,
            quit,
        };

        let icon = tray_icon_image();
        match TrayIconBuilder::new()
            .with_menu(Box::new(menu))
            .with_tooltip("Codex Buddy")
            .with_icon(icon)
            .build()
        {
            Ok(tray) => {
                self.tray = Some(tray);
                self.menu_items = Some(items);
                self.refresh_menu();
                if self.config.auto_start {
                    self.start_bridge();
                    self.refresh_menu();
                }
            }
            Err(error) => {
                self.append_log(&format!("tray init failed: {error}"));
            }
        }
    }

    fn handle_menu(&mut self, id: &str) {
        match id {
            "start" => self.start_bridge(),
            "stop" => self.stop_bridge(),
            "restart" => self.restart_bridge(),
            "guide_ble" => self.run_ble_wizard(),
            "guide_wifi" => self.run_wifi_wizard(),
            "guide_check" => self.run_connection_check(),
            "mode_auto" => self.set_mode(Mode::Auto),
            "mode_ble" => self.set_mode(Mode::Ble),
            "mode_wifi" => self.set_mode(Mode::Wifi),
            "auto_start_on" => self.set_auto_start(true),
            "auto_start_off" => self.set_auto_start(false),
            "auto_restart_on" => self.set_auto_restart(true),
            "auto_restart_off" => self.set_auto_restart(false),
            "launch_at_login_on" => self.set_launch_at_login(true),
            "launch_at_login_off" => self.set_launch_at_login(false),
            "language_en" => self.set_language(Language::En),
            "language_zh" => self.set_language(Language::Zh),
            "preferences" => self.open_preferences(),
            "configure" => self.configure_ports(),
            "doctor" => self.run_doctor(),
            "logs" => self.open_logs(),
            "diagnostics" => self.copy_diagnostics(),
            "install_hook" => self.install_desktop_hook(),
            "uninstall_hook" => self.uninstall_desktop_hook(),
            "quit" => {
                self.stop_bridge();
                std::process::exit(0);
            }
            _ => {}
        }
        self.refresh_menu();
    }

    fn tr(&self, en: &'static str, zh: &'static str) -> &'static str {
        match self.config.language {
            Language::En => en,
            Language::Zh => zh,
        }
    }

    fn poll(&mut self) {
        if self.reload_config_if_changed() && self.child.is_some() {
            self.append_log("config changed; restarting bridge");
            self.restart_bridge();
        }
        if let Some(child) = self.child.as_mut() {
            if matches!(child.try_wait(), Ok(Some(_))) {
                self.child = None;
                self.last_line = "bridge exited".to_string();
                self.append_log("bridge exited");
                if self.config.auto_restart {
                    self.append_log("auto restarting bridge");
                    self.start_bridge();
                }
            }
        }
        if self.config.mode != Mode::Ble && self.child.is_some() && self.has_wifi_connection() {
            self.last_heartbeat = Some(SystemTime::now());
        }
        self.refresh_menu();
    }

    fn reload_config_if_changed(&mut self) -> bool {
        let modified = config_modified_time();
        if modified == self.config_mtime {
            return false;
        }
        self.config_mtime = modified;
        self.config = Config::load(&self.project_root);
        true
    }

    fn set_mode(&mut self, mode: Mode) {
        self.config.mode = mode;
        self.save_config();
        self.restart_bridge();
    }

    fn set_auto_start(&mut self, enabled: bool) {
        if self.config.auto_start != enabled {
            self.config.auto_start = enabled;
            self.save_config();
        }
    }

    fn set_auto_restart(&mut self, enabled: bool) {
        if self.config.auto_restart != enabled {
            self.config.auto_restart = enabled;
            self.save_config();
        }
    }

    fn set_launch_at_login(&mut self, enabled: bool) {
        if launch_agent::is_enabled() == enabled {
            return;
        }
        let result = if enabled {
            let Some(app_path) = app_bundle_path() else {
                let message = self.tr(
                    "Launch at login is only available from CodexBuddyMenu.app.",
                    "登录启动只能在 CodexBuddyMenu.app 里启用。",
                );
                osascript_alert(self.tr("Codex Buddy", "Codex Buddy"), message);
                return;
            };
            launch_agent::install(&app_path)
        } else {
            launch_agent::uninstall()
        };

        if let Err(error) = result {
            let message = format!("launch agent update failed: {error}");
            self.append_log(&message);
            osascript_alert(self.tr("Codex Buddy", "Codex Buddy"), &message);
        }
    }

    fn set_language(&mut self, language: Language) {
        if self.config.language != language {
            self.config.language = language;
            self.save_config();
        }
    }

    fn save_config(&mut self) {
        if let Err(error) = self.config.save() {
            self.append_log(&format!("config save failed: {error}"));
        }
        self.config_mtime = config_modified_time();
    }

    fn open_preferences(&mut self) {
        if !self.preferences_bin.exists() {
            let message = format!(
                "preferences binary not found: {}",
                self.preferences_bin.display()
            );
            self.append_log(&message);
            osascript_alert(self.tr("Codex Buddy", "Codex Buddy"), &message);
            return;
        }
        match Command::new(&self.preferences_bin).spawn() {
            Ok(_) => self.append_log("preferences opened"),
            Err(error) => {
                let message = format!("open preferences failed: {error}");
                self.append_log(&message);
                osascript_alert(self.tr("Codex Buddy", "Codex Buddy"), &message);
            }
        }
    }

    fn start_bridge(&mut self) {
        if self.child.is_some() {
            return;
        }
        self.ensure_log_file();
        let mut command = Command::new(&self.daemon.program);
        command
            .args(self.daemon_args(self.bridge_args()))
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        if let Some(pythonpath) = &self.daemon.pythonpath {
            command.env("PYTHONPATH", pythonpath);
        }

        self.append_log(&format!("starting {:?}", command));
        match command.spawn() {
            Ok(mut child) => {
                if let Some(stdout) = child.stdout.take() {
                    spawn_log_reader(stdout, self.log_path.clone());
                }
                if let Some(stderr) = child.stderr.take() {
                    spawn_log_reader(stderr, self.log_path.clone());
                }
                self.last_line = "bridge started".to_string();
                self.child = Some(child);
            }
            Err(error) => {
                self.last_line = format!("start failed: {error}");
                self.append_log(&self.last_line);
                osascript_alert("Codex Buddy", &self.last_line);
            }
        }
    }

    fn stop_bridge(&mut self) {
        if let Some(mut child) = self.child.take() {
            stop_child_process_group(&mut child);
            self.last_line = "bridge stopped".to_string();
            self.append_log("bridge stopped");
        }
    }

    fn restart_bridge(&mut self) {
        self.stop_bridge();
        self.start_bridge();
    }

    fn bridge_args(&self) -> Vec<String> {
        match self.config.mode {
            Mode::Ble => {
                let mut args = self.watch_args("ble-socket");
                args.extend([
                    "--ble-port".to_string(),
                    self.config.ble_port.to_string(),
                    "--ble-app".to_string(),
                    self.ble_bridge_app.display().to_string(),
                    "--ble-device-name".to_string(),
                    self.config.ble_device_name.clone(),
                ]);
                if !self.config.ble_pair_code.is_empty() {
                    args.extend([
                        "--ble-pair-code".to_string(),
                        self.config.ble_pair_code.clone(),
                    ]);
                }
                args
            }
            Mode::Auto | Mode::Wifi => self.wifi_bridge_args(),
        }
    }

    fn wifi_bridge_args(&self) -> Vec<String> {
        let mut args = vec![
            "wifi-bridge".to_string(),
            "--interval".to_string(),
            self.config.interval.to_string(),
            "--session-cwd".to_string(),
            self.config.session_cwd.display().to_string(),
            "--wifi-host".to_string(),
            "0.0.0.0".to_string(),
            "--wifi-port".to_string(),
            self.config.wifi_port.to_string(),
            "--bridge-host".to_string(),
            "127.0.0.1".to_string(),
            "--bridge-port".to_string(),
            self.config.bridge_port.to_string(),
        ];
        if !self.config.wifi_token.is_empty() {
            args.extend(["--wifi-token".to_string(), self.config.wifi_token.clone()]);
        }
        args
    }

    fn watch_args(&self, transport: &str) -> Vec<String> {
        vec![
            "watch".to_string(),
            "--interval".to_string(),
            self.config.interval.to_string(),
            "--session-cwd".to_string(),
            self.config.session_cwd.display().to_string(),
            "--transport".to_string(),
            transport.to_string(),
        ]
    }

    fn doctor_args(&self) -> Vec<String> {
        let transport = if self.config.mode != Mode::Ble && self.child.is_some() {
            "local-bridge"
        } else {
            match self.config.mode {
                Mode::Auto => "wifi-server",
                Mode::Ble => "ble-socket",
                Mode::Wifi => "wifi-server",
            }
        };
        let mut args = vec![
            "doctor".to_string(),
            "--timeout".to_string(),
            "8".to_string(),
            "--transport".to_string(),
            transport.to_string(),
            "--wifi-host".to_string(),
            "0.0.0.0".to_string(),
            "--wifi-port".to_string(),
            self.config.wifi_port.to_string(),
            "--ble-port".to_string(),
            self.config.ble_port.to_string(),
            "--bridge-port".to_string(),
            self.config.bridge_port.to_string(),
            "--ble-app".to_string(),
            self.ble_bridge_app.display().to_string(),
            "--ble-device-name".to_string(),
            self.config.ble_device_name.clone(),
        ];
        if !self.config.ble_pair_code.is_empty() {
            args.extend([
                "--ble-pair-code".to_string(),
                self.config.ble_pair_code.clone(),
            ]);
        }
        if !self.config.wifi_token.is_empty() {
            args.extend(["--wifi-token".to_string(), self.config.wifi_token.clone()]);
        }
        args
    }

    fn run_doctor(&mut self) {
        let output = self.run_python(self.doctor_args());
        self.append_log(&output);
        osascript_alert(
            self.tr("Codex Buddy Doctor", "Codex Buddy 诊断"),
            &trim_for_dialog(&output),
        );
    }

    fn run_ble_wizard(&mut self) {
        if self.config.ble_pair_code.is_empty() {
            let prompt = format!(
                "{}\n\n{}: {}\n\n{}",
                self.tr(
                    "If your device shows a BLE Pair code on the Device page, enter it here. Leave this blank for older firmware.",
                    "如果设备 Device/设备 页面显示 BLE 配对码，请在这里输入。旧固件可以留空。",
                ),
                self.tr("BLE device name", "BLE 设备名"),
                self.config.ble_device_name,
                self.tr(
                    "You can change the BLE device name later in Preferences.",
                    "后续可以在偏好设置里修改 BLE 设备名。",
                )
            );
            if let Some(value) = osascript_input(
                &prompt,
                "",
                self.tr("Codex Buddy BLE Pairing", "Codex Buddy BLE 配对"),
            ) {
                self.config.ble_pair_code = value.trim().to_string();
            }
        }
        self.config.mode = Mode::Ble;
        self.save_config();
        self.restart_bridge();
        self.refresh_menu();
        thread::sleep(Duration::from_secs(5));

        let output = self.run_python(self.ble_doctor_args());
        self.append_log(&output);
        let ok = output.contains("ok ble-socket") && output.contains("heartbeat_applied");
        let message = if ok {
            format!(
                "{}\n\n{}: {}\n{}: {}\n\n{}",
                self.tr("BLE is connected.", "BLE 已连接。"),
                self.tr("Device name", "设备名"),
                self.config.ble_device_name,
                self.tr("Pair code", "配对码"),
                if self.config.ble_pair_code.is_empty() {
                    self.tr("(not set)", "（未设置）")
                } else {
                    self.tr("(saved)", "（已保存）")
                },
                self.tr(
                    "The device should be in normal boot mode. No WiFi, Host, Port, or Token setup is needed for BLE.",
                    "设备只需要正常开机，不需要配置 WiFi、Host、Port 或 Token。",
                )
            )
        } else {
            format!(
                "{}\n\n{}: {}\n{}: {}\n\n{}",
                self.tr(
                    "BLE is not ready yet.",
                    "BLE 暂时未就绪。",
                ),
                self.tr("Device name", "设备名"),
                self.config.ble_device_name,
                self.tr("Pair code", "配对码"),
                if self.config.ble_pair_code.is_empty() {
                    self.tr("(not set)", "（未设置）")
                } else {
                    self.tr("(saved)", "（已保存）")
                },
                trim_for_dialog(&output)
            )
        };
        osascript_alert(
            self.tr("Codex Buddy BLE Guide", "Codex Buddy BLE 向导"),
            &message,
        );
    }

    fn run_wifi_wizard(&mut self) {
        self.config.mode = Mode::Wifi;
        self.save_config();
        self.restart_bridge();
        self.refresh_menu();
        let token = if self.config.wifi_token.is_empty() {
            self.tr("(empty)", "（空）").to_string()
        } else {
            self.config.wifi_token.clone()
        };
        let message = format!(
            "{}\n\nSSID: {}\nHost: {}\nPort: {}\nToken: {}\n\n{}",
            self.tr(
                "WiFi bridge has started. On the device, open the WiFi page and connect with these values:",
                "WiFi 桥接已启动。请在设备 WiFi 页面用这些值连接：",
            ),
            self.tr("(your WiFi network)", "（你的 WiFi 网络）"),
            network::lan_ip_text(),
            self.config.wifi_port,
            token,
            self.tr(
                "If the device already has WiFi saved, press Connect again on the device WiFi page.",
                "如果设备已保存 WiFi，在设备 WiFi 页面再按一次 Connect。",
            )
        );
        osascript_alert(
            self.tr("Codex Buddy WiFi Guide", "Codex Buddy WiFi 向导"),
            &message,
        );
    }

    fn run_connection_check(&mut self) {
        let output = self.run_python(self.doctor_args());
        self.append_log(&output);
        let summary = if output.contains("summary: usable") {
            self.tr("Connection is usable.", "连接可用。")
        } else {
            self.tr("Connection needs attention.", "连接需要处理。")
        };
        let message = format!("{}\n\n{}", summary, trim_for_dialog(&output));
        osascript_alert(
            self.tr("Codex Buddy Connection Check", "Codex Buddy 连接检查"),
            &message,
        );
    }

    fn ble_doctor_args(&self) -> Vec<String> {
        let mut args = vec![
            "doctor".to_string(),
            "--timeout".to_string(),
            "8".to_string(),
            "--transport".to_string(),
            "ble-socket".to_string(),
            "--ble-port".to_string(),
            self.config.ble_port.to_string(),
            "--ble-app".to_string(),
            self.ble_bridge_app.display().to_string(),
            "--ble-device-name".to_string(),
            self.config.ble_device_name.clone(),
        ];
        if !self.config.ble_pair_code.is_empty() {
            args.extend([
                "--ble-pair-code".to_string(),
                self.config.ble_pair_code.clone(),
            ]);
        }
        args
    }

    fn install_desktop_hook(&mut self) {
        if !osascript_confirm(
            self.tr(
                "Install Codex Buddy Desktop hook? This writes a managed block to ~/.codex/config.toml and creates a backup.",
                "安装 Codex Buddy Desktop hook？这会向 ~/.codex/config.toml 写入托管配置块，并创建备份。",
            ),
            self.tr("Codex Buddy", "Codex Buddy"),
        ) {
            return;
        }
        let output = self.run_python(self.desktop_hook_args(true));
        self.append_log(&output);
        osascript_alert(
            self.tr("Desktop Hook Install", "Desktop Hook 安装"),
            &trim_for_dialog(&output),
        );
    }

    fn uninstall_desktop_hook(&mut self) {
        if !osascript_confirm(
            self.tr(
                "Uninstall Codex Buddy Desktop hook? Only the managed block is removed.",
                "卸载 Codex Buddy Desktop hook？只会移除托管配置块。",
            ),
            self.tr("Codex Buddy", "Codex Buddy"),
        ) {
            return;
        }
        let output = self.run_python(self.desktop_hook_args(false));
        self.append_log(&output);
        osascript_alert(
            self.tr("Desktop Hook Uninstall", "Desktop Hook 卸载"),
            &trim_for_dialog(&output),
        );
    }

    fn desktop_hook_args(&self, install: bool) -> Vec<String> {
        let transport = if self.config.mode != Mode::Ble {
            "local-bridge"
        } else {
            "ble-socket"
        };
        let mut args = vec![
            "desktop".to_string(),
            if install { "install" } else { "uninstall" }.to_string(),
            "--cwd".to_string(),
            self.config.session_cwd.display().to_string(),
            "--transport".to_string(),
            transport.to_string(),
        ];
        if let Some(hook_binary) = &self.daemon.hook_binary {
            args.extend([
                "--hook-binary".to_string(),
                hook_binary.display().to_string(),
            ]);
        } else {
            args.extend([
                "--python".to_string(),
                self.daemon.program.display().to_string(),
            ]);
        }
        if transport == "local-bridge" {
            args.extend([
                "--bridge-port".to_string(),
                self.config.bridge_port.to_string(),
            ]);
        } else {
            args.extend([
                "--ble-port".to_string(),
                self.config.ble_port.to_string(),
                "--ble-app".to_string(),
                self.ble_bridge_app.display().to_string(),
                "--ble-device-name".to_string(),
                self.config.ble_device_name.clone(),
            ]);
            if !self.config.ble_pair_code.is_empty() {
                args.extend([
                    "--ble-pair-code".to_string(),
                    self.config.ble_pair_code.clone(),
                ]);
            }
        }
        args
    }

    fn configure_ports(&mut self) {
        let current = format!(
            "{}|{}|{}|{}|{}|{}",
            self.config.session_cwd.display(),
            self.config.wifi_port,
            self.config.ble_port,
            self.config.bridge_port,
            self.config.interval,
            self.config.wifi_token
        );
        let prompt = self.tr(
            "Edit as: session_cwd|wifi_port|ble_port|bridge_port|interval|wifi_token",
            "按此格式编辑：session_cwd|wifi_port|ble_port|bridge_port|interval|wifi_token",
        );
        if let Some(value) = osascript_input(
            prompt,
            &current,
            self.tr("Codex Buddy Settings", "Codex Buddy 设置"),
        ) {
            let parts: Vec<&str> = value.split('|').collect();
            if parts.len() >= 5 {
                self.config.session_cwd = PathBuf::from(parts[0]);
                self.config.wifi_port = parts[1].parse().unwrap_or(self.config.wifi_port);
                self.config.ble_port = parts[2].parse().unwrap_or(self.config.ble_port);
                self.config.bridge_port = parts[3].parse().unwrap_or(self.config.bridge_port);
                self.config.interval = parts[4].parse().unwrap_or(self.config.interval);
                self.config.wifi_token = parts.get(5).map(|s| s.to_string()).unwrap_or_default();
                self.save_config();
                self.restart_bridge();
            }
        }
    }

    fn open_logs(&mut self) {
        self.ensure_log_file();
        let _ = Command::new("open").arg(&self.log_path).spawn();
    }

    fn copy_diagnostics(&mut self) {
        let diagnostics = self.diagnostics_text();
        if let Ok(mut child) = Command::new("pbcopy").stdin(Stdio::piped()).spawn() {
            if let Some(stdin) = child.stdin.as_mut() {
                let _ = stdin.write_all(diagnostics.as_bytes());
            }
            let _ = child.wait();
        }
        osascript_alert(
            self.tr("Codex Buddy", "Codex Buddy"),
            self.tr(
                "Diagnostics copied to clipboard.",
                "诊断信息已复制到剪贴板。",
            ),
        );
    }

    fn diagnostics_text(&self) -> String {
        let lsof = Command::new("/usr/sbin/lsof")
            .args([
                "-nP",
                &format!("-iTCP:{}", self.config.wifi_port),
                &format!("-iTCP:{}", self.config.ble_port),
                &format!("-iTCP:{}", self.config.bridge_port),
            ])
            .output()
            .map(|output| String::from_utf8_lossy(&output.stdout).to_string())
            .unwrap_or_default();
        format!(
            "Codex Buddy Diagnostics\nProject: {}\nDaemon: {}\nDaemon src: {}\nBLE bridge app: {}\nPreferences: {}\nApp bundle: {}\nLaunch at login: {}\nMode: {}\nRunning: {}\nMac host: {}\nWiFi port: {}\nBLE port: {}\nBridge port: {}\nSession cwd: {}\nLast line: {}\nLog: {}\n\nlsof:\n{}",
            self.project_root.display(),
            self.daemon_summary(),
            self.daemon_src.display(),
            self.ble_bridge_app.display(),
            self.preferences_bin.display(),
            app_bundle_path()
                .map(|path| path.display().to_string())
                .unwrap_or_else(|| "-".to_string()),
            launch_agent::is_enabled(),
            self.config.mode.title(),
            self.child.is_some(),
            network::lan_ip_text(),
            self.config.wifi_port,
            self.config.ble_port,
            self.config.bridge_port,
            self.config.session_cwd.display(),
            self.last_line,
            self.log_path.display(),
            lsof
        )
    }

    fn run_python(&self, args: Vec<String>) -> String {
        let mut command = Command::new(&self.daemon.program);
        command
            .args(self.daemon_args(args))
            .current_dir(&self.project_root);
        if let Some(pythonpath) = &self.daemon.pythonpath {
            command.env("PYTHONPATH", pythonpath);
        }
        match command.output() {
            Ok(output) => {
                let stdout = String::from_utf8_lossy(&output.stdout);
                let stderr = String::from_utf8_lossy(&output.stderr);
                format!(
                    "exit {}\n{}{}",
                    output.status.code().unwrap_or(-1),
                    stdout,
                    stderr
                )
            }
            Err(error) => format!("failed to run daemon: {error}"),
        }
    }

    fn daemon_args(&self, args: Vec<String>) -> Vec<String> {
        let mut merged = self.daemon.base_args.clone();
        merged.extend(args);
        merged
    }

    fn daemon_summary(&self) -> String {
        if self.daemon.hook_binary.is_some() {
            format!("binary {}", self.daemon.program.display())
        } else {
            format!("python {}", self.daemon.program.display())
        }
    }

    fn has_wifi_connection(&self) -> bool {
        Command::new("/usr/sbin/lsof")
            .args([
                "-nP",
                &format!("-iTCP:{}", self.config.wifi_port),
                "-sTCP:ESTABLISHED",
            ])
            .output()
            .map(|output| String::from_utf8_lossy(&output.stdout).contains("ESTABLISHED"))
            .unwrap_or(false)
    }

    fn refresh_menu(&mut self) {
        let Some(items) = &self.menu_items else {
            return;
        };
        let running = self.child.is_some();
        let running_text = if running {
            self.tr("running", "运行中")
        } else {
            self.tr("stopped", "已停止")
        };
        let on_text = self.tr("On", "开");
        let off_text = self.tr("Off", "关");
        items.status.set_text(format!(
            "{}: {} | {}: {}",
            self.tr("Status", "状态"),
            running_text,
            self.tr("Mode", "模式"),
            self.config.mode.title()
        ));
        items.detail.set_text(format!(
            "{}: {}:{} | BLE {} | Bridge {}",
            self.tr("Mac Host", "Mac 地址"),
            network::lan_ip_text(),
            self.config.wifi_port,
            self.config.ble_port,
            self.config.bridge_port
        ));
        items.last_line.set_text(format!(
            "{}: {}",
            self.tr("Last", "最近"),
            self.last_line_text()
        ));
        items.start.set_enabled(!running);
        items.stop.set_enabled(running);
        items.start.set_text(self.tr("Start Bridge", "启动桥接"));
        items.stop.set_text(self.tr("Stop Bridge", "停止桥接"));
        items
            .restart
            .set_text(self.tr("Restart Bridge", "重启桥接"));
        items
            .guide_menu
            .set_text(self.tr("Connection Guide", "连接向导"));
        items
            .guide_ble
            .set_text(self.tr("Connect with BLE...", "使用 BLE 快速连接..."));
        items
            .guide_wifi
            .set_text(self.tr("Connect with WiFi...", "使用 WiFi 连接说明..."));
        items
            .guide_check
            .set_text(self.tr("Check current connection", "检查当前连接"));
        items.connection_menu.set_text(format!(
            "{}: {}",
            self.tr("Connection Mode", "连接模式"),
            self.config.mode.title()
        ));
        items.mode_auto.set_text(selected_label(
            self.config.mode == Mode::Auto,
            self.tr("Auto (recommended)", "Auto（推荐）"),
        ));
        items.mode_wifi.set_text(selected_label(
            self.config.mode == Mode::Wifi,
            self.tr("WiFi only", "仅 WiFi"),
        ));
        items.mode_ble.set_text(selected_label(
            self.config.mode == Mode::Ble,
            self.tr("BLE only", "仅 BLE"),
        ));
        items.auto_start_menu.set_text(format!(
            "{}: {}",
            self.tr("Start bridge when app opens", "打开 App 时启动桥接"),
            if self.config.auto_start {
                on_text
            } else {
                off_text
            }
        ));
        items
            .auto_start_on
            .set_text(selected_label(self.config.auto_start, on_text));
        items
            .auto_start_off
            .set_text(selected_label(!self.config.auto_start, off_text));
        items.auto_restart_menu.set_text(format!(
            "{}: {}",
            self.tr("Restart bridge if it exits", "桥接退出时自动重启"),
            if self.config.auto_restart {
                on_text
            } else {
                off_text
            }
        ));
        items
            .auto_restart_on
            .set_text(selected_label(self.config.auto_restart, on_text));
        items
            .auto_restart_off
            .set_text(selected_label(!self.config.auto_restart, off_text));
        let launch_at_login_enabled = launch_agent::is_enabled();
        items.launch_at_login_menu.set_text(format!(
            "{}: {}",
            self.tr("Launch app at macOS login", "Mac 登录时启动 App"),
            if launch_at_login_enabled {
                on_text
            } else {
                off_text
            }
        ));
        items
            .launch_at_login_on
            .set_text(selected_label(launch_at_login_enabled, on_text));
        items
            .launch_at_login_off
            .set_text(selected_label(!launch_at_login_enabled, off_text));
        items.language_menu.set_text(format!(
            "{}: {}",
            self.tr("Language", "语言"),
            self.config.language.title()
        ));
        items.language_en.set_text(selected_label(
            self.config.language == Language::En,
            "English",
        ));
        items
            .language_zh
            .set_text(selected_label(self.config.language == Language::Zh, "中文"));
        items
            .preferences
            .set_text(self.tr("Preferences...", "偏好设置..."));
        items
            .configure
            .set_text(self.tr("Configure Ports...", "配置端口..."));
        items.doctor.set_text(self.tr("Run Doctor", "运行诊断"));
        items.logs.set_text(self.tr("Open Logs", "打开日志"));
        items
            .diagnostics
            .set_text(self.tr("Copy Diagnostics", "复制诊断信息"));
        items
            .install
            .set_text(self.tr("Install Desktop Hook...", "安装 Desktop Hook..."));
        items
            .uninstall
            .set_text(self.tr("Uninstall Desktop Hook...", "卸载 Desktop Hook..."));
        items.quit.set_text(self.tr("Quit", "退出"));
    }

    fn last_line_text(&self) -> String {
        let value = if self.config.language == Language::Zh {
            match self.last_line.as_str() {
                "not started" => "未启动".to_string(),
                "bridge started" => "桥接已启动".to_string(),
                "bridge stopped" => "桥接已停止".to_string(),
                "bridge exited" => "桥接已退出".to_string(),
                other if other.starts_with("start failed:") => {
                    other.replacen("start failed:", "启动失败:", 1)
                }
                other => other.to_string(),
            }
        } else {
            self.last_line.clone()
        };
        compact_line(&value)
    }

    fn ensure_log_file(&self) {
        if let Some(parent) = self.log_path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        let _ = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.log_path);
    }

    fn append_log(&self, message: &str) {
        self.ensure_log_file();
        if let Ok(mut file) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.log_path)
        {
            let _ = writeln!(file, "[{:?}] {}", SystemTime::now(), message);
        }
    }
}

fn main() {
    hide_dock_icon();
    let mut event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();
    configure_event_loop(&mut event_loop);
    let proxy = event_loop.create_proxy();
    spawn_tick_thread(proxy.clone());
    let mut app = AppState::new();

    event_loop.run(move |event, event_loop_target, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            Event::NewEvents(StartCause::Init) => {
                enforce_dock_hidden(event_loop_target);
                app.init_tray(proxy.clone());
                enforce_dock_hidden(event_loop_target);
            }
            Event::UserEvent(UserEvent::Menu(id)) => app.handle_menu(&id),
            Event::UserEvent(UserEvent::Tick) => {
                app.poll();
            }
            Event::LoopDestroyed => app.stop_bridge(),
            _ => {}
        }
    });
}

#[cfg(target_os = "macos")]
fn configure_event_loop(event_loop: &mut EventLoop<UserEvent>) {
    event_loop.set_activation_policy(ActivationPolicy::Accessory);
    event_loop.set_dock_visibility(false);
    event_loop.set_activate_ignoring_other_apps(false);
}

#[cfg(not(target_os = "macos"))]
fn configure_event_loop(_event_loop: &mut EventLoop<UserEvent>) {}

#[cfg(target_os = "macos")]
fn enforce_dock_hidden(event_loop_target: &EventLoopWindowTarget<UserEvent>) {
    event_loop_target.set_activation_policy_at_runtime(ActivationPolicy::Accessory);
    event_loop_target.set_dock_visibility(false);
    hide_dock_icon();
}

#[cfg(not(target_os = "macos"))]
fn enforce_dock_hidden(_event_loop_target: &EventLoopWindowTarget<UserEvent>) {}

#[cfg(target_os = "macos")]
fn hide_dock_icon() {
    use objc2::MainThreadMarker;
    use objc2_app_kit::{NSApplication, NSApplicationActivationPolicy};

    if let Some(mtm) = MainThreadMarker::new() {
        let app = NSApplication::sharedApplication(mtm);
        let _ = app.setActivationPolicy(NSApplicationActivationPolicy::Accessory);
    }
}

#[cfg(not(target_os = "macos"))]
fn hide_dock_icon() {}

fn spawn_tick_thread(proxy: EventLoopProxy<UserEvent>) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(3));
        let _ = proxy.send_event(UserEvent::Tick);
    });
}

fn stop_child_process_group(child: &mut Child) {
    #[cfg(unix)]
    {
        let pid = child.id();
        signal_process_tree(pid, "-TERM");
        for _ in 0..20 {
            if matches!(child.try_wait(), Ok(Some(_))) {
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        signal_process_tree(pid, "-KILL");
        let _ = child.wait();
    }
    #[cfg(not(unix))]
    {
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg(unix)]
fn signal_process_tree(pid: u32, signal: &str) {
    for child_pid in child_pids(pid) {
        signal_process_tree(child_pid, signal);
    }
    let _ = Command::new("/bin/kill")
        .args([signal, &pid.to_string()])
        .status();
}

#[cfg(unix)]
fn child_pids(pid: u32) -> Vec<u32> {
    let output = Command::new("/usr/bin/pgrep")
        .args(["-P", &pid.to_string()])
        .output();
    match output {
        Ok(output) if output.status.success() => String::from_utf8_lossy(&output.stdout)
            .lines()
            .filter_map(|line| line.trim().parse::<u32>().ok())
            .collect(),
        _ => Vec::new(),
    }
}

fn spawn_log_reader<R>(mut reader: R, log_path: PathBuf)
where
    R: Read + Send + 'static,
{
    thread::spawn(move || {
        let mut buffer = [0_u8; 4096];
        loop {
            match reader.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(count) => {
                    if let Ok(mut file) =
                        OpenOptions::new().create(true).append(true).open(&log_path)
                    {
                        let _ = file.write_all(&buffer[..count]);
                    }
                }
            }
        }
    });
}

fn tray_icon_image() -> Icon {
    Icon::from_rgba(TRAY_ICON_RGBA.to_vec(), TRAY_ICON_SIZE, TRAY_ICON_SIZE)
        .expect("valid tray icon")
}

fn compact_line(value: &str) -> String {
    let collapsed = value.split_whitespace().collect::<Vec<_>>().join(" ");
    if collapsed.chars().count() > 48 {
        format!("{}...", collapsed.chars().take(45).collect::<String>())
    } else {
        collapsed
    }
}

fn selected_label(selected: bool, label: &str) -> String {
    if selected {
        format!("✓ {label}")
    } else {
        label.to_string()
    }
}

fn config_modified_time() -> Option<SystemTime> {
    fs::metadata(config_path())
        .and_then(|metadata| metadata.modified())
        .ok()
}

fn trim_for_dialog(value: &str) -> String {
    if value.chars().count() > 3000 {
        format!("{}...", value.chars().take(3000).collect::<String>())
    } else {
        value.to_string()
    }
}

fn osascript_alert(title: &str, message: &str) {
    let _ = Command::new("osascript")
        .arg("-e")
        .arg(format!(
            "display dialog {} with title {} buttons {{\"OK\"}} default button \"OK\"",
            apple_string(message),
            apple_string(title)
        ))
        .status();
}

fn osascript_confirm(message: &str, title: &str) -> bool {
    Command::new("osascript")
        .arg("-e")
        .arg(format!(
            "display dialog {} with title {} buttons {{\"Cancel\", \"OK\"}} default button \"OK\" cancel button \"Cancel\"",
            apple_string(message),
            apple_string(title)
        ))
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

fn osascript_input(prompt: &str, default_value: &str, title: &str) -> Option<String> {
    let output = Command::new("osascript")
        .arg("-e")
        .arg(format!(
            "text returned of (display dialog {} default answer {} with title {})",
            apple_string(prompt),
            apple_string(default_value),
            apple_string(title)
        ))
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn apple_string(value: &str) -> String {
    format!("\"{}\"", value.replace('\\', "\\\\").replace('"', "\\\""))
}
