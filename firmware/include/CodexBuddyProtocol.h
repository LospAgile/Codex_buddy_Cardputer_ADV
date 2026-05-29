#pragma once

#include <Arduino.h>

enum class BuddyState {
  Idle,
  Running,
  Waiting,
  Review,
  Failed,
};

enum class BuddyAnimation {
  Idle,
  Running,
  Waiting,
  Waving,
  Jumping,
  Review,
  Failed,
  RunningRight,
  RunningLeft,
};

struct BuddyEntry {
  char kind[24] = {};
  char text[96] = {};
};

struct BuddyPet {
  char id[48] = {};
  char displayName[48] = {};
};

struct BuddyHeartbeat {
  BuddyState state = BuddyState::Idle;
  BuddyAnimation animation = BuddyAnimation::Idle;
  char summary[128] = {};
  BuddyEntry entries[4];
  uint8_t entryCount = 0;
  bool hasTokens = false;
  uint32_t totalTokens = 0;
  bool hasTodayTokens = false;
  uint32_t todayTokens = 0;
  BuddyPet pet;
};

struct BuddyApprovalRequest {
  bool active = false;
  char id[96] = {};
  char tool[48] = {};
  char hint[128] = {};
};

struct BuddyWifiConfigRequest {
  bool clear = false;
  bool connectNow = false;
  bool hasSsid = false;
  bool hasPassword = false;
  bool hasHost = false;
  bool hasPort = false;
  bool hasToken = false;
  char ssid[33] = {};
  char password[65] = {};
  char host[64] = {};
  uint16_t port = 0;
  char token[96] = {};
};

struct BuddyPairRequest {
  char code[8] = {};
};

const char* buddyStateLabel(BuddyState state);
const char* buddyAnimationLabel(BuddyAnimation animation);
BuddyAnimation buddyDefaultAnimation(BuddyState state);
bool parseHeartbeatLine(const String& line, BuddyHeartbeat& out, String& error);
bool parseApprovalRequestLine(
    const String& line,
    BuddyApprovalRequest& out,
    String& error);
bool parseWifiConfigLine(
    const String& line,
    BuddyWifiConfigRequest& out,
    String& error);
bool parsePairRequestLine(
    const String& line,
    BuddyPairRequest& out,
    String& error);
String buildButtonEventLine(const char* button, const char* action);
String buildApprovalDecisionLine(const char* requestId, const char* decision);
String buildWifiHelloLine(const char* token);
String buildDeviceStatusLine(
    const char* status,
    BuddyState state,
    BuddyAnimation animation);
String buildErrorLine(const char* message);
