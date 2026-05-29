#include "CodexBuddyProtocol.h"

#include <ArduinoJson.h>

namespace {

void copyUtf8(char* dest, size_t destSize, const char* src) {
  if (destSize == 0) {
    return;
  }

  dest[0] = '\0';
  if (src == nullptr) {
    return;
  }

  size_t out = 0;
  const uint8_t* input = reinterpret_cast<const uint8_t*>(src);
  while (*input != 0 && out + 1 < destSize) {
    uint8_t lead = *input;
    size_t len = 1;
    if ((lead & 0x80) == 0) {
      len = 1;
    } else if ((lead & 0xE0) == 0xC0) {
      len = 2;
    } else if ((lead & 0xF0) == 0xE0) {
      len = 3;
    } else if ((lead & 0xF8) == 0xF0) {
      len = 4;
    } else {
      ++input;
      continue;
    }

    bool valid = true;
    for (size_t i = 1; i < len; ++i) {
      if ((input[i] & 0xC0) != 0x80) {
        valid = false;
        break;
      }
    }
    if (!valid) {
      ++input;
      continue;
    }
    if (out + len >= destSize) {
      break;
    }

    for (size_t i = 0; i < len; ++i) {
      dest[out++] = static_cast<char>(input[i]);
    }
    input += len;
  }
  dest[out] = '\0';
}

BuddyState parseState(const char* value) {
  if (value == nullptr) {
    return BuddyState::Idle;
  }
  if (strcmp(value, "running") == 0) {
    return BuddyState::Running;
  }
  if (strcmp(value, "waiting") == 0) {
    return BuddyState::Waiting;
  }
  if (strcmp(value, "review") == 0) {
    return BuddyState::Review;
  }
  if (strcmp(value, "failed") == 0) {
    return BuddyState::Failed;
  }
  return BuddyState::Idle;
}

BuddyAnimation parseAnimation(const char* value, BuddyState state) {
  if (value == nullptr || value[0] == '\0') {
    return buddyDefaultAnimation(state);
  }
  if (strcmp(value, "running") == 0) {
    return BuddyAnimation::Running;
  }
  if (strcmp(value, "waiting") == 0) {
    return BuddyAnimation::Waiting;
  }
  if (strcmp(value, "waving") == 0) {
    return BuddyAnimation::Waving;
  }
  if (strcmp(value, "jumping") == 0) {
    return BuddyAnimation::Jumping;
  }
  if (strcmp(value, "review") == 0) {
    return BuddyAnimation::Review;
  }
  if (strcmp(value, "failed") == 0) {
    return BuddyAnimation::Failed;
  }
  if (strcmp(value, "running-right") == 0) {
    return BuddyAnimation::RunningRight;
  }
  if (strcmp(value, "running-left") == 0) {
    return BuddyAnimation::RunningLeft;
  }
  return BuddyAnimation::Idle;
}

}  // namespace

const char* buddyStateLabel(BuddyState state) {
  switch (state) {
    case BuddyState::Running:
      return "running";
    case BuddyState::Waiting:
      return "waiting";
    case BuddyState::Review:
      return "review";
    case BuddyState::Failed:
      return "failed";
    case BuddyState::Idle:
    default:
      return "idle";
  }
}

const char* buddyAnimationLabel(BuddyAnimation animation) {
  switch (animation) {
    case BuddyAnimation::Running:
      return "running";
    case BuddyAnimation::Waiting:
      return "waiting";
    case BuddyAnimation::Waving:
      return "waving";
    case BuddyAnimation::Jumping:
      return "jumping";
    case BuddyAnimation::Review:
      return "review";
    case BuddyAnimation::Failed:
      return "failed";
    case BuddyAnimation::RunningRight:
      return "running-right";
    case BuddyAnimation::RunningLeft:
      return "running-left";
    case BuddyAnimation::Idle:
    default:
      return "idle";
  }
}

BuddyAnimation buddyDefaultAnimation(BuddyState state) {
  switch (state) {
    case BuddyState::Running:
      return BuddyAnimation::Running;
    case BuddyState::Waiting:
      return BuddyAnimation::Waving;
    case BuddyState::Review:
      return BuddyAnimation::Review;
    case BuddyState::Failed:
      return BuddyAnimation::Failed;
    case BuddyState::Idle:
    default:
      return BuddyAnimation::Idle;
  }
}

bool parseHeartbeatLine(const String& line, BuddyHeartbeat& out, String& error) {
  JsonDocument doc;
  DeserializationError jsonError = deserializeJson(doc, line);
  if (jsonError) {
    error = jsonError.c_str();
    return false;
  }

  const char* type = doc["type"] | "";
  if (strcmp(type, "heartbeat") != 0) {
    error = "not a heartbeat";
    return false;
  }

  BuddyHeartbeat next{};
  next.state = parseState(doc["state"] | "idle");
  next.animation = parseAnimation(doc["animation"] | "", next.state);
  copyUtf8(next.summary, sizeof(next.summary), doc["summary"] | "");

  JsonArray entries = doc["entries"].as<JsonArray>();
  for (JsonObject entry : entries) {
    if (next.entryCount >= 4) {
      break;
    }
    copyUtf8(next.entries[next.entryCount].kind,
             sizeof(next.entries[next.entryCount].kind),
             entry["kind"] | "");
    copyUtf8(next.entries[next.entryCount].text,
             sizeof(next.entries[next.entryCount].text),
             entry["text"] | "");
    ++next.entryCount;
  }

  JsonObject tokens = doc["tokens"].as<JsonObject>();
  if (!tokens.isNull() && tokens["total"].is<uint32_t>()) {
    next.hasTokens = true;
    next.totalTokens = tokens["total"].as<uint32_t>();
  }
  if (!tokens.isNull() && tokens["today"].is<uint32_t>()) {
    next.hasTodayTokens = true;
    next.todayTokens = tokens["today"].as<uint32_t>();
  }

  JsonObject pet = doc["pet"].as<JsonObject>();
  if (!pet.isNull()) {
    copyUtf8(next.pet.id, sizeof(next.pet.id), pet["id"] | "");
    copyUtf8(next.pet.displayName,
             sizeof(next.pet.displayName),
             pet["displayName"] | "");
  }

  out = next;
  error = "";
  return true;
}

