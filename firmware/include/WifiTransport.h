#pragma once

#include <Arduino.h>
#include <WiFi.h>

#include "AppSettings.h"
#include "CodexBuddyProtocol.h"

struct WifiRuntimeInfo {
  bool configured = false;
  bool wifiConnected = false;
  bool tcpConnected = false;
  char ssid[33];
  char password[65];
  char host[64];
  uint16_t port = 47392;
  char token[96];
  char ip[16];
  int32_t rssi = 0;
  const char* status = "not configured";
};

struct WifiNetworkInfo {
  char ssid[33];
  int32_t rssi = 0;
  bool secure = false;
};

class CodexBuddyWifi {
 public:
  void begin();
  void update(ConnectionMode mode, uint32_t now);
  bool pollLine(String& line);
  void sendLine(const String& line);
  void applyConfig(const BuddyWifiConfigRequest& request);
  uint8_t scanNetworks();
  uint8_t networkCount() const { return networkCount_; }
  const WifiNetworkInfo& network(uint8_t index) const;
  WifiRuntimeInfo info();
  bool tcpConnected();
  bool wifiConnected() const;
  bool configured() const { return configured_; }

 private:
  struct WifiConfig {
    char ssid[33];
    char password[65];
    char host[64];
    uint16_t port = 47392;
    char token[96];
  };

  WifiConfig config_;
  WiFiClient client_;
  String rxBuffer_;
  String rxLines_[4];
  uint8_t rxHead_ = 0;
  uint8_t rxTail_ = 0;
  uint8_t rxCount_ = 0;
  uint32_t lastWifiAttemptMs_ = 0;
  uint32_t lastTcpAttemptMs_ = 0;
  bool configured_ = false;
  bool started_ = false;
  WifiNetworkInfo networks_[6];
  uint8_t networkCount_ = 0;
  const char* status_ = "not configured";

  void load();
  void save();
  void clear();
  void startRadio();
  void ensureWifi(uint32_t now);
  void ensureTcp(uint32_t now);
  void readTcp();
  void appendIncoming(char c);
  void queueLine(const String& line);
  bool shouldUse(ConnectionMode mode) const;
};
