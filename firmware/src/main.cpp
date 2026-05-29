#include <Arduino.h>
#include <M5Cardputer.h>
#include <esp32-hal-rgb-led.h>
#include <math.h>

#include "AppSettings.h"
#include "BleTransport.h"
#include "CodexBuddyProtocol.h"
#include "KeyMap.h"
#include "PetStats.h"
#include "SfxPlayer.h"
#include "StatusView.h"
#include "WifiTransport.h"

namespace {

constexpr const char* kFirmwareVersion = "0.3.27-ble-pair";
constexpr const char* kBleDeviceName = "Codex-Buddy";
constexpr uint8_t kMenuCount = 7;
constexpr uint8_t kSettingsCount = 9;
constexpr uint8_t kWifiFieldCount = 6;
constexpr uint8_t kKeyQueueSize = 8;
constexpr uint32_t kStatusDrawIntervalMs = 500;
constexpr uint32_t kApprovalDrawIntervalMs = 140;
constexpr uint32_t kMotionSampleIntervalMs = 120;
constexpr uint32_t kMotionActivityThrottleMs = 1000;
constexpr uint32_t kMotionJumpMs = 1200;
constexpr float kMotionActivityDelta = 0.18f;
constexpr float kMotionShakeDelta = 1.25f;
constexpr float kMotionTiltThreshold = 0.25f;
constexpr uint32_t kApprovalLedStrobeStepMs = 140;
constexpr uint32_t kBootLedConfirmMs = 5000;
constexpr uint8_t kCardputerAdvRgbLedPin = 21;
constexpr uint8_t kLedBright = 255;
constexpr uint8_t kLedDisplayBoostBrightness = 220;
constexpr int32_t kLowBatterySafeLevel = 20;
constexpr int16_t kLowBatterySafeVoltageMv = 3600;
constexpr int16_t kUsbPresentMv = 4200;
constexpr int32_t kLowBatteryExitLevel = 28;
constexpr int16_t kLowBatteryExitVoltageMv = 3800;
constexpr uint8_t kLowBatterySafeBrightness = 64;

CodexBuddyBle ble;
CodexBuddyWifi wifi;
StatusView view;
SettingsStore settingsStore;
SfxPlayer sfx;
PetStatsStore petStats;
BuddyHeartbeat heartbeat;
BuddyApprovalRequest approvalRequest;
String serialBuffer;
uint32_t lastHeartbeatMs = 0;
uint32_t lastDrawMs = 0;
bool needsDraw = true;
ViewMode viewMode = ViewMode::Status;
uint8_t menuIndex = 0;
uint8_t settingsIndex = 0;
uint8_t wifiFieldIndex = 0;
uint8_t wifiNetworkIndex = 0;
uint32_t lastUserActivityMs = 0;
uint32_t lastMotionSampleMs = 0;
uint32_t lastMotionActivityMs = 0;
uint32_t motionJumpUntilMs = 0;
uint32_t ledPulseUntilMs = 0;
uint32_t bootLedConfirmUntilMs = 0;
bool ledPinReady = false;
bool feedbackHardwareStarted = false;
bool transportsStarted = false;
bool lowBatterySafeMode = false;
bool ledDisplayBoostActive = false;
bool displaySleeping = false;
bool petStatsMode = false;
bool blePaired = false;
bool lastBleConnected = false;
bool hasLastAccel = false;
bool hasMotionOverride = false;
float lastAccelX = 0.0f;
float lastAccelY = 0.0f;
float lastAccelZ = 0.0f;
BuddyAnimation motionOverride = BuddyAnimation::Idle;
int8_t lastMotionTiltDirection = 0;
char blePairCode[7] = {};

enum class WifiEditTarget : uint8_t {
  None,
  Ssid,
  Password,
  Host,
  Port,
  Token,
};

WifiEditTarget wifiEditTarget = WifiEditTarget::None;
char wifiSsidEdit[33];
char wifiPasswordEdit[65];
char wifiHostEdit[64];
char wifiPortEdit[6] = "47392";
char wifiTokenEdit[96];
size_t wifiEditCursor = 0;

enum class HostTransport : uint8_t {
  Broadcast,
  Serial,
  Ble,
  Wifi,
};

struct KeyQueue {
  KeyAction items[kKeyQueueSize];
  uint8_t head = 0;
  uint8_t tail = 0;
  uint8_t count = 0;
};

KeyQueue keyQueue;
HostTransport approvalTransport = HostTransport::Broadcast;

struct PowerSnapshot {
  int32_t batteryLevel = -1;
  int16_t batteryMv = -1;
  int16_t vbusMv = -1;
  bool usbPresent = false;
  bool lowBattery = false;
};

void sendToHost(const String& line, HostTransport target) {
  switch (target) {
    case HostTransport::Serial:
      Serial.print(line);
      return;
    case HostTransport::Ble:
      ble.sendLine(line);
      return;
    case HostTransport::Wifi:
      wifi.sendLine(line);
      return;
    case HostTransport::Broadcast:
    default:
      Serial.print(line);
      wifi.sendLine(line);
      ble.sendLine(line);
      return;
  }
}

void sendToHost(const String& line) {
  sendToHost(line, HostTransport::Broadcast);
}

void queueKey(KeyAction action) {
  if (keyQueue.count >= kKeyQueueSize) {
    return;
  }
  keyQueue.items[keyQueue.tail] = action;
  keyQueue.tail = (keyQueue.tail + 1) % kKeyQueueSize;
  ++keyQueue.count;
}

bool popKey(KeyAction& action) {
  if (keyQueue.count == 0) {
    return false;
  }
  action = keyQueue.items[keyQueue.head];
  keyQueue.head = (keyQueue.head + 1) % kKeyQueueSize;
  --keyQueue.count;
  return true;
}

bool queueFnLayerAction(char c) {
  // Cardputer-Adv 的方向键和 Delete/Esc 在 Fn 层，M5Cardputer 库不会自动解析。
  KeyAction action;
  if (!fnLayerActionForChar(c, &action)) {
    return false;
  }
  queueKey(action);
  return true;
}

const char* imuStatusLabel(uint32_t now) {
  const AppSettings& settings = settingsStore.values();
  if (!settings.petMotionEnabled) {
    return "off";
  }
  if (approvalRequest.active ||
      (heartbeat.state != BuddyState::Idle &&
       heartbeat.state != BuddyState::Running)) {
    return "hold";
  }
  if (now < motionJumpUntilMs) {
    return "shake";
  }
  if (lastMotionTiltDirection < 0) {
    return "left";
  }
  if (lastMotionTiltDirection > 0) {
    return "right";
  }
  if (hasLastAccel) {
    return "level";
  }
  return "no imu";
}

void fillLedStatus(char* buffer, size_t bufferSize, uint32_t now) {
  if (buffer == nullptr || bufferSize == 0) {
    return;
  }
  if (!settingsStore.values().ledEnabled) {
    strlcpy(buffer, "off", bufferSize);
    return;
  }
  const bool active =
      approvalRequest.active || (ledPulseUntilMs != 0 && now < ledPulseUntilMs);
  snprintf(
      buffer,
      bufferSize,
      "p%d %s",
      kCardputerAdvRgbLedPin,
      active ? "on" : "sw");
}

PowerSnapshot readPowerSnapshot() {
  PowerSnapshot power;
  power.batteryLevel = M5Cardputer.Power.getBatteryLevel();
  power.batteryMv = M5Cardputer.Power.getBatteryVoltage();
  power.vbusMv = M5Cardputer.Power.getVBUSVoltage();
  const auto chargingState = M5Cardputer.Power.isCharging();
  power.usbPresent =
      power.vbusMv >= kUsbPresentMv ||
      chargingState == m5::Power_Class::is_charging;
  const bool levelLow =
      power.batteryLevel >= 0 &&
      power.batteryLevel <= kLowBatterySafeLevel;
  const bool voltageFallbackLow =
      power.batteryLevel < 0 &&
      power.batteryMv > 0 &&
      power.batteryMv <= kLowBatterySafeVoltageMv;
  power.lowBattery = levelLow || voltageFallbackLow;
  return power;
}

bool shouldUseLowBatterySafeMode(const PowerSnapshot& power) {
  return power.lowBattery && !power.usbPresent;
}

bool canLeaveLowBatterySafeMode(const PowerSnapshot& power) {
  if (power.usbPresent) {
    return true;
  }
  const bool levelRecovered =
      power.batteryLevel >= kLowBatteryExitLevel;
  const bool voltageRecovered =
      power.batteryMv >= kLowBatteryExitVoltageMv;
  return levelRecovered && voltageRecovered;
}

void initBlePairCode() {
  const uint64_t mac = ESP.getEfuseMac();
  const uint32_t code = static_cast<uint32_t>((mac ^ (mac >> 24)) % 1000000);
  snprintf(blePairCode, sizeof(blePairCode), "%06lu", static_cast<unsigned long>(code));
}

DeviceInfo buildDeviceInfo(uint32_t now) {
  WifiRuntimeInfo wifiInfo = wifi.info();
  const PowerSnapshot power = readPowerSnapshot();
  DeviceInfo info;
  info.uptimeMs = now;
  info.freeHeap = ESP.getFreeHeap();
  info.heartbeatAgeMs = now - lastHeartbeatMs;
  info.batteryLevel = power.batteryLevel;
  info.batteryMv = power.batteryMv;
  info.vbusMv = power.vbusMv;
  const auto chargingState = M5Cardputer.Power.isCharging();
  info.chargingKnown = chargingState != m5::Power_Class::charge_unknown;
  info.charging = chargingState == m5::Power_Class::is_charging;
  info.bleConnected = ble.connected();
  info.wifiConnected = wifiInfo.wifiConnected;
  info.wifiTcpConnected = wifiInfo.tcpConnected;
  strlcpy(info.wifiSsid, wifiInfo.ssid, sizeof(info.wifiSsid));
  strlcpy(info.wifiIp, wifiInfo.ip, sizeof(info.wifiIp));
  strlcpy(info.wifiHost, wifiInfo.host, sizeof(info.wifiHost));
  info.wifiPort = wifiInfo.port;
  info.wifiTokenConfigured = wifiInfo.token[0] != '\0';
  info.wifiRssi = wifiInfo.rssi;
  info.wifiStatus = wifiInfo.status;
  info.bleName = kBleDeviceName;
  info.blePairCode = blePairCode;
  if (wifiInfo.tcpConnected) {
    info.transport = "WiFi";
  } else if (ble.connected()) {
    info.transport = "BLE";
  } else {
    info.transport = connectionModeLabel(settingsStore.values().connectionMode);
  }
  info.firmwareVersion = kFirmwareVersion;
  info.imuStatus = imuStatusLabel(now);
  fillLedStatus(info.ledStatus, sizeof(info.ledStatus), now);
  return info;
}

WifiViewInfo buildWifiViewInfo() {
  WifiRuntimeInfo runtime = wifi.info();
  WifiViewInfo info;
  info.editing = wifiEditTarget != WifiEditTarget::None;
  info.focus = wifiFieldIndex;
  info.editCursor = static_cast<uint8_t>(wifiEditCursor);
  info.selectedNetwork = wifiNetworkIndex;
  info.networkCount = wifi.networkCount();
  if (info.networkCount > 0 && info.selectedNetwork >= info.networkCount) {
    info.selectedNetwork = info.networkCount - 1;
  }
  for (uint8_t i = 0; i < info.networkCount && i < 6; ++i) {
    const WifiNetworkInfo& network = wifi.network(i);
    strlcpy(info.networks[i].ssid, network.ssid, sizeof(info.networks[i].ssid));
    info.networks[i].rssi = network.rssi;
    info.networks[i].secure = network.secure;
  }
  strlcpy(info.ssid, wifiSsidEdit, sizeof(info.ssid));
  strlcpy(info.password, wifiPasswordEdit, sizeof(info.password));
  strlcpy(info.host, wifiHostEdit, sizeof(info.host));
  strlcpy(info.port, wifiPortEdit, sizeof(info.port));
  strlcpy(info.token, wifiTokenEdit, sizeof(info.token));
  info.configured = runtime.configured;
  info.wifiConnected = runtime.wifiConnected;
  info.tcpConnected = runtime.tcpConnected;
  strlcpy(info.ip, runtime.ip, sizeof(info.ip));
  info.rssi = runtime.rssi;
  info.status = runtime.status;
  return info;
}

void applyDisplayBrightnessForState() {
  M5Cardputer.Display.setBrightness(
      displaySleeping ? 0 : settingsStore.values().brightness);
}

void enableLedDisplayBoost() {
  const uint8_t brightness =
      max(settingsStore.values().brightness, kLedDisplayBoostBrightness);
  ledDisplayBoostActive = true;
  M5Cardputer.Display.setBrightness(brightness);
}

void disableLedDisplayBoost() {
  if (!ledDisplayBoostActive) {
    return;
  }
  ledDisplayBoostActive = false;
  applyDisplayBrightnessForState();
}

void restoreDisplayBrightness() {
  ledDisplayBoostActive = false;
  applyDisplayBrightnessForState();
}

void setLedColor(uint8_t red, uint8_t green, uint8_t blue) {
  if (!ledPinReady) {
    return;
  }
  if (red != 0 || green != 0 || blue != 0) {
    enableLedDisplayBoost();
  }
  neopixelWrite(kCardputerAdvRgbLedPin, red, green, blue);
}

void clearLed() {
  setLedColor(0, 0, 0);
}

void beginFeedbackHardware() {
  if (feedbackHardwareStarted) {
    return;
  }
  sfx.begin(settingsStore.values().soundEnabled);
  ledPinReady = true;
  clearLed();
  feedbackHardwareStarted = true;
}

void pulseLed(uint8_t red, uint8_t green, uint8_t blue, uint32_t durationMs) {
  if (!settingsStore.values().ledEnabled) {
    clearLed();
    disableLedDisplayBoost();
    return;
  }
  ledPulseUntilMs = millis() + durationMs;
  setLedColor(red, green, blue);
}

void updateLed(uint32_t now) {
  if (bootLedConfirmUntilMs != 0 && now < bootLedConfirmUntilMs) {
    setLedColor(0, kLedBright, 0);
    return;
  }
  bootLedConfirmUntilMs = 0;

  if (!settingsStore.values().ledEnabled) {
    clearLed();
    disableLedDisplayBoost();
    ledPulseUntilMs = 0;
    return;
  }

  if (approvalRequest.active) {
    const uint8_t phase = (now / kApprovalLedStrobeStepMs) % 4;
    if (phase == 0) {
      setLedColor(kLedBright, 0, 0);
    } else if (phase == 2) {
      setLedColor(kLedBright, kLedBright, kLedBright);
    } else {
      clearLed();
    }
    return;
  }

  if (ledPulseUntilMs != 0 && now < ledPulseUntilMs) {
    enableLedDisplayBoost();
    return;
  }

  ledPulseUntilMs = 0;
  clearLed();
  disableLedDisplayBoost();
}

bool bootLedConfirmActive(uint32_t now) {
  return bootLedConfirmUntilMs != 0 && now < bootLedConfirmUntilMs;
}

void playSfx(SfxEvent event) {
  sfx.play(event);
}

void feedbackApprovalRequest() {
  playSfx(SfxEvent::ApprovalAlert);
  pulseLed(kLedBright, 0, 0, 5000);
}

void feedbackApprove() {
  playSfx(SfxEvent::ApproveChord);
  pulseLed(0, kLedBright, 0, 900);
}

void feedbackDeny() {
  playSfx(SfxEvent::Deny);
  pulseLed(kLedBright, 0, 0, 1200);
}

void feedbackReview() {
  playSfx(SfxEvent::ConfirmArpeggio);
  pulseLed(0, 0, kLedBright, 1200);
}

void feedbackFailed() {
  playSfx(SfxEvent::Warn2);
  pulseLed(kLedBright, 0, 0, 1800);
}

bool hasElapsed(uint32_t now, uint32_t since, uint32_t intervalMs) {
  return static_cast<int32_t>(now - since) >=
         static_cast<int32_t>(intervalMs);
}

void wakeDisplay(uint32_t now) {
  lastUserActivityMs = now;
  if (!displaySleeping) {
    return;
  }
  petStats.endNap(now);
  displaySleeping = false;
  restoreDisplayBrightness();
  viewMode = ViewMode::Status;
  needsDraw = true;
}

void recordMotionActivity(uint32_t now) {
  if (!displaySleeping &&
      now - lastMotionActivityMs < kMotionActivityThrottleMs) {
    return;
  }
  lastMotionActivityMs = now;
  if (displaySleeping) {
    wakeDisplay(now);
  } else {
    lastUserActivityMs = now;
  }
}

void enterDisplaySleep(uint32_t now) {
  if (approvalRequest.active || displaySleeping) {
    return;
  }
  petStats.beginNap(now);
  displaySleeping = true;
  M5Cardputer.Display.fillScreen(TFT_BLACK);
  M5Cardputer.Display.setBrightness(0);
  lastDrawMs = now;
  needsDraw = false;
}

void maybeAutoSleep(uint32_t now) {
  const uint16_t sleepSeconds = settingsStore.values().autoSleepSeconds;
  if (sleepSeconds == 0 || displaySleeping || approvalRequest.active) {
    return;
  }
  if (hasElapsed(now, lastUserActivityMs,
                 static_cast<uint32_t>(sleepSeconds) * 1000UL)) {
    enterDisplaySleep(now);
  }
}

void updatePetMotion(uint32_t now) {
  const AppSettings& settings = settingsStore.values();
  hasMotionOverride = false;

  if (!settings.petMotionEnabled || approvalRequest.active ||
      (heartbeat.state != BuddyState::Idle &&
       heartbeat.state != BuddyState::Running)) {
    hasLastAccel = false;
    lastMotionTiltDirection = 0;
    return;
  }

  if (now < motionJumpUntilMs) {
    motionOverride = BuddyAnimation::Jumping;
    hasMotionOverride = true;
  }

  if (now - lastMotionSampleMs < kMotionSampleIntervalMs) {
    return;
  }
  lastMotionSampleMs = now;

  float accelX = 0.0f;
  float accelY = 0.0f;
  float accelZ = 0.0f;
  if (!M5.Imu.getAccel(&accelX, &accelY, &accelZ)) {
    hasLastAccel = false;
    return;
  }

  if (hasLastAccel) {
    const float delta = fabsf(accelX - lastAccelX) +
                        fabsf(accelY - lastAccelY) +
                        fabsf(accelZ - lastAccelZ);
    if (delta > kMotionActivityDelta) {
      recordMotionActivity(now);
    }
    if (delta > kMotionShakeDelta) {
      motionJumpUntilMs = now + kMotionJumpMs;
      motionOverride = BuddyAnimation::Jumping;
      hasMotionOverride = true;
    }
  }

  lastAccelX = accelX;
  lastAccelY = accelY;
  lastAccelZ = accelZ;
  hasLastAccel = true;

  if (hasMotionOverride) {
    needsDraw = true;
    return;
  }

  int8_t tiltDirection = 0;
  if (accelX > kMotionTiltThreshold) {
    tiltDirection = -1;
    motionOverride = BuddyAnimation::RunningLeft;
    hasMotionOverride = true;
    needsDraw = true;
  } else if (accelX < -kMotionTiltThreshold) {
    tiltDirection = 1;
    motionOverride = BuddyAnimation::RunningRight;
    hasMotionOverride = true;
    needsDraw = true;
  }
  if (tiltDirection != lastMotionTiltDirection) {
    recordMotionActivity(now);
    lastMotionTiltDirection = tiltDirection;
  }
}

void drawNow(uint32_t now) {
  BuddyHeartbeat renderHeartbeat = heartbeat;
  if (hasMotionOverride) {
    renderHeartbeat.animation = motionOverride;
  }
  view.draw(
      renderHeartbeat,
      approvalRequest,
      viewMode,
      settingsStore.values(),
      buildDeviceInfo(now),
      buildWifiViewInfo(),
      petStats.snapshot(now),
      petStatsMode,
      menuIndex,
      settingsIndex);
  lastDrawMs = now;
  needsDraw = false;
}

void syncWifiEditFromConfig() {
  WifiRuntimeInfo info = wifi.info();
  strlcpy(wifiSsidEdit, info.ssid, sizeof(wifiSsidEdit));
  strlcpy(wifiPasswordEdit, info.password, sizeof(wifiPasswordEdit));
  strlcpy(wifiHostEdit, info.host, sizeof(wifiHostEdit));
  snprintf(wifiPortEdit, sizeof(wifiPortEdit), "%u", info.port);
  strlcpy(wifiTokenEdit, info.token, sizeof(wifiTokenEdit));
}

void drawLowBatterySafeMode(uint32_t now, const PowerSnapshot& power) {
  M5Cardputer.Display.setBrightness(kLowBatterySafeBrightness);
  view.drawLowBatterySafeBoot(
      settingsStore.values(),
      power.batteryLevel,
      power.batteryMv,
      power.vbusMv);
  lastDrawMs = now;
  needsDraw = false;
}

void enterLowBatterySafeMode(uint32_t now, const PowerSnapshot& power) {
  if (!lowBatterySafeMode) {
    Serial.printf(
        "codex-buddy: low battery safe mode, bat=%ld%% mv=%d vbus=%d\n",
        static_cast<long>(power.batteryLevel),
        static_cast<int>(power.batteryMv),
        static_cast<int>(power.vbusMv));
  }
  lowBatterySafeMode = true;
  displaySleeping = false;
  ledDisplayBoostActive = false;
  bootLedConfirmUntilMs = 0;
  ledPulseUntilMs = 0;
  if (ledPinReady) {
    neopixelWrite(kCardputerAdvRgbLedPin, 0, 0, 0);
  }
  sfx.setEnabled(false);
  drawLowBatterySafeMode(now, power);
}

void startNormalRuntime(uint32_t now) {
  beginFeedbackHardware();
  view.drawBoot("Starting BLE/WiFi...");
  if (!transportsStarted) {
    ble.begin(kBleDeviceName);
    wifi.begin();
    syncWifiEditFromConfig();
    transportsStarted = true;
  }
  lowBatterySafeMode = false;
  displaySleeping = false;
  restoreDisplayBrightness();
  bootLedConfirmUntilMs = now + kBootLedConfirmMs;
  sendToHost(buildDeviceStatusLine("boot", heartbeat.state, heartbeat.animation));
  drawNow(millis());
}

bool updateLowBatterySafeMode(uint32_t now, const PowerSnapshot& power) {
  if (!lowBatterySafeMode) {
    if (shouldUseLowBatterySafeMode(power)) {
      enterLowBatterySafeMode(now, power);
      return true;
    }
    return false;
  }

  if (canLeaveLowBatterySafeMode(power)) {
    Serial.println("codex-buddy: leaving low battery safe mode");
    startNormalRuntime(now);
    return false;
  }
  return true;
}

char* wifiEditBuffer(WifiEditTarget target) {
  switch (target) {
    case WifiEditTarget::Ssid:
      return wifiSsidEdit;
    case WifiEditTarget::Password:
      return wifiPasswordEdit;
    case WifiEditTarget::Host:
      return wifiHostEdit;
    case WifiEditTarget::Port:
      return wifiPortEdit;
    case WifiEditTarget::Token:
      return wifiTokenEdit;
    case WifiEditTarget::None:
    default:
      return nullptr;
  }
}

size_t wifiEditBufferSize(WifiEditTarget target) {
  switch (target) {
    case WifiEditTarget::Ssid:
      return sizeof(wifiSsidEdit);
    case WifiEditTarget::Password:
      return sizeof(wifiPasswordEdit);
    case WifiEditTarget::Host:
      return sizeof(wifiHostEdit);
    case WifiEditTarget::Port:
      return sizeof(wifiPortEdit);
    case WifiEditTarget::Token:
      return sizeof(wifiTokenEdit);
    case WifiEditTarget::None:
    default:
      return 0;
  }
}

void clampWifiEditCursor() {
  char* buffer = wifiEditBuffer(wifiEditTarget);
  if (buffer == nullptr) {
    return;
  }
  size_t length = strlen(buffer);
  if (wifiEditCursor > length) {
    wifiEditCursor = length;
  }
}

void insertWifiEditChar(char c) {
  char* buffer = wifiEditBuffer(wifiEditTarget);
  size_t bufferSize = wifiEditBufferSize(wifiEditTarget);
  if (buffer == nullptr || bufferSize == 0) {
    return;
  }
  clampWifiEditCursor();
  if (wifiEditTarget == WifiEditTarget::Port && (c < '0' || c > '9')) {
    return;
  }
  size_t length = strlen(buffer);
  if (length + 1 >= bufferSize) {
    return;
  }
  memmove(buffer + wifiEditCursor + 1, buffer + wifiEditCursor, length - wifiEditCursor + 1);
  buffer[wifiEditCursor] = c;
  ++wifiEditCursor;
  needsDraw = true;
}

void backspaceWifiEdit() {
  char* buffer = wifiEditBuffer(wifiEditTarget);
  if (buffer == nullptr) {
    return;
  }
  clampWifiEditCursor();
  size_t length = strlen(buffer);
  if (length == 0 || wifiEditCursor == 0) {
    return;
  }
  memmove(buffer + wifiEditCursor - 1, buffer + wifiEditCursor, length - wifiEditCursor + 1);
  --wifiEditCursor;
  needsDraw = true;
}

void moveWifiEditCursor(int8_t direction) {
  char* buffer = wifiEditBuffer(wifiEditTarget);
  if (buffer == nullptr) {
    return;
  }
  clampWifiEditCursor();
  size_t length = strlen(buffer);
  if (direction < 0 && wifiEditCursor > 0) {
    --wifiEditCursor;
  } else if (direction > 0 && wifiEditCursor < length) {
    ++wifiEditCursor;
  }
  needsDraw = true;
}

void startWifiEditForField(uint8_t field) {
  switch (field) {
    case 0:
      wifiEditTarget = WifiEditTarget::Ssid;
      break;
    case 1:
      wifiEditTarget = WifiEditTarget::Password;
      break;
    case 2:
      wifiEditTarget = WifiEditTarget::Host;
      break;
    case 3:
      wifiEditTarget = WifiEditTarget::Port;
      break;
    case 4:
      wifiEditTarget = WifiEditTarget::Token;
      break;
    default:
      wifiEditTarget = WifiEditTarget::None;
      break;
  }
  clampWifiEditCursor();
  char* buffer = wifiEditBuffer(wifiEditTarget);
  wifiEditCursor = buffer == nullptr ? 0 : strlen(buffer);
  needsDraw = true;
}

void finishWifiEdit() {
  wifiEditTarget = WifiEditTarget::None;
  wifiEditCursor = 0;
  needsDraw = true;
}

void scanWifiNetworks() {
  uint8_t count = wifi.scanNetworks();
  wifiNetworkIndex = 0;
  if (count > 0 && wifiSsidEdit[0] == '\0') {
    strlcpy(wifiSsidEdit, wifi.network(0).ssid, sizeof(wifiSsidEdit));
  }
  needsDraw = true;
}

void selectWifiNetwork(int8_t direction) {
  uint8_t count = wifi.networkCount();
  if (count == 0) {
    return;
  }
  int next = static_cast<int>(wifiNetworkIndex) + direction;
  if (next < 0) {
    next = count - 1;
  }
  if (next >= count) {
    next = 0;
  }
  wifiNetworkIndex = static_cast<uint8_t>(next);
  const char* selectedSsid = wifi.network(wifiNetworkIndex).ssid;
  if (strcmp(wifiSsidEdit, selectedSsid) != 0) {
    wifiPasswordEdit[0] = '\0';
  }
  strlcpy(wifiSsidEdit, selectedSsid, sizeof(wifiSsidEdit));
  needsDraw = true;
}

void connectWifi() {
  uint32_t port = strtoul(wifiPortEdit, nullptr, 10);
  if (port == 0 || port > 65535) {
    port = 47392;
    snprintf(wifiPortEdit, sizeof(wifiPortEdit), "%lu", port);
  }

  BuddyWifiConfigRequest request{};
  request.connectNow = true;
  request.hasSsid = true;
  request.hasPassword = true;
  request.hasHost = true;
  request.hasPort = true;
  request.hasToken = true;
  strlcpy(request.ssid, wifiSsidEdit, sizeof(request.ssid));
  strlcpy(request.password, wifiPasswordEdit, sizeof(request.password));
  strlcpy(request.host, wifiHostEdit, sizeof(request.host));
  strlcpy(request.token, wifiTokenEdit, sizeof(request.token));
  request.port = static_cast<uint16_t>(port);
  wifi.applyConfig(request);
  if (settingsStore.values().connectionMode != ConnectionMode::Wifi) {
    settingsStore.setConnectionMode(ConnectionMode::Auto);
  }
  viewMode = ViewMode::Wifi;
  needsDraw = true;
}

void handleLine(const String& line, HostTransport source) {
  if (source == HostTransport::Ble) {
    BuddyPairRequest pairRequest{};
    String pairError;
    if (parsePairRequestLine(line, pairRequest, pairError)) {
      if (strcmp(pairRequest.code, blePairCode) == 0) {
        blePaired = true;
        sendToHost(
            buildDeviceStatusLine(
                "pair_ok",
                heartbeat.state,
                heartbeat.animation),
            source);
      } else {
        sendToHost(buildErrorLine("pair code mismatch"), source);
      }
      needsDraw = true;
      return;
    }
    if (!blePaired) {
      sendToHost(buildErrorLine("pairing required"), source);
      return;
    }
  }

  BuddyHeartbeat next{};
  String error;
  if (parseHeartbeatLine(line, next, error)) {
    const BuddyState previousState = heartbeat.state;
    heartbeat = next;
    const uint32_t now = millis();
    lastHeartbeatMs = now;
    petStats.ingestTokens(
        next.hasTokens,
        next.totalTokens,
        next.hasTodayTokens,
        next.todayTokens);
    // 先向请求来源回 ack，避免 BLE notify / UI 唤醒拖慢 WiFi heartbeat。
    sendToHost(
        buildDeviceStatusLine(
            "heartbeat_applied",
            heartbeat.state,
            heartbeat.animation),
        source);
    if (next.state == BuddyState::Review && previousState != BuddyState::Review) {
      wakeDisplay(now);
      feedbackReview();
    } else if (next.state == BuddyState::Failed &&
               previousState != BuddyState::Failed) {
      wakeDisplay(now);
      feedbackFailed();
    }
    if (viewMode == ViewMode::Menu) {
      viewMode = ViewMode::Status;
    }
    needsDraw = true;
    return;
  }

  BuddyApprovalRequest nextApproval{};
  if (parseApprovalRequestLine(line, nextApproval, error)) {
    approvalRequest = nextApproval;
    approvalTransport = source;
    const uint32_t now = millis();
    heartbeat.state = BuddyState::Waiting;
    heartbeat.animation = BuddyAnimation::Waving;
    snprintf(
        heartbeat.summary,
        sizeof(heartbeat.summary),
        "Approval: %s",
        approvalRequest.tool[0] ? approvalRequest.tool : "tool");
    lastHeartbeatMs = now;
    petStatsMode = false;
    // 审批请求也先确认接收，再做音效、LED 和屏幕唤醒。
    sendToHost(
        buildDeviceStatusLine(
            "approval_request_applied",
            heartbeat.state,
            heartbeat.animation),
        source);
    wakeDisplay(now);
    feedbackApprovalRequest();
    viewMode = ViewMode::Status;
    needsDraw = true;
    return;
  }

  BuddyWifiConfigRequest wifiConfig{};
  if (parseWifiConfigLine(line, wifiConfig, error)) {
    wifi.applyConfig(wifiConfig);
    syncWifiEditFromConfig();
    if (wifiConfig.hasPassword) {
      strlcpy(
          wifiPasswordEdit,
          wifiConfig.password,
          sizeof(wifiPasswordEdit));
    }
    if (wifiConfig.hasToken) {
      strlcpy(wifiTokenEdit, wifiConfig.token, sizeof(wifiTokenEdit));
    }
    if (wifiConfig.connectNow) {
      if (settingsStore.values().connectionMode != ConnectionMode::Wifi) {
        settingsStore.setConnectionMode(ConnectionMode::Auto);
      }
    }
    needsDraw = true;
    sendToHost(
        buildDeviceStatusLine(
            wifiConfig.clear ? "wifi_config_cleared" : "wifi_config_applied",
            heartbeat.state,
            heartbeat.animation),
        source);
    return;
  }

  sendToHost(buildErrorLine(error.c_str()), source);
}

void pollSerial() {
  while (Serial.available() > 0) {
    char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      if (serialBuffer.length() > 0) {
        handleLine(serialBuffer, HostTransport::Serial);
        serialBuffer = "";
      }
    } else {
      serialBuffer += c;
    }
  }
}