bool parseApprovalRequestLine(
    const String& line,
    BuddyApprovalRequest& out,
    String& error) {
  JsonDocument doc;
  DeserializationError jsonError = deserializeJson(doc, line);
  if (jsonError) {
    error = jsonError.c_str();
    return false;
  }

  const char* type = doc["type"] | "";
  if (strcmp(type, "approval_request") != 0) {
    error = "not an approval_request";
    return false;
  }

  BuddyApprovalRequest next{};
  next.active = true;
  copyUtf8(next.id, sizeof(next.id), doc["id"] | "");
  copyUtf8(next.tool, sizeof(next.tool), doc["tool"] | "");
  copyUtf8(next.hint, sizeof(next.hint), doc["hint"] | "");

  if (next.id[0] == '\0') {
    error = "approval id required";
    return false;
  }

  out = next;
  error = "";
  return true;
}

bool parseWifiConfigLine(
    const String& line,
    BuddyWifiConfigRequest& out,
    String& error) {
  JsonDocument doc;
  DeserializationError jsonError = deserializeJson(doc, line);
  if (jsonError) {
    error = jsonError.c_str();
    return false;
  }

  const char* type = doc["type"] | "";
  if (strcmp(type, "wifi_config") != 0) {
    error = "not a wifi_config";
    return false;
  }

  BuddyWifiConfigRequest next{};
  next.clear = doc["clear"] | false;
  next.connectNow = doc["connect"] | false;

  if (doc["ssid"].is<const char*>()) {
    next.hasSsid = true;
    copyUtf8(next.ssid, sizeof(next.ssid), doc["ssid"] | "");
  }
  if (doc["password"].is<const char*>()) {
    next.hasPassword = true;
    copyUtf8(next.password, sizeof(next.password), doc["password"] | "");
  }
  if (doc["host"].is<const char*>()) {
    next.hasHost = true;
    copyUtf8(next.host, sizeof(next.host), doc["host"] | "");
  }
  if (doc["token"].is<const char*>()) {
    next.hasToken = true;
    copyUtf8(next.token, sizeof(next.token), doc["token"] | "");
  }
  if (doc["port"].is<int>()) {
    int port = doc["port"].as<int>();
    if (port <= 0 || port > 65535) {
      error = "wifi port out of range";
      return false;
    }
    next.hasPort = true;
    next.port = static_cast<uint16_t>(port);
  }

  if (!next.clear && !next.connectNow && !next.hasSsid &&
      !next.hasPassword && !next.hasHost && !next.hasPort &&
      !next.hasToken) {
    error = "wifi_config has no changes";
    return false;
  }

  out = next;
  error = "";
  return true;
}

bool parsePairRequestLine(
    const String& line,
    BuddyPairRequest& out,
    String& error) {
  JsonDocument doc;
  DeserializationError jsonError = deserializeJson(doc, line);
  if (jsonError) {
    error = jsonError.c_str();
    return false;
  }

  const char* type = doc["type"] | "";
  if (strcmp(type, "pair_request") != 0) {
    error = "not a pair_request";
    return false;
  }

  const char* code = doc["code"] | "";
  if (code[0] == '\0') {
    error = "pair code required";
    return false;
  }

  BuddyPairRequest next{};
  copyUtf8(next.code, sizeof(next.code), code);
  out = next;
  error = "";
  return true;
}

String buildButtonEventLine(const char* button, const char* action) {
  JsonDocument doc;
  doc["v"] = 0;
  doc["type"] = "button";
  doc["button"] = button;
  doc["action"] = action;

  String line;
  serializeJson(doc, line);
  line += '\n';
  return line;
}

String buildApprovalDecisionLine(const char* requestId, const char* decision) {
  JsonDocument doc;
  doc["v"] = 0;
  doc["type"] = "approval_decision";
  doc["id"] = requestId;
  doc["decision"] = decision;

  String line;
  serializeJson(doc, line);
  line += '\n';
  return line;
}

String buildWifiHelloLine(const char* token) {
  JsonDocument doc;
  doc["v"] = 0;
  doc["type"] = "hello";
  doc["source"] = "codex-buddy-cardputer";
  if (token != nullptr && token[0] != '\0') {
    doc["token"] = token;
  }

  String line;
  serializeJson(doc, line);
  line += '\n';
  return line;
}

String buildDeviceStatusLine(
    const char* status,
    BuddyState state,
    BuddyAnimation animation) {
  JsonDocument doc;
  doc["v"] = 0;
  doc["type"] = "device_status";
  doc["status"] = status;
  doc["state"] = buddyStateLabel(state);
  doc["animation"] = buddyAnimationLabel(animation);

  String line;
  serializeJson(doc, line);
  line += '\n';
  return line;
}

String buildErrorLine(const char* message) {
  JsonDocument doc;
  doc["v"] = 0;
  doc["type"] = "error";
  doc["message"] = message;

  String line;
  serializeJson(doc, line);
  line += '\n';
  return line;
}
