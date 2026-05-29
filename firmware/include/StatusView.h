#pragma once

#include <Arduino.h>

#include "AppSettings.h"
#include "CodexBuddyProtocol.h"
#include "PetStats.h"

enum class ViewMode {
  Status,
  Menu,
  Approval,
  Settings,
  Wifi,
  Device,
  Help,
  Sleep,
};

struct DeviceInfo {
  uint32_t uptimeMs = 0;
  uint32_t freeHeap = 0;
  uint32_t heartbeatAgeMs = 0;
  int32_t batteryLevel = -1;
  int16_t batteryMv = -1;
  int16_t vbusMv = -1;
  bool chargingKnown = false;
  bool charging = false;
  bool bleConnected = false;
  bool wifiConnected = false;
  bool wifiTcpConnected = false;
  char wifiSsid[33];
  char wifiIp[16];
  char wifiHost[64];
  uint16_t wifiPort = 47392;
  bool wifiTokenConfigured = false;
  int32_t wifiRssi = 0;
  const char* wifiStatus = "not configured";
  const char* bleName = "Codex-Buddy";
  const char* blePairCode = "";
  const char* transport = "BLE";
  const char* firmwareVersion = "dev";
  const char* imuStatus = "off";
  char ledStatus[12] = "off";
};

struct WifiNetworkView {
  char ssid[33];
  int32_t rssi = 0;
  bool secure = false;
};

struct WifiViewInfo {
  bool editing = false;
  uint8_t focus = 0;
  uint8_t editCursor = 0;
  uint8_t selectedNetwork = 0;
  uint8_t networkCount = 0;
  WifiNetworkView networks[6];
  char ssid[33];
  char password[65];
  char host[64];
  char port[6];
  char token[96];
  bool configured = false;
  bool wifiConnected = false;
  bool tcpConnected = false;
  char ip[16];
  int32_t rssi = 0;
  const char* status = "not configured";
};

class StatusView {
 public:
  void begin();
  void draw(
      const BuddyHeartbeat& heartbeat,
      const BuddyApprovalRequest& approvalRequest,
      ViewMode mode,
      const AppSettings& settings,
      const DeviceInfo& deviceInfo,
      const WifiViewInfo& wifiInfo,
      const PetStatsInfo& petStats,
      bool petStatsMode,
      uint8_t menuIndex,
      uint8_t settingsIndex);
  void drawBoot(const char* message);
  void drawLowBatterySafeBoot(
      const AppSettings& settings,
      int32_t batteryLevel,
      int16_t batteryMv,
      int16_t vbusMv);
};
