#include "PetStats.h"

#include <Preferences.h>

namespace {

constexpr const char* kNamespace = "codex-pet";

uint8_t clampPercent(int value) {
  if (value < 0) {
    return 0;
  }
  if (value > 100) {
    return 100;
  }
  return static_cast<uint8_t>(value);
}

uint8_t clampHearts(int value) {
  if (value < 1) {
    return 1;
  }
  if (value > 5) {
    return 5;
  }
  return static_cast<uint8_t>(value);
}

uint8_t levelForTokens(bool hasTokens, uint32_t totalTokens) {
  if (!hasTokens) {
    return 1;
  }
  uint32_t level = 1 + totalTokens / 50000UL;
  if (level > 99) {
    level = 99;
  }
  return static_cast<uint8_t>(level);
}

uint32_t napElapsedSeconds(bool active, uint32_t startedMs, uint32_t now) {
  if (!active) {
    return 0;
  }
  return (now - startedMs) / 1000UL;
}

}  // namespace

void PetStatsStore::begin() {
  Preferences preferences;
  if (!preferences.begin(kNamespace, true)) {
    return;
  }
  approvals_ = preferences.getUInt("approvals", 0);
  denials_ = preferences.getUInt("denials", 0);
  napSeconds_ = preferences.getUInt("napSec", 0);
  hasTotalTokens_ = preferences.getBool("hasTotal", false);
  totalTokens_ = preferences.getUInt("totalTok", 0);
  hasTodayTokens_ = preferences.getBool("hasToday", false);
  todayTokens_ = preferences.getUInt("todayTok", 0);
  preferences.end();
}

PetStatsInfo PetStatsStore::snapshot(uint32_t now) const {
  const uint32_t napSeconds =
      napSeconds_ + napElapsedSeconds(napActive_, napStartedMs_, now);

  PetStatsInfo info;
  info.approvals = approvals_;
  info.denials = denials_;
  info.napSeconds = napSeconds;
  info.hasTotalTokens = hasTotalTokens_;
  info.totalTokens = totalTokens_;
  info.hasTodayTokens = hasTodayTokens_;
  info.todayTokens = todayTokens_;
  info.level = levelForTokens(hasTotalTokens_, totalTokens_);

  const int approvalBoost = static_cast<int>(approvals_ > 25 ? 25 : approvals_);
  const int denialPenalty = static_cast<int>((denials_ > 10 ? 10 : denials_) * 4);
  const int tokenBoost =
      hasTotalTokens_
          ? static_cast<int>(
                totalTokens_ / 20000UL > 20 ? 20 : totalTokens_ / 20000UL)
          : 0;
  const int napMinutes = static_cast<int>(
      napSeconds / 60UL > 20 ? 20 : napSeconds / 60UL);

  info.moodHearts =
      clampHearts(3 + static_cast<int>(approvals_ / 5) -
                  static_cast<int>(denials_ / 3));
  info.fedPercent = clampPercent(45 + approvalBoost * 2 - denialPenalty + tokenBoost);
  info.energyPercent = clampPercent(42 + napMinutes * 3 - static_cast<int>(denials_ * 2));
  return info;
}

void PetStatsStore::recordApproval() {
  ++approvals_;
  save();
}

void PetStatsStore::recordDenial() {
  ++denials_;
  save();
}

void PetStatsStore::beginNap(uint32_t now) {
  if (napActive_) {
    return;
  }
  napActive_ = true;
  napStartedMs_ = now;
}

void PetStatsStore::endNap(uint32_t now) {
  if (!napActive_) {
    return;
  }
  const uint32_t gained = napElapsedSeconds(true, napStartedMs_, now);
  napActive_ = false;
  napStartedMs_ = 0;
  if (gained == 0) {
    return;
  }
  napSeconds_ += gained;
  save();
}

void PetStatsStore::ingestTokens(
    bool hasTotalTokens,
    uint32_t totalTokens,
    bool hasTodayTokens,
    uint32_t todayTokens) {
  bool dirty = false;
  if (hasTotalTokens && (!hasTotalTokens_ || totalTokens_ != totalTokens)) {
    hasTotalTokens_ = true;
    totalTokens_ = totalTokens;
    dirty = true;
  }
  if (hasTodayTokens && (!hasTodayTokens_ || todayTokens_ != todayTokens)) {
    hasTodayTokens_ = true;
    todayTokens_ = todayTokens;
    dirty = true;
  }
  if (dirty) {
    save();
  }
}

void PetStatsStore::save() {
  Preferences preferences;
  if (!preferences.begin(kNamespace, false)) {
    return;
  }
  preferences.putUInt("approvals", approvals_);
  preferences.putUInt("denials", denials_);
  preferences.putUInt("napSec", napSeconds_);
  preferences.putBool("hasTotal", hasTotalTokens_);
  preferences.putUInt("totalTok", totalTokens_);
  preferences.putBool("hasToday", hasTodayTokens_);
  preferences.putUInt("todayTok", todayTokens_);
  preferences.end();
}