void pollBle() {
  String line;
  while (ble.pollLine(line)) {
    handleLine(line, HostTransport::Ble);
  }
}

void pollWifi() {
  String line;
  while (wifi.pollLine(line)) {
    handleLine(line, HostTransport::Wifi);
  }
}

void pollKeyboard() {
  if (!M5Cardputer.Keyboard.isChange() || !M5Cardputer.Keyboard.isPressed()) {
    return;
  }

  const uint32_t now = millis();
  if (displaySleeping) {
    wakeDisplay(now);
    return;
  }
  lastUserActivityMs = now;

  Keyboard_Class::KeysState keys = M5Cardputer.Keyboard.keysState();
  if (viewMode == ViewMode::Wifi && wifiEditTarget != WifiEditTarget::None) {
    if (keys.enter) {
      finishWifiEdit();
    }
    if (keys.del) {
      backspaceWifiEdit();
    }
    if (keys.space) {
      insertWifiEditChar(' ');
    }
    if (keys.fn) {
      for (char c : keys.word) {
        KeyAction action;
        if (fnLayerActionForChar(c, &action)) {
          if (action == KeyAction::Left) {
            moveWifiEditCursor(-1);
          } else if (action == KeyAction::Right) {
            moveWifiEditCursor(1);
          } else if (action == KeyAction::Back) {
            finishWifiEdit();
          }
        }
      }
    }
    for (uint8_t hid : keys.hid_keys) {
      KeyAction action;
      if (hidKeyAction(hid, &action)) {
        if (action == KeyAction::Left) {
          moveWifiEditCursor(-1);
        } else if (action == KeyAction::Right) {
          moveWifiEditCursor(1);
        }
      }
    }
    for (char c : keys.word) {
      if (keys.fn && isFnLayerActionChar(c)) {
        continue;
      }
      if (c == '\r' || c == '\n') {
        finishWifiEdit();
      } else if (c == 27) {
        finishWifiEdit();
      } else if (c >= 32 && c <= 126) {
        insertWifiEditChar(c);
      }
    }
    return;
  }

  if (keys.enter) {
    queueKey(KeyAction::Select);
  }
  if (keys.space) {
    queueKey(KeyAction::Select);
  }
  if (keys.del) {
    queueKey(KeyAction::Back);
  }
  if (keys.tab) {
    queueKey(KeyAction::Menu);
  }
  if (keys.fn) {
    for (char c : keys.word) {
      queueFnLayerAction(c);
    }
  }
  for (uint8_t hid : keys.hid_keys) {
    KeyAction action;
    if (hidKeyAction(hid, &action)) {
      queueKey(action);
    }
  }
  for (char c : keys.word) {
    if (keys.fn && isFnLayerActionChar(c)) {
      continue;
    }
    KeyAction action;
    if (wordKeyAction(c, &action)) {
      queueKey(action);
    }
  }
}

