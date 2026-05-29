#include "WifiTransport.h"

#include <Preferences.h>

namespace {

constexpr const char* kNamespace = "codex-wifi";
constexpr uint32_t kWifiRetryMs = 10000;
constexpr uint32_t kTcpRetryMs = 5000;

void copyFixed(char* dest, size_t destSize, const String& value) {
  if (destSize == 0) {
    return;
  }
  strlcpy(dest, value.c_str(), destSize);
}

void copyFixed(char* dest, size_t destSize, const char* value) {
  if (destSize == 0) {
    return;
  }
  strlcpy(dest, value == nullptr ? "" : value, destSize);
}

const char* wifiStatusLabel(wl_status_t status) {
  switch (status) {
    case WL_NO_SSID_AVAIL:
      return "no ap";
    case WL_CONNECT_FAILED:
      return "auth failed";
    case WL_CONNECTION_LOST:
      return "wifi lost";
    case WL_DISCONNECTED:
      return "wifi retry";
    case WL_IDLE_STATUS:
      return "wifi idle";
    case WL_SCAN_COMPLETED:
      return "scan done";
    case WL_NO_SHIELD:
      return "wifi missing";
    default:
      return "wifi connecting";
  }
}

}  // namespace

void CodexBuddyWifi::begin() {
  load();
}

void CodexBuddyWifi::load() {
  Preferences preferences;
  if (preferences.begin(kNamespace, true)) {
    copyFixed(config_.ssid, sizeof(config_.ssid),
              preferences.getString("ssid", ""));
    copyFixed(config_.password, sizeof(config_.password),
              preferences.getString("password", ""));
    copyFixed(config_.host, sizeof(config_.host),
              preferences.getString("host", ""));
    config_.port = preferences.getUShort("port", 47392);
    copyFixed(config_.token, sizeof(config_.token),
              preferences.getString("token", ""));
    preferences.end();
  }

  if (config_.port == 0) {
    config_.port = 47392;
  }
  configured_ = config_.ssid[0] != '\0' && config_.host[0] != '\0';
  status_ = configured_ ? "idle" : "not configured";
}

void CodexBuddyWifi::save() {
  Preferences preferences;
  if (!preferences.begin(kNamespace, false)) {
    return;
  }
  preferences.putString("ssid", config_.ssid);
  preferences.putString("password", config_.password);
  preferences.putString("host", config_.host);
  preferences.putUShort("port", config_.port);
  preferences.putString("token", config_.token);
  preferences.end();
  configured_ = config_.ssid[0] != '\0' && config_.host[0] != '\0';
  status_ = configured_ ? "saved" : "not configured";
}

void CodexBuddyWifi::clear() {
  client_.stop();
  if (started_) {
    WiFi.disconnect();
  }
  memset(&config_, 0, sizeof(config_));
  config_.port = 47392;
  configured_ = false;
  status_ = "not configured";

  Preferences preferences;
  if (preferences.begin(kNamespace, false)) {
    preferences.clear();
    preferences.end();
  }
}

void CodexBuddyWifi::applyConfig(const BuddyWifiConfigRequest& request) {
  if (request.clear) {
    clear();
  }
  if (request.hasSsid) {
    copyFixed(config_.ssid, sizeof(config_.ssid), request.ssid);
  }
  if (request.hasPassword) {
    copyFixed(config_.password, sizeof(config_.password), request.password);
  }
  if (request.hasHost) {
    copyFixed(config_.host, sizeof(config_.host), request.host);
  }
  if (request.hasPort) {
    config_.port = request.port == 0 ? 47392 : request.port;
  }
  if (request.hasToken) {
    copyFixed(config_.token, sizeof(config_.token), request.token);
  }

  save();
  if (request.connectNow && configured_) {
    startRadio();
    client_.stop();
    WiFi.disconnect();
    lastWifiAttemptMs_ = 0;
    lastTcpAttemptMs_ = 0;
    status_ = "connecting";
  }
}

uint8_t CodexBuddyWifi::scanNetworks() {
  startRadio();
  if (client_.connected()) {
    client_.stop();
  }
  WiFi.scanDelete();
  int found = WiFi.scanNetworks(false, true);
  if (found < 0) {
    networkCount_ = 0;
    status_ = "scan failed";
    return 0;
  }

  networkCount_ = 0;
  uint8_t limit = found > 6 ? 6 : static_cast<uint8_t>(found);
  for (uint8_t i = 0; i < limit; ++i) {
    String ssid = WiFi.SSID(i);
    if (ssid.length() == 0) {
      continue;
    }
    copyFixed(networks_[networkCount_].ssid,
              sizeof(networks_[networkCount_].ssid),
              ssid);
    networks_[networkCount_].rssi = WiFi.RSSI(i);
    networks_[networkCount_].secure =
        WiFi.encryptionType(i) != WIFI_AUTH_OPEN;
    ++networkCount_;
  }
  WiFi.scanDelete();
  status_ = networkCount_ > 0 ? "scan done" : "no networks";
  return networkCount_;
}

