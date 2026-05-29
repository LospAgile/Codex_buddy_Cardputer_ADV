use std::path::PathBuf;

use codex_buddy_menu::{
    config::{app_bundle_path, project_root, Config, Language, Mode},
    launch_agent, network,
};
use eframe::egui;
#[cfg(target_os = "macos")]
use objc2::MainThreadMarker;
#[cfg(target_os = "macos")]
use objc2_app_kit::{NSApplication, NSApplicationActivationPolicy};

struct PreferencesApp {
    project_root: PathBuf,
    config: Config,
    session_cwd: String,
    wifi_port: String,
    ble_port: String,
    ble_device_name: String,
    ble_pair_code: String,
    bridge_port: String,
    interval: String,
    wifi_token: String,
    launch_at_login: bool,
    can_launch_at_login: bool,
    status: String,
}

impl PreferencesApp {
    fn new() -> PreferencesApp {
        let project_root = project_root();
        let config = Config::load(&project_root);
        PreferencesApp {
            project_root,
            session_cwd: config.session_cwd.display().to_string(),
            wifi_port: config.wifi_port.to_string(),
            ble_port: config.ble_port.to_string(),
            ble_device_name: config.ble_device_name.clone(),
            ble_pair_code: config.ble_pair_code.clone(),
            bridge_port: config.bridge_port.to_string(),
            interval: config.interval.to_string(),
            wifi_token: config.wifi_token.clone(),
            launch_at_login: launch_agent::is_enabled(),
            can_launch_at_login: app_bundle_path().is_some(),
            status: String::new(),
            config,
        }
    }

    fn save(&mut self) -> Result<(), String> {
        self.config.session_cwd = PathBuf::from(self.session_cwd.trim());
        self.config.wifi_port = parse_port(&self.wifi_port, "WiFi port")?;
        self.config.ble_port = parse_port(&self.ble_port, "BLE port")?;
        self.config.ble_device_name = self.ble_device_name.trim().to_string();
        if self.config.ble_device_name.is_empty() {
            return Err("BLE device name is required".to_string());
        }
        self.config.ble_pair_code = self.ble_pair_code.trim().to_string();
        self.config.bridge_port = parse_port(&self.bridge_port, "Bridge port")?;
        self.config.interval = self
            .interval
            .trim()
            .parse::<f32>()
            .map_err(|_| "Interval must be a number".to_string())
            .and_then(|value| {
                if value >= 0.25 {
                    Ok(value)
                } else {
                    Err("Interval must be at least 0.25 seconds".to_string())
                }
            })?;
        self.config.wifi_token = self.wifi_token.trim().to_string();
        self.config
            .save()
            .map_err(|error| format!("Save config failed: {error}"))?;

        match (self.launch_at_login, app_bundle_path()) {
            (true, Some(app_path)) => {
                launch_agent::install(&app_path)
                    .map_err(|error| format!("LaunchAgent install failed: {error}"))?;
            }
            (false, _) => {
                launch_agent::uninstall()
                    .map_err(|error| format!("LaunchAgent uninstall failed: {error}"))?;
            }
            (true, None) => {
                return Err("Launch at login requires CodexBuddyMenu.app".to_string());
            }
        }
        Ok(())
    }
}

impl eframe::App for PreferencesApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading("Codex Buddy Preferences");
            ui.add_space(6.0);
            ui.label(format!("Project: {}", self.project_root.display()));
            ui.label(format!("Mac WiFi Host: {}", network::lan_ip_text()));
            ui.label(format!(
                "Device WiFi page: Host {}, Port {}",
                network::lan_ip_text(),
                self.wifi_port
            ));
            ui.separator();

            egui::ComboBox::from_label("Mode")
                .selected_text(self.config.mode.title())
                .show_ui(ui, |ui| {
                    for mode in Mode::all() {
                        ui.selectable_value(&mut self.config.mode, mode, mode.title());
                    }
                });

            egui::ComboBox::from_label("Language")
                .selected_text(self.config.language.title())
                .show_ui(ui, |ui| {
                    for language in Language::all() {
                        ui.selectable_value(&mut self.config.language, language, language.title());
                    }
                });

            ui.separator();
            ui.label("Bridge");
            ui.horizontal(|ui| {
                ui.label("Session cwd");
                ui.text_edit_singleline(&mut self.session_cwd);
            });
            ui.horizontal(|ui| {
                ui.label("WiFi");
                ui.text_edit_singleline(&mut self.wifi_port);
                ui.label("BLE");
                ui.text_edit_singleline(&mut self.ble_port);
                ui.label("Local bridge");
                ui.text_edit_singleline(&mut self.bridge_port);
            });
            ui.horizontal(|ui| {
                ui.label("BLE device");
                ui.text_edit_singleline(&mut self.ble_device_name);
                ui.label("Pair code");
                ui.text_edit_singleline(&mut self.ble_pair_code);
            });
            ui.horizontal(|ui| {
                ui.label("Heartbeat interval");
                ui.text_edit_singleline(&mut self.interval);
                ui.label("seconds");
            });
            ui.horizontal(|ui| {
                ui.label("WiFi token");
                ui.text_edit_singleline(&mut self.wifi_token);
            });

            ui.separator();
            ui.checkbox(&mut self.config.auto_start, "Start bridge when app opens");
            ui.checkbox(&mut self.config.auto_restart, "Restart bridge if it exits");
            ui.add_enabled_ui(self.can_launch_at_login, |ui| {
                ui.checkbox(&mut self.launch_at_login, "Launch app at macOS login");
            });
            if !self.can_launch_at_login {
                ui.label("Launch at login is available after building CodexBuddyMenu.app.");
            }

            ui.separator();
            ui.horizontal(|ui| {
                if ui.button("Save").clicked() {
                    match self.save() {
                        Ok(()) => {
                            self.status = "Saved. The menu app will reload shortly.".to_string();
                        }
                        Err(error) => self.status = error,
                    }
                }
                if ui.button("Close").clicked() {
                    ctx.send_viewport_cmd(egui::ViewportCommand::Close);
                }
            });
            if !self.status.is_empty() {
                ui.add_space(6.0);
                ui.label(&self.status);
            }
        });
    }
}

fn main() -> eframe::Result<()> {
    hide_dock_icon();
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([640.0, 460.0])
            .with_min_inner_size([560.0, 420.0])
            .with_title("Codex Buddy Preferences"),
        ..Default::default()
    };
    eframe::run_native(
        "Codex Buddy Preferences",
        options,
        Box::new(|_cc| Ok(Box::new(PreferencesApp::new()))),
    )
}

#[cfg(target_os = "macos")]
fn hide_dock_icon() {
    if let Some(mtm) = MainThreadMarker::new() {
        let app = NSApplication::sharedApplication(mtm);
        let _ = app.setActivationPolicy(NSApplicationActivationPolicy::Accessory);
    }
}

#[cfg(not(target_os = "macos"))]
fn hide_dock_icon() {}

fn parse_port(value: &str, label: &str) -> Result<u16, String> {
    value
        .trim()
        .parse::<u16>()
        .ok()
        .filter(|port| *port > 0)
        .ok_or_else(|| format!("{label} must be a valid TCP port"))
}