ViewMode viewForMenuIndex(uint8_t index) {
  switch (index) {
    case 0:
      return ViewMode::Status;
    case 1:
      return ViewMode::Approval;
    case 2:
      return ViewMode::Settings;
    case 3:
      return ViewMode::Wifi;
    case 4:
      return ViewMode::Device;
    case 5:
      return ViewMode::Help;
    case 6:
      return ViewMode::Sleep;
    default:
      return ViewMode::Status;
  }
}

bool shortcutToIndex(KeyAction action, uint8_t& index) {
  switch (action) {
    case KeyAction::Shortcut1:
      index = 0;
      return true;
    case KeyAction::Shortcut2:
      index = 1;
      return true;
    case KeyAction::Shortcut3:
      index = 2;
      return true;
    case KeyAction::Shortcut4:
      index = 3;
      return true;
    case KeyAction::Shortcut5:
      index = 4;
      return true;
    case KeyAction::Shortcut6:
      index = 5;
      return true;
    case KeyAction::Shortcut7:
      index = 6;
      return true;
    default:
      return false;
  }
}

void sendDecision(const char* decision) {
  if (!approvalRequest.active || approvalRequest.id[0] == '\0') {
    viewMode = ViewMode::Menu;
    needsDraw = true;
    return;
  }

  sendToHost(
      buildApprovalDecisionLine(approvalRequest.id, decision),
      approvalTransport);
  wakeDisplay(millis());
  if (strcmp(decision, "deny") == 0) {
    petStats.recordDenial();
    feedbackDeny();
  } else {
    petStats.recordApproval();
    feedbackApprove();
  }
  approvalRequest.active = false;
  petStatsMode = false;
  approvalTransport = HostTransport::Broadcast;
  viewMode = ViewMode::Status;
  needsDraw = true;
}

