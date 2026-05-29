#pragma once

#include <Arduino.h>

enum class ConnectionMode : uint8_t {
  Auto = 0,
  Ble = 1,
  Wifi = 2,
};

enum class LanguageMode : uint8_t {
  EnUs = 0,
  ZhCn = 1,
};

enum class HomeLayoutMode : uint8_t {
  Detail = 0,
  Focus = 1,
};

struct AppSettings {
  uint8_t brightness = 160;
  LanguageMode language = LanguageMode::ZhCn;
  bool soundEnabled = true;
  bool ledEnabled = true;
  uint16_t autoSleepSeconds = 120;
  bool petMotionEnabled = true;
  ConnectionMode connectionMode = ConnectionMode::Auto;
  bool summaryVisible = true;
  HomeLayoutMode homeLayout = HomeLayoutMode::Detail;
};

class SettingsStore {
 public:
  void begin();
  const AppSettings& values() const { return settings_; }
  void save();
  void adjust(uint8_t index, int8_t direction);
  void activate(uint8_t index);
  void setConnectionMode(ConnectionMode mode);

 private:
  AppSettings settings_;
  void apply();
};

const char* connectionModeLabel(ConnectionMode mode);
const char* languageModeLabel(LanguageMode mode);
const char* homeLayoutModeLabel(HomeLayoutMode mode);
