#pragma once

#include <Arduino.h>

enum class SfxEvent : uint8_t {
  NavBlip,
  ConfirmArpeggio,
  ApproveChord,
  ApprovalAlert,
  Back,
  Deny,
  SaveFanfare,
  Menu,
  Warn,
  Warn2,
};

class SfxPlayer {
 public:
  struct Note {
    uint16_t frequency;
    uint16_t durationMs;
  };

  void begin(bool enabled);
  void setEnabled(bool enabled);
  void play(SfxEvent event);
  void update(uint32_t now);
  void stop();

 private:
  const Note* sequence_ = nullptr;
  uint8_t count_ = 0;
  uint8_t index_ = 0;
  uint32_t noteUntilMs_ = 0;
  bool enabled_ = false;

  void startCurrent(uint32_t now);
};