const WifiNetworkInfo& CodexBuddyWifi::network(uint8_t index) const {
  static WifiNetworkInfo empty;
  if (index >= networkCount_) {
    return empty;
  }
  return networks_[index];
}

bool CodexBuddyWifi::shouldUse(ConnectionMode mode) const {
  if (mode == ConnectionMode::Wifi) {
    return true;
  }
  // Auto mode keeps the boot path lazy. WiFi only stays active after an
  // explicit scan/connect or a runtime wifi_config connect request.
  return mode == ConnectionMode::Auto && configured_ && started_;
}

void CodexBuddyWifi::update(ConnectionMode mode, uint32_t now) {
  if (!shouldUse(mode)) {
    if (client_.connected()) {
      client_.stop();
    }
    status_ = "disabled";
    return;
  }

  if (!configured_) {
    status_ = "not configured";
    return;
  }

  startRadio();
  ensureWifi(now);
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  ensureTcp(now);
  if (client_.connected()) {
    readTcp();
  }
}

void CodexBuddyWifi::startRadio() {
  if (started_) {
    return;
  }
  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  started_ = true;
}

void CodexBuddyWifi::ensureWifi(uint32_t now) {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  if (client_.connected()) {
    client_.stop();
  }
  if (lastWifiAttemptMs_ == 0 || now - lastWifiAttemptMs_ >= kWifiRetryMs) {
    lastWifiAttemptMs_ = now;
    startRadio();
    WiFi.begin(config_.ssid, config_.password);
    status_ = "wifi connecting";
    return;
  }
  status_ = wifiStatusLabel(WiFi.status());
}

void CodexBuddyWifi::ensureTcp(uint32_t now) {
  if (client_.connected()) {
    status_ = "bridge online";
    return;
  }

  if (lastTcpAttemptMs_ != 0 && now - lastTcpAttemptMs_ < kTcpRetryMs) {
    status_ = "bridge retry";
    return;
  }

  lastTcpAttemptMs_ = now;
  client_.stop();
  if (!client_.connect(config_.host, config_.port)) {
    status_ = "bridge offline";
    return;
  }

  if (config_.token[0] != '\0') {
    client_.print(buildWifiHelloLine(config_.token));
  }
  status_ = "bridge online";
}

void CodexBuddyWifi::readTcp() {
  while (client_.connected() && client_.available() > 0) {
    appendIncoming(static_cast<char>(client_.read()));
  }
  if (!client_.connected()) {
    status_ = "bridge closed";
  }
}

void CodexBuddyWifi::appendIncoming(char c) {
  if (c == '\n' || c == '\r') {
    if (rxBuffer_.length() > 0) {
      queueLine(rxBuffer_);
      rxBuffer_ = "";
    }
    return;
  }
  rxBuffer_ += c;
}

void CodexBuddyWifi::queueLine(const String& line) {
  if (rxCount_ >= 4) {
    return;
  }
  rxLines_[rxTail_] = line;
  rxTail_ = (rxTail_ + 1) % 4;
  ++rxCount_;
}

bool CodexBuddyWifi::pollLine(String& line) {
  if (rxCount_ == 0) {
    return false;
  }
  line = rxLines_[rxHead_];
  rxHead_ = (rxHead_ + 1) % 4;
  --rxCount_;
  return true;
}

void CodexBuddyWifi::sendLine(const String& line) {
  if (!client_.connected()) {
    return;
  }
  client_.print(line);
}

WifiRuntimeInfo CodexBuddyWifi::info() {
  WifiRuntimeInfo runtime;
  runtime.configured = configured_;
  runtime.wifiConnected = started_ && WiFi.status() == WL_CONNECTED;
  runtime.tcpConnected = client_.connected();
  copyFixed(runtime.ssid, sizeof(runtime.ssid), config_.ssid);
  copyFixed(runtime.password, sizeof(runtime.password), config_.password);
  copyFixed(runtime.host, sizeof(runtime.host), config_.host);
  copyFixed(runtime.token, sizeof(runtime.token), config_.token);
  runtime.port = config_.port;
  runtime.rssi = runtime.wifiConnected ? WiFi.RSSI() : 0;
  if (runtime.wifiConnected) {
    copyFixed(runtime.ip, sizeof(runtime.ip), WiFi.localIP().toString());
  } else {
    runtime.ip[0] = '\0';
  }
  runtime.status = status_;
  return runtime;
}

bool CodexBuddyWifi::tcpConnected() {
  return client_.connected();
}

bool CodexBuddyWifi::wifiConnected() const {
  return WiFi.status() == WL_CONNECTED;
}