void handleKey(KeyAction action) {
  uint8_t shortcutIndex = 0;
  if (shortcutToIndex(action, shortcutIndex)) {
    menuIndex = shortcutIndex;
    viewMode = viewForMenuIndex(menuIndex);
    petStatsMode = false;
    playSfx(SfxEvent::ConfirmArpeggio);
    needsDraw = true;
    return;
  }

  if (action == KeyAction::Menu) {
    sendToHost(buildButtonEventLine("menu", "short"));
    viewMode = ViewMode::Menu;
    petStatsMode = false;
    playSfx(SfxEvent::Menu);
    needsDraw = true;
    return;
  }

  if (action == KeyAction::Approve) {
    if (approvalRequest.active) {
      sendDecision("approve_once");
    }
    return;
  }
  if (action == KeyAction::Deny) {
    if (approvalRequest.active) {
      sendDecision("deny");
    }
    return;
  }
  if (approvalRequest.active) {
    petStatsMode = false;
    if (action == KeyAction::Select) {
      sendDecision("approve_once");
    } else if (action == KeyAction::Back) {
      sendDecision("deny");
    }
    if (action == KeyAction::Select || action == KeyAction::Back) {
      return;
    }
  }

  if (viewMode == ViewMode::Status && !approvalRequest.active) {
    if (action == KeyAction::Select) {
      petStatsMode = !petStatsMode;
      playSfx(SfxEvent::ConfirmArpeggio);
      needsDraw = true;
      return;
    }
    if (action == KeyAction::Back && petStatsMode) {
      petStatsMode = false;
      playSfx(SfxEvent::Back);
      needsDraw = true;
      return;
    }
  }

  if (viewMode == ViewMode::Menu) {
    if (action == KeyAction::Up && menuIndex > 0) {
      --menuIndex;
      playSfx(SfxEvent::NavBlip);
    } else if (action == KeyAction::Down && menuIndex + 1 < kMenuCount) {
      ++menuIndex;
      playSfx(SfxEvent::NavBlip);
    } else if (action == KeyAction::Select) {
      viewMode = viewForMenuIndex(menuIndex);
      petStatsMode = false;
      playSfx(SfxEvent::ConfirmArpeggio);
    } else if (action == KeyAction::Back) {
      viewMode = ViewMode::Status;
      petStatsMode = false;
      playSfx(SfxEvent::Back);
    }
    needsDraw = true;
    return;
  }

  if (viewMode == ViewMode::Wifi) {
    if (action == KeyAction::Refresh) {
      scanWifiNetworks();
      playSfx(SfxEvent::ConfirmArpeggio);
    } else if (action == KeyAction::Connect) {
      connectWifi();
      playSfx(SfxEvent::SaveFanfare);
    } else if (action == KeyAction::Up && wifiFieldIndex > 0) {
      --wifiFieldIndex;
      playSfx(SfxEvent::NavBlip);
    } else if (action == KeyAction::Down &&
               wifiFieldIndex + 1 < kWifiFieldCount) {
      ++wifiFieldIndex;
      playSfx(SfxEvent::NavBlip);
    } else if (wifiFieldIndex == 0 && action == KeyAction::Left) {
      selectWifiNetwork(-1);
      playSfx(SfxEvent::NavBlip);
    } else if (wifiFieldIndex == 0 && action == KeyAction::Right) {
      selectWifiNetwork(1);
      playSfx(SfxEvent::NavBlip);
    } else if (action == KeyAction::Select) {
      if (wifiFieldIndex == kWifiFieldCount - 1) {
        connectWifi();
        playSfx(SfxEvent::SaveFanfare);
      } else {
        startWifiEditForField(wifiFieldIndex);
        playSfx(SfxEvent::ConfirmArpeggio);
      }
    } else if (action == KeyAction::Back) {
      if (wifiEditTarget != WifiEditTarget::None) {
        finishWifiEdit();
        playSfx(SfxEvent::SaveFanfare);
      } else {
        viewMode = ViewMode::Menu;
        playSfx(SfxEvent::Back);
      }
    }
    needsDraw = true;
    return;
  }

  if (viewMode == ViewMode::Settings) {
    if (action == KeyAction::Up && settingsIndex > 0) {
      --settingsIndex;
      playSfx(SfxEvent::NavBlip);
    } else if (action == KeyAction::Down &&
               settingsIndex + 1 < kSettingsCount) {
      ++settingsIndex;
      playSfx(SfxEvent::NavBlip);
    } else if (action == KeyAction::Left) {
      settingsStore.adjust(settingsIndex, -1);
      playSfx(SfxEvent::SaveFanfare);
    } else if (action == KeyAction::Right || action == KeyAction::Select) {
      settingsStore.activate(settingsIndex);
      playSfx(SfxEvent::SaveFanfare);
    } else if (action == KeyAction::Back) {
      viewMode = ViewMode::Menu;
      playSfx(SfxEvent::Back);
    }
    needsDraw = true;
    return;
  }

  if (viewMode == ViewMode::Approval) {
    if (approvalRequest.active && action == KeyAction::Select) {
      sendDecision("approve_once");
    } else if (approvalRequest.active && action == KeyAction::Back) {
      sendDecision("deny");
    } else if (!approvalRequest.active && action == KeyAction::Back) {
      viewMode = ViewMode::Menu;
      playSfx(SfxEvent::Back);
    }
    needsDraw = true;
    return;
  }

  if (viewMode == ViewMode::Sleep) {
    if (action == KeyAction::Select) {
      playSfx(SfxEvent::Back);
      enterDisplaySleep(millis());
    } else if (action == KeyAction::Back || action == KeyAction::Up ||
               action == KeyAction::Down || action == KeyAction::Left ||
               action == KeyAction::Right) {
      viewMode = ViewMode::Menu;
      playSfx(SfxEvent::Back);
      needsDraw = true;
    }
    return;
  }

  if (action == KeyAction::Back) {
    viewMode = ViewMode::Menu;
    petStatsMode = false;
    playSfx(SfxEvent::Back);
    needsDraw = true;
    return;
  }
}

