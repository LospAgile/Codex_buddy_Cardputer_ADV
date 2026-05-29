#include "AppSettings.h"

#include <M5Cardputer.h>
#include <Preferences.h>

namespace {

constexpr const char* kNamespace = "codex-ui";
constexpr uint8_t kDefaultBrightness = 160;
constexpr uint8_t kMinBrightness = 40;
constexpr uint8_t kMaxBrightness = 255;
constexpr uint8_t kDefaultSfxVolume = 72;

uint8_t clampBrightness(int value) {
  if (value < kMinBrightness) {
    return kMinBrightness;
  }
  if (value > kMaxBrightness) {
    return kMaxBrightness;
  }
  return static_cast<uint8_t>(value);
}

ConnectionMode normalizeMode(uint8_t value) {
  if (value > static_cast<uint8_t>(ConnectionMode::Wifi)) {
    return ConnectionMode::Auto;
  }
  return static_cast<ConnectionMode>(value);
}

LanguageMode normalizeLanguage(uint8_t value) {
  if (value > static_cast<uint8_t>(LanguageMode::ZhCn)) {
    return LanguageMode::EnUs;
  }
  return static_cast<LanguageMode>(value);
}

HomeLayoutMode normalizeHomeLayout(uint8_t value) {
  if (value > static_cast<uint8_t>(HomeLayoutMode::Focus)) {
    return HomeLayoutMode::Detail;
  }
  return static_cast<HomeLayoutMode>(value);
}

ConnectionMode nextMode(ConnectionMode mode, int8_t direction) {
  int value = static_cast<int>(mode) + direction;
  if (value < 0) {
    value = 2;
  }
  if (value > 2) {
    value = 0;
  }
  return static_cast<ConnectionMode>(value);
}

LanguageMode nextLanguage(LanguageMode mode, int8_t direction) {
  int value = static_cast<int>(mode) + direction;
  if (value < 0) {
    value = 1;
  }
  if (value > 1) {
    value = 0;
  }
  return static_cast<LanguageMode>(value);
}

HomeLayoutMode nextHomeLayout(HomeLayoutMode mode, int8_t direction) {
  int value = static_cast<int>(mode) + direction;
  if (value < 0) {
    value = 1;
  }
  if (value > 1) {
    value = 0;
  }
  return static_cast<HomeLayoutMode>(value);
}

uint16_t nextSleep(uint16_t current, int8_t direction) {
  constexpr uint16_t values[] = {0, 30, 120, 300, 600};
  uint8_t index = 0;
  for (uint8_t i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
    if (values[i] == current) {
      index = i;
      break;
    }
  }

  int next = static_cast<int>(index) + direction;
  if (next < 0) {
    next = sizeof(values) / sizeof(values[0]) - 1;
  }
  if (next >= static_cast<int>(sizeof(values) / sizeof(values[0]))) {
    next = 0;
  }
  return values[next];
}

}  // namespace

const char* connectionModeLabel(ConnectionMode mode) {
  switch (mode) {
    case ConnectionMode::Ble:
      return "ble";
    case ConnectionMode::Wifi:
      return "wifi";
    case ConnectionMode::Auto:
    default:
      return "auto";
  }
}

const char* languageModeLabel(LanguageMode mode) {
  switch (mode) {
    case LanguageMode::ZhCn:
      return "zh-CN";
    case LanguageMode::EnUs:
    default:
      return "en-US";
  }
}

const char* homeLayoutModeLabel(HomeLayoutMode mode) {
  switch (mode) {
    case HomeLayoutMode::Focus:
      return "focus";
    case HomeLayoutMode::Detail:
    default:
      return "detail";
  }
}

void SettingsStore::begin() {
  Preferences preferences;
  if (preferences.begin(kNamespace, true)) {
    settings_.brightness = preferences.getUChar("bright", kDefaultBrightness);
    settings_.language = normalizeLanguage(preferences.getUChar("lang", 1));
    settings_.soundEnabled = preferences.getBool("sound", true);
    settings_.ledEnabled = preferences.getBool("led", true);
    settings_.autoSleepSeconds = preferences.getUShort("sleep", 120);
    settings_.petMotionEnabled = preferences.getBool("motion", true);
    settings_.connectionMode =
        normalizeMode(preferences.getUChar("conn", 0));
    settings_.summaryVisible = preferences.getBool("summary", true);
    settings_.homeLayout = normalizeHomeLayout(preferences.getUChar("home", 0));
    preferences.end();
  }

  settings_.brightness = clampBrightness(settings_.brightness);
  apply();
}

void SettingsStore::save() {
  Preferences preferences;
  if (!preferences.begin(kNamespace, false)) {
    return;
  }
  preferences.putUChar("bright", settings_.brightness);
  preferences.putUChar("lang", static_cast<uint8_t>(settings_.language));
  preferences.putBool("sound", settings_.soundEnabled);
  preferences.putBool("led", settings_.ledEnabled);
  preferences.putUShort("sleep", settings_.autoSleepSeconds);
  preferences.putBool("motion", settings_.petMotionEnabled);
  preferences.putUChar("conn", static_cast<uint8_t>(settings_.connectionMode));
  preferences.putBool("summary", settings_.summaryVisible);
  preferences.putUChar("home", static_cast<uint8_t>(settings_.homeLayout));
  preferences.end();
  apply();
}

void SettingsStore::adjust(uint8_t index, int8_t direction) {
  switch (index) {
    case 0:
      settings_.brightness =
          clampBrightness(static_cast<int>(settings_.brightness) +
                          direction * 20);
      break;
    case 1:
      settings_.language = nextLanguage(settings_.language, direction);
      break;
    case 2:
      settings_.soundEnabled = !settings_.soundEnabled;
      break;
    case 3:
      settings_.ledEnabled = !settings_.ledEnabled;
      break;
    case 4:
      settings_.autoSleepSeconds =
          nextSleep(settings_.autoSleepSeconds, direction);
      break;
    case 5:
      settings_.petMotionEnabled = !settings_.petMotionEnabled;
      break;
    case 6:
      settings_.connectionMode =
          nextMode(settings_.connectionMode, direction);
      break;
    case 7:
      settings_.summaryVisible = !settings_.summaryVisible;
      break;
    case 8:
      settings_.homeLayout = nextHomeLayout(settings_.homeLayout, direction);
      break;
    default:
      return;
  }
  save();
}

void SettingsStore::activate(uint8_t index) {
  adjust(index, 1);
}

void SettingsStore::setConnectionMode(ConnectionMode mode) {
  settings_.connectionMode = normalizeMode(static_cast<uint8_t>(mode));
  save();
}

void SettingsStore::apply() {
  M5Cardputer.Display.setBrightness(settings_.brightness);
  M5Cardputer.Speaker.setVolume(settings_.soundEnabled ? kDefaultSfxVolume : 0);
}
