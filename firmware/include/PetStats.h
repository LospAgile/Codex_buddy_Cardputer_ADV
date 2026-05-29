#pragma once

#include <Arduino.h>

struct PetStatsInfo {
  uint8_t moodHearts = 3;
  uint8_t fedPercent = 50;
  uint8_t energyPercent = 50;
  uint8_t level = 1;
  uint32_t approvals = 0;
  uint32_t denials = 0;
  uint32_t napSeconds = 0;
  bool hasTotalTokens = false;
  uint32_t totalTokens = 0;
  bool hasTodayTokens = false;
  uint32_t todayTokens = 0;
};

class PetStatsStore {
 public:
  void begin();
  PetStatsInfo snapshot(uint32_t now) const;
  void recordApproval();
  void recordDenial();
  void beginNap(uint32_t now);
  void endNap(uint32_t now);
  void ingestTokens(
      bool hasTotalTokens,
      uint32_t totalTokens,
      bool hasTodayTokens,
      uint32_t todayTokens);

 private:
  uint32_t approvals_ = 0;
  uint32_t denials_ = 0;
  uint32_t napSeconds_ = 0;
  bool hasTotalTokens_ = false;
  uint32_t totalTokens_ = 0;
  bool hasTodayTokens_ = false;
  uint32_t todayTokens_ = 0;
  bool napActive_ = false;
  uint32_t napStartedMs_ = 0;

  void save();
};