void dispatchKeys() {
  KeyAction action;
  while (popKey(action)) {
    handleKey(action);
  }
}

}  // namespace

void setup() {
  auto cfg = M5.config();
  M5Cardputer.begin(cfg, true);
  Serial.begin(115200);
  M5Cardputer.Display.setBrightness(kLowBatterySafeBrightness);

  view.begin();
  settingsStore.begin();
  petStats.begin();
  initBlePairCode();
  snprintf(heartbeat.summary, sizeof(heartbeat.summary), "Waiting for Codex");

  lastHeartbeatMs = millis();
  lastUserActivityMs = lastHeartbeatMs;
  const PowerSnapshot power = readPowerSnapshot();
  if (shouldUseLowBatterySafeMode(power)) {
    enterLowBatterySafeMode(lastHeartbeatMs, power);
    return;
  }

  startNormalRuntime(lastHeartbeatMs);
}

void loop() {
  M5Cardputer.update();
  uint32_t now = millis();
  const PowerSnapshot power = readPowerSnapshot();
  if (updateLowBatterySafeMode(now, power)) {
    return;
  }

  const bool bootLedOnly = bootLedConfirmActive(now);
  if (bootLedOnly) {
    updateLed(now);
  } else if (transportsStarted) {
    wifi.update(settingsStore.values().connectionMode, now);
  }
  const bool bleConnected = transportsStarted && ble.connected();
  if (lastBleConnected && !bleConnected) {
    blePaired = false;
    needsDraw = true;
  }
  lastBleConnected = bleConnected;
  pollSerial();
  if (transportsStarted) {
    pollBle();
    pollWifi();
  }
  pollKeyboard();
  dispatchKeys();
  sfx.setEnabled(settingsStore.values().soundEnabled);
  sfx.update(now);
  updatePetMotion(now);
  if (!bootLedOnly) {
    updateLed(now);
  }
  maybeAutoSleep(now);

  const uint32_t drawIntervalMs =
      approvalRequest.active ? kApprovalDrawIntervalMs : kStatusDrawIntervalMs;
  if (!displaySleeping &&
      (needsDraw || now - lastDrawMs > drawIntervalMs)) {
    drawNow(now);
  }
}
