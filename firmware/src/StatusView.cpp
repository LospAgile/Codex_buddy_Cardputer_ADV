#include "StatusView.h"

#include <M5Cardputer.h>
#include <pgmspace.h>
#include <string.h>

#include "CodexPetSprite.h"

namespace {

M5Canvas screenCanvas(&M5Cardputer.Display);
bool screenCanvasReady = false;

constexpr uint8_t kMenuCount = 7;
constexpr uint8_t kSettingsCount = 9;
constexpr uint8_t kWifiFieldCount = 6;
constexpr int kScreenWidth = 240;
constexpr int kScreenHeight = 135;
constexpr int kTopBarHeight = 15;
constexpr int kFooterHeight = 17;
constexpr int kFooterY = kScreenHeight - kFooterHeight;
constexpr int kMainY = kTopBarHeight;
constexpr int kMainHeight = kScreenHeight - kTopBarHeight - kFooterHeight;
constexpr int kPetX = 5;
constexpr int kPetY = 30;
constexpr int kTopTextY = 2;
constexpr int kMarqueeGapPx = 28;
constexpr uint32_t kMarqueeStepMs = 55;
constexpr uint16_t kHudBg = 0x0841;
constexpr uint16_t kPanelBg = 0x1082;
constexpr uint16_t kDimLine = 0x39E7;

struct PetSequence {
  const uint8_t* frames;
  const uint16_t* durations;
  uint8_t count;
};

bool isZh(const AppSettings& settings) {
  return settings.language == LanguageMode::ZhCn;
}

const char* textFor(const AppSettings& settings, const char* en, const char* zh) {
  return isZh(settings) ? zh : en;
}

template <typename Canvas>
void setUiFont(Canvas& canvas, const AppSettings& settings) {
  if (isZh(settings)) {
    canvas.setFont(&fonts::efontCN_12);
  } else {
    canvas.setFont(&fonts::Font0);
  }
  canvas.setTextSize(1);
  canvas.setTextDatum(top_left);
  canvas.setTextWrap(false);
}

uint8_t utf8Length(uint8_t first) {
  if ((first & 0xE0) == 0xC0) {
    return 2;
  }
  if ((first & 0xF0) == 0xE0) {
    return 3;
  }
  if ((first & 0xF8) == 0xF0) {
    return 4;
  }
  return 1;
}

template <typename Canvas>
void printUiText(Canvas& canvas, const char* text) {
  if (text == nullptr) {
    return;
  }
  canvas.print(text);
}

uint16_t stateColor(BuddyState state) {
  switch (state) {
    case BuddyState::Running:
      return TFT_CYAN;
    case BuddyState::Waiting:
      return TFT_ORANGE;
    case BuddyState::Review:
      return TFT_GREEN;
    case BuddyState::Failed:
      return TFT_RED;
    case BuddyState::Idle:
    default:
      return TFT_DARKGREY;
  }
}

PetSequence sequenceFor(BuddyAnimation animation) {
  switch (animation) {
    case BuddyAnimation::Running:
      return {kCodexPetRunningFrames, kCodexPetRunningDurations, 6};
    case BuddyAnimation::Waiting:
      return {kCodexPetWaitingFrames, kCodexPetWaitingDurations, 6};
    case BuddyAnimation::Waving:
      return {kCodexPetWavingFrames, kCodexPetWavingDurations, 4};
    case BuddyAnimation::Jumping:
      return {kCodexPetJumpingFrames, kCodexPetJumpingDurations, 5};
    case BuddyAnimation::Review:
      return {kCodexPetReviewFrames, kCodexPetReviewDurations, 6};
    case BuddyAnimation::Failed:
      return {kCodexPetFailedFrames, kCodexPetFailedDurations, 8};
    case BuddyAnimation::RunningRight:
      return {kCodexPetRunningRightFrames, kCodexPetRunningRightDurations, 8};
    case BuddyAnimation::RunningLeft:
      return {kCodexPetRunningLeftFrames, kCodexPetRunningLeftDurations, 8};
    case BuddyAnimation::Idle:
    default:
      return {kCodexPetIdleFrames, kCodexPetIdleDurations, 6};
  }
}

uint8_t selectFrameIndex(const PetSequence& sequence, uint32_t ageMs) {
  uint32_t totalMs = 0;
  for (uint8_t i = 0; i < sequence.count; ++i) {
    totalMs += pgm_read_word(&sequence.durations[i]);
  }
  if (totalMs == 0) {
    return pgm_read_byte(&sequence.frames[0]);
  }

  uint32_t cursor = ageMs % totalMs;
  for (uint8_t i = 0; i < sequence.count; ++i) {
    uint16_t duration = pgm_read_word(&sequence.durations[i]);
    if (cursor < duration) {
      return pgm_read_byte(&sequence.frames[i]);
    }
    cursor -= duration;
  }
  return pgm_read_byte(&sequence.frames[sequence.count - 1]);
}

template <typename Canvas>
void drawPetSprite(
    Canvas& canvas,
    int x,
    int y,
    BuddyAnimation animation,
    uint32_t ageMs) {
  PetSequence sequence = sequenceFor(animation);
  uint8_t frameIndex = selectFrameIndex(sequence, ageMs);
  const uint16_t* frame = kCodexPetFrames[frameIndex];
  canvas.fillRect(
      x,
      y,
      kCodexPetFrameWidth,
      kCodexPetFrameHeight,
      TFT_BLACK);
  canvas.pushImage(
      x,
      y,
      kCodexPetFrameWidth,
      kCodexPetFrameHeight,
      frame,
      kCodexPetTransparentColor);
}

template <typename Canvas>
void drawBootContent(Canvas& canvas, const char* message) {
  canvas.fillScreen(TFT_BLACK);
  canvas.setTextColor(TFT_WHITE, TFT_BLACK);
  canvas.setCursor(8, 8);
  canvas.println("Codex Buddy");
  canvas.setTextColor(TFT_CYAN, TFT_BLACK);
  canvas.setCursor(8, 28);
  canvas.println(message);
}

template <typename Canvas>
void drawPageHeader(Canvas& canvas, const char* title, uint16_t color) {
  canvas.fillScreen(TFT_BLACK);
  canvas.fillRect(0, 0, canvas.width(), kTopBarHeight, kHudBg);
  canvas.fillRect(0, 0, 3, kTopBarHeight, color);
  canvas.drawFastHLine(0, kTopBarHeight - 1, canvas.width(), kDimLine);
  canvas.setTextColor(color, kHudBg);
  canvas.setClipRect(6, 0, canvas.width() - 12, kTopBarHeight - 1);
  canvas.setCursor(6, kTopTextY);
  printUiText(canvas, title);
  canvas.clearClipRect();
}

template <typename Canvas>
void drawPageFooter(Canvas& canvas, const char* text) {
  canvas.drawFastHLine(0, kFooterY, canvas.width(), kDimLine);
  canvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
  canvas.setCursor(6, 122);
  printUiText(canvas, text);
}

template <typename Canvas>
void printClipped(Canvas& canvas, const char* text, size_t maxChars) {
  if (text == nullptr) {
    return;
  }
  size_t count = 0;
  while (*text != '\0' && count < maxChars) {
    const uint8_t first = static_cast<uint8_t>(*text);
    const size_t length = utf8Length(first);
    char buffer[5] = {};
    size_t copied = 0;
    while (copied < length && text[copied] != '\0') {
      buffer[copied] = text[copied];
      ++copied;
    }
    buffer[copied] = '\0';
    printUiText(canvas, buffer);
    text += copied;
    ++count;
  }
  if (*text != '\0') {
    canvas.print("...");
  }
}

template <typename Canvas>
void printClippedToWidth(Canvas& canvas, const char* text, int maxWidth) {
  if (text == nullptr || maxWidth <= 0) {
    return;
  }
  if (canvas.textWidth(text) <= maxWidth) {
    printUiText(canvas, text);
    return;
  }

  char buffer[96] = {};
  size_t used = 0;
  const char* cursor = text;
  while (*cursor != '\0' && used + 4 < sizeof(buffer)) {
    const size_t length = utf8Length(static_cast<uint8_t>(*cursor));
    char candidate[96] = {};
    memcpy(candidate, buffer, used);
    size_t copied = 0;
    while (copied < length && cursor[copied] != '\0' &&
           used + copied + 4 < sizeof(candidate)) {
      candidate[used + copied] = cursor[copied];
      ++copied;
    }
    candidate[used + copied] = '\0';
    strcat(candidate, "...");
    if (canvas.textWidth(candidate) > maxWidth) {
      break;
    }
    memcpy(buffer + used, cursor, copied);
    used += copied;
    buffer[used] = '\0';
    cursor += copied;
  }
  printUiText(canvas, buffer);
  canvas.print("...");
}

bool isAsciiPetLabel(const char* text) {
  if (text == nullptr || text[0] == '\0') {
    return false;
  }
  bool hasNameChar = false;
  for (const char* cursor = text; *cursor != '\0'; ++cursor) {
    const uint8_t c = static_cast<uint8_t>(*cursor);
    if (c < 0x20 || c >= 0x7f) {
      return false;
    }
    if ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
        (c >= '0' && c <= '9')) {
      hasNameChar = true;
    }
  }
  return hasNameChar;
}

const char* petDisplayName(const BuddyPet& pet) {
  if (isAsciiPetLabel(pet.displayName)) {
    return pet.displayName;
  }
  if (isAsciiPetLabel(pet.id)) {
    return pet.id;
  }
  return "Alice";
}

bool isAssistantEntry(const char* kind) {
  return kind != nullptr &&
         (strcmp(kind, "assistant") == 0 || strcmp(kind, "assist") == 0 ||
          strcmp(kind, "agent") == 0);
}

const char* entryKindLabel(const char* kind) {
  if (isAssistantEntry(kind)) {
    return "Agent";
  }
  return kind == nullptr || kind[0] == '\0' ? "-" : kind;
}

template <typename Canvas>
void drawMarqueeText(
    Canvas& canvas,
    const char* text,
    int x,
    int y,
    int w,
    int h,
    uint16_t fg,
    uint16_t bg) {
  canvas.fillRect(x, y, w, h, bg);
  canvas.setTextColor(fg, bg);
  if (text == nullptr || text[0] == '\0') {
    return;
  }

  canvas.setClipRect(x, y, w, h);
  const int textWidth = canvas.textWidth(text);
  if (textWidth <= w) {
    canvas.setCursor(x, y + 1);
    printUiText(canvas, text);
    canvas.clearClipRect();
    return;
  }

  const int cycle = textWidth + kMarqueeGapPx;
  const int offset = (millis() / kMarqueeStepMs) % cycle;
  int drawX = x - offset;
  canvas.setCursor(drawX, y + 1);
  printUiText(canvas, text);

  drawX += cycle;
  if (drawX < x + w) {
    canvas.setCursor(drawX, y + 1);
    printUiText(canvas, text);
  }
  canvas.clearClipRect();
}

template <typename Canvas>
void drawActivityEntry(Canvas& canvas, const BuddyEntry& entry, int y) {
  constexpr int kActivityX = 84;
  constexpr int kKindWidth = 42;
  constexpr int kTextX = kActivityX + kKindWidth + 8;
  constexpr int kTextWidth = kScreenWidth - kTextX - 6;
  canvas.fillRect(kActivityX, y, kScreenWidth - kActivityX - 6, 14, TFT_BLACK);

  canvas.setTextColor(TFT_CYAN, TFT_BLACK);
  canvas.setCursor(kActivityX, y);
  printClippedToWidth(canvas, entryKindLabel(entry.kind), kKindWidth);

  canvas.setTextColor(TFT_WHITE, TFT_BLACK);
  canvas.setCursor(kActivityX + kKindWidth, y);
  canvas.print(":");

  if (isAssistantEntry(entry.kind)) {
    drawMarqueeText(
        canvas, entry.text, kTextX, y, kTextWidth, 14, TFT_WHITE, TFT_BLACK);
    return;
  }

  canvas.setCursor(kTextX, y);
  printClippedToWidth(canvas, entry.text, kTextWidth);
}

template <typename Canvas>
void drawActionButton(
    Canvas& canvas,
    int x,
    int y,
    int w,
    int h,
    uint16_t bg,
    const char* label) {
  canvas.fillRect(x, y, w, h, bg);
  canvas.drawRect(x, y, w, h, bg == TFT_MAROON ? TFT_RED : TFT_GREEN);
  canvas.setTextColor(TFT_WHITE, bg);
  canvas.setClipRect(x + 2, y, w - 4, h);
  const int textWidth = canvas.textWidth(label);
  const int textX = x + max(3, (w - textWidth) / 2);
  canvas.setCursor(textX, y + (h > 15 ? 4 : 1));
  printUiText(canvas, label);
  canvas.clearClipRect();
}

const char* boolLabel(bool value, const AppSettings& settings) {
  if (isZh(settings)) {
    return value ? "开" : "关";
  }
  return value ? "on" : "off";
}

void formatDuration(char* out, size_t outSize, uint32_t ms) {
  if (outSize == 0) {
    return;
  }
  uint32_t seconds = ms / 1000;
  if (seconds < 60) {
    snprintf(out, outSize, "%lus", static_cast<unsigned long>(seconds));
    return;
  }
  uint32_t minutes = seconds / 60;
  if (minutes < 60) {
    snprintf(out,
             outSize,
             "%lum%02lus",
             static_cast<unsigned long>(minutes),
             static_cast<unsigned long>(seconds % 60));
    return;
  }
  snprintf(out,
           outSize,
           "%luh%02lum",
           static_cast<unsigned long>(minutes / 60),
           static_cast<unsigned long>(minutes % 60));
}

void formatHeap(char* out, size_t outSize, uint32_t bytes) {
  if (outSize == 0) {
    return;
  }
  snprintf(out,
           outSize,
           "%luk",
           static_cast<unsigned long>((bytes + 1023) / 1024));
}

void formatMilliVolts(char* out, size_t outSize, int16_t mv) {
  if (outSize == 0) {
    return;
  }
  if (mv <= 0) {
    snprintf(out, outSize, "-");
    return;
  }
  snprintf(out,
           outSize,
           "%d.%dV",
           static_cast<int>(mv / 1000),
           static_cast<int>((mv % 1000) / 100));
}

template <typename Canvas>
void drawLowBatterySafeContent(
    Canvas& canvas,
    const AppSettings& settings,
    int32_t batteryLevel,
    int16_t batteryMv,
    int16_t vbusMv) {
  setUiFont(canvas, settings);
  drawPageHeader(
      canvas,
      textFor(settings, "CODEX low power", "CODEX 低电量"),
      TFT_ORANGE);

  char battery[18] = {};
  char voltage[12] = {};
  char usb[12] = {};
  if (batteryLevel >= 0) {
    snprintf(
        battery,
        sizeof(battery),
        "%ld%%",
        static_cast<long>(batteryLevel));
  } else {
    strlcpy(battery, "-", sizeof(battery));
  }
  formatMilliVolts(voltage, sizeof(voltage), batteryMv);
  formatMilliVolts(usb, sizeof(usb), vbusMv);

  canvas.setTextColor(TFT_ORANGE, TFT_BLACK);
  canvas.setCursor(12, 28);
  printUiText(canvas, textFor(settings, "LOW BATTERY", "低电量"));

  canvas.setTextColor(TFT_WHITE, TFT_BLACK);
  canvas.setCursor(12, 48);
  printUiText(
      canvas,
      textFor(settings, "Plug in USB-C to continue", "请接入 USB-C 电源"));

  canvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  canvas.setCursor(12, 70);
  printUiText(canvas, textFor(settings, "Battery ", "电量 "));
  printUiText(canvas, battery);
  canvas.print("  ");
  printUiText(canvas, voltage);

  canvas.setCursor(12, 88);
  printUiText(canvas, "USB ");
  printUiText(canvas, usb);

  canvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
  canvas.setCursor(12, 110);
  printUiText(
      canvas,
      textFor(settings,
              "BLE/WiFi/LED/SFX paused",
              "无线/灯光/音效已暂停"));
}

void formatCompactNumber(char* out, size_t outSize, uint32_t value) {
  if (outSize == 0) {
    return;
  }
  if (value >= 1000000UL) {
    snprintf(out,
             outSize,
             "%lu.%lum",
             static_cast<unsigned long>(value / 1000000UL),
             static_cast<unsigned long>((value % 1000000UL) / 100000UL));
    return;
  }
  if (value >= 1000UL) {
    snprintf(out,
             outSize,
             "%lu.%luk",
             static_cast<unsigned long>(value / 1000UL),
             static_cast<unsigned long>((value % 1000UL) / 100UL));
    return;
  }
  snprintf(out, outSize, "%lu", static_cast<unsigned long>(value));
}

void formatSecondsCompact(char* out, size_t outSize, uint32_t seconds) {
  if (outSize == 0) {
    return;
  }
  if (seconds < 60) {
    snprintf(out, outSize, "%lus", static_cast<unsigned long>(seconds));
    return;
  }
  uint32_t minutes = seconds / 60UL;
  if (minutes < 60) {
    snprintf(out, outSize, "%lum", static_cast<unsigned long>(minutes));
    return;
  }
  snprintf(out,
           outSize,
           "%luh%02lum",
           static_cast<unsigned long>(minutes / 60UL),
           static_cast<unsigned long>(minutes % 60UL));
}

template <typename Canvas>
void drawTinyBar(
    Canvas& canvas,
    int x,
    int y,
    int w,
    uint8_t percent,
    uint16_t color,
    uint16_t bg) {
  canvas.drawRect(x, y, w, 5, TFT_DARKGREY);
  const int fillWidth = max(0, min(w - 2, (w - 2) * percent / 100));
  canvas.fillRect(x + 1, y + 1, fillWidth, 3, color);
  if (fillWidth < w - 2) {
    canvas.fillRect(x + 1 + fillWidth, y + 1, w - 2 - fillWidth, 3, bg);
  }
}

template <typename Canvas>
void drawInfoLine(
    Canvas& canvas,
    int labelX,
    int valueX,
    int y,
    const char* label,
    const char* value,
    int valueWidth,
    uint16_t valueColor = TFT_LIGHTGREY) {
  canvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
  canvas.setCursor(labelX, y);
  printUiText(canvas, label);
  canvas.setTextColor(valueColor, TFT_BLACK);
  canvas.setCursor(valueX, y);
  printClippedToWidth(canvas, value, valueWidth);
}

const char* menuLabel(uint8_t index, const AppSettings& settings) {
  switch (index) {
    case 0:
      return textFor(settings, "Status", "状态");
    case 1:
      return textFor(settings, "Approval", "审批");
    case 2:
      return textFor(settings, "Settings", "设置");
    case 3:
      return "WiFi";
    case 4:
      return textFor(settings, "Device", "设备");
    case 5:
      return textFor(settings, "Help", "帮助");
    case 6:
      return textFor(settings, "Sleep", "休眠");
    default:
      return "";
  }
}

const char* stateDisplayLabel(BuddyState state, const AppSettings& settings) {
  if (!isZh(settings)) {
    return buddyStateLabel(state);
  }
  switch (state) {
    case BuddyState::Running:
      return "运行";
    case BuddyState::Waiting:
      return "等待";
    case BuddyState::Review:
      return "审阅";
    case BuddyState::Failed:
      return "失败";
    case BuddyState::Idle:
    default:
      return "空闲";
  }
}

const char* animationDisplayLabel(
    BuddyAnimation animation,
    const AppSettings& settings) {
  if (!isZh(settings)) {
    return buddyAnimationLabel(animation);
  }
  switch (animation) {
    case BuddyAnimation::Running:
      return "运行";
    case BuddyAnimation::Waiting:
      return "等待";
    case BuddyAnimation::Waving:
      return "挥手";
    case BuddyAnimation::Jumping:
      return "跳跃";
    case BuddyAnimation::Review:
      return "审阅";
    case BuddyAnimation::Failed:
      return "失败";
    case BuddyAnimation::RunningRight:
      return "右行";
    case BuddyAnimation::RunningLeft:
      return "左行";
    case BuddyAnimation::Idle:
    default:
      return "待机";
  }
}

const char* hudTransportLabel(const DeviceInfo& info) {
  if (info.wifiTcpConnected) {
    return "WiFi";
  }
  if (info.bleConnected) {
    return "BLE";
  }
  if (info.wifiConnected) {
    return "WiFi?";
  }
  return "NO LINK";
}

uint16_t hudTransportColor(const DeviceInfo& info) {
  if (info.wifiTcpConnected) {
    return TFT_GREEN;
  }
  if (info.bleConnected) {
    return TFT_GREEN;
  }
  if (info.wifiConnected) {
    return TFT_ORANGE;
  }
  return TFT_RED;
}

const char* bleStatusLabel(const DeviceInfo& info, const AppSettings& settings) {
  if (info.bleConnected) {
    return textFor(settings, "connected", "已连");
  }
  return textFor(settings, "advertise", "广播");
}

template <typename Canvas>
void drawInlineApprovalPanel(
    Canvas& canvas,
    const BuddyApprovalRequest& request,
    const AppSettings& settings) {
  constexpr int x = 82;
  constexpr int y = 45;
  constexpr int w = 151;
  constexpr int h = 69;
  canvas.fillRect(x, y, w, h, kPanelBg);
  canvas.drawRect(x, y, w, h, TFT_GREEN);
  canvas.fillRect(x, y, 3, h, TFT_GREEN);
  canvas.setTextColor(TFT_GREEN, kPanelBg);
  canvas.setCursor(x + 8, y + 6);
  printUiText(canvas, textFor(settings, "APPROVAL", "审批"));

  canvas.setTextColor(TFT_CYAN, kPanelBg);
  canvas.setCursor(x + 8, y + 21);
  printUiText(canvas, textFor(settings, "tool ", "工具 "));
  printClipped(canvas, request.tool[0] ? request.tool : "-", 13);

  canvas.setTextColor(TFT_LIGHTGREY, kPanelBg);
  drawMarqueeText(
      canvas,
      request.hint[0] ? request.hint : request.id,
      x + 8,
      y + 35,
      w - 16,
      14,
      TFT_LIGHTGREY,
      kPanelBg);

  drawActionButton(
      canvas,
      x + 8,
      y + 52,
      61,
      14,
      TFT_DARKGREEN,
      textFor(settings, "Y allow", "Y 批准"));
  drawActionButton(
      canvas,
      x + w - 69,
      y + 52,
      61,
      14,
      TFT_MAROON,
      textFor(settings, "N deny", "N 拒绝"));
}

template <typename Canvas>
void drawPetStatsPanel(
    Canvas& canvas,
    const PetStatsInfo& stats,
    const AppSettings& settings) {
  constexpr int x = 82;
  constexpr int y = 45;
  constexpr int w = 151;
  constexpr int h = 69;
  canvas.fillRect(x, y, w, h, kPanelBg);
  canvas.drawRect(x, y, w, h, TFT_CYAN);
  canvas.fillRect(x, y, 3, h, TFT_CYAN);

  canvas.setTextColor(TFT_CYAN, kPanelBg);
  canvas.setCursor(x + 8, y + 6);
  printUiText(canvas, textFor(settings, "PET Stats", "宠物统计"));

  char totalTokens[12] = {};
  char todayTokens[12] = {};
  char nap[12] = {};
  char tokenSummary[28] = {};
  if (stats.hasTotalTokens) {
    formatCompactNumber(totalTokens, sizeof(totalTokens), stats.totalTokens);
  } else {
    strlcpy(totalTokens, "-", sizeof(totalTokens));
  }
  if (stats.hasTodayTokens) {
    formatCompactNumber(todayTokens, sizeof(todayTokens), stats.todayTokens);
  } else {
    strlcpy(todayTokens, "-", sizeof(todayTokens));
  }
  snprintf(tokenSummary,
           sizeof(tokenSummary),
           "T%s D%s",
           totalTokens,
           todayTokens);
  formatSecondsCompact(nap, sizeof(nap), stats.napSeconds);

  canvas.setTextColor(TFT_LIGHTGREY, kPanelBg);
  canvas.setCursor(x + 8, y + 21);
  printUiText(canvas, textFor(settings, "Mood ", "心情 "));
  canvas.printf("%u/5", stats.moodHearts);

  canvas.setCursor(x + 8, y + 34);
  printUiText(canvas, textFor(settings, "Fed", "饱腹"));
  drawTinyBar(canvas, x + 42, y + 38, 38, stats.fedPercent, TFT_GREEN, kPanelBg);

  canvas.setCursor(x + 8, y + 47);
  printUiText(canvas, textFor(settings, "Energy", "精力"));
  drawTinyBar(canvas, x + 42, y + 51, 38, stats.energyPercent, TFT_CYAN, kPanelBg);

  canvas.setTextColor(TFT_WHITE, kPanelBg);
  canvas.setCursor(x + 88, y + 21);
  canvas.printf("Lv %u", stats.level);
  canvas.setCursor(x + 88, y + 34);
  canvas.printf("A/D %lu/%lu",
                static_cast<unsigned long>(stats.approvals),
                static_cast<unsigned long>(stats.denials));
  canvas.setCursor(x + 88, y + 47);
  canvas.print("Nap ");
  printClippedToWidth(canvas, nap, 42);
  canvas.setCursor(x + 88, y + 60);
  printClippedToWidth(canvas, tokenSummary, 54);
}

template <typename Canvas>
void drawStatusContent(
    Canvas& canvas,
    const BuddyHeartbeat& heartbeat,
    const BuddyApprovalRequest& approvalRequest,
    const DeviceInfo& deviceInfo,
    const AppSettings& settings,
    const PetStatsInfo& petStats,
    bool petStatsMode) {
  canvas.fillScreen(TFT_BLACK);
  setUiFont(canvas, settings);

  uint16_t color =
      approvalRequest.active ? TFT_GREEN : stateColor(heartbeat.state);
  const char* label =
      approvalRequest.active
          ? textFor(settings, "approval", "审批")
          : stateDisplayLabel(heartbeat.state, settings);
  canvas.fillRect(0, 0, canvas.width(), kTopBarHeight, kHudBg);
  canvas.fillRect(0, 0, 3, kTopBarHeight, color);
  canvas.drawFastHLine(0, kTopBarHeight - 1, canvas.width(), kDimLine);
  canvas.setTextColor(color, kHudBg);
  canvas.setClipRect(7, 0, 158, kTopBarHeight - 1);
  canvas.setCursor(7, kTopTextY);
  canvas.print("CODEX ");
  printClippedToWidth(canvas, label, 112);
  canvas.clearClipRect();

  canvas.setTextColor(hudTransportColor(deviceInfo), kHudBg);
  canvas.setClipRect(176, 0, 58, kTopBarHeight - 1);
  canvas.setCursor(178, kTopTextY);
  printUiText(canvas, hudTransportLabel(deviceInfo));
  canvas.clearClipRect();

  drawPetSprite(canvas, kPetX, kPetY, heartbeat.animation, deviceInfo.uptimeMs);

  canvas.setTextColor(TFT_WHITE, TFT_BLACK);
  canvas.setCursor(84, 25);
  printUiText(canvas, textFor(settings, "Pet: ", "宠物: "));
  printClippedToWidth(canvas, petDisplayName(heartbeat.pet), 104);

  canvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  canvas.setCursor(84, 39);
  if (settings.summaryVisible) {
    printClipped(
        canvas,
        heartbeat.summary[0] ? heartbeat.summary : textFor(settings, "Waiting for Codex", "等待 Codex"),
        21);
  } else {
    printUiText(canvas, textFor(settings, "Summary hidden", "摘要已隐藏"));
  }

  if (approvalRequest.active) {
    drawInlineApprovalPanel(canvas, approvalRequest, settings);
  } else if (petStatsMode) {
    drawPetStatsPanel(canvas, petStats, settings);
  } else {
    const bool focusLayout = settings.homeLayout == HomeLayoutMode::Focus;
    canvas.setTextColor(color, TFT_BLACK);
    canvas.setCursor(84, 56);
    printUiText(canvas, focusLayout ? textFor(settings, "State: ", "状态: ") : textFor(settings, "Anim: ", "动作: "));
    printUiText(canvas, focusLayout ? stateDisplayLabel(heartbeat.state, settings) : animationDisplayLabel(heartbeat.animation, settings));

    if (focusLayout) {
      canvas.setTextColor(TFT_CYAN, TFT_BLACK);
      canvas.setCursor(84, 74);
      printUiText(canvas, textFor(settings, "Anim: ", "动作: "));
      printUiText(canvas, animationDisplayLabel(heartbeat.animation, settings));
      canvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
      canvas.setCursor(84, 92);
      printUiText(canvas, textFor(settings, "Trans: ", "传输: "));
      printClipped(canvas, deviceInfo.transport, 8);
    } else {
      int y = 74;
      const uint8_t visibleEntries = min<uint8_t>(heartbeat.entryCount, 2);
      const uint8_t startEntry = heartbeat.entryCount > visibleEntries
                                   ? heartbeat.entryCount - visibleEntries
                                   : 0;
      for (uint8_t i = 0; i < visibleEntries; ++i) {
        drawActivityEntry(canvas, heartbeat.entries[startEntry + i], y);
        y += 16;
      }
    }
  }

  canvas.drawFastHLine(0, kFooterY, canvas.width(), kDimLine);
  canvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
  canvas.setCursor(8, 122);
  if (approvalRequest.active) {
    printUiText(canvas, textFor(settings, "Y/Enter allow  N/Del deny", "Y/Enter批 N/Del拒"));
  } else if (petStatsMode) {
    printUiText(canvas, textFor(settings, "Del status", "Del状态"));
  } else if (heartbeat.hasTokens) {
    char tokens[12] = {};
    formatCompactNumber(tokens, sizeof(tokens), heartbeat.totalTokens);
    canvas.printf("Enter stats | tok %s", tokens);
  } else {
    canvas.printf(
        isZh(settings) ? "Enter统计 | %lus" : "Enter stats | %lus",
        static_cast<unsigned long>(deviceInfo.heartbeatAgeMs / 1000));
  }

  canvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
  canvas.setCursor(188, 122);
  printUiText(canvas, textFor(settings, "M menu", "M 菜单"));
}

template <typename Canvas>
void drawMenuContent(
    Canvas& canvas,
    uint8_t selectedIndex,
    const AppSettings& settings) {
  setUiFont(canvas, settings);
  drawPageHeader(canvas, textFor(settings, "CODEX menu", "CODEX 菜单"), TFT_CYAN);
  for (uint8_t i = 0; i < kMenuCount; ++i) {
    uint8_t col = i % 2;
    uint8_t row = i / 2;
    int x = col == 0 ? 10 : 124;
    int y = 28 + row * 21;
    bool selected = i == selectedIndex;
    uint16_t bg = selected ? kPanelBg : TFT_BLACK;
    uint16_t fg = selected ? TFT_WHITE : TFT_LIGHTGREY;
    canvas.fillRect(x - 2, y - 4, 106, 18, bg);
    if (selected) {
      canvas.drawRect(x - 2, y - 4, 106, 18, TFT_CYAN);
      canvas.fillRect(x - 2, y - 4, 3, 18, TFT_CYAN);
    }
    canvas.setTextColor(fg, bg);
    canvas.setCursor(x + 4, y);
    canvas.printf("%u  ", i + 1);
    printUiText(canvas, menuLabel(i, settings));
  }
  drawPageFooter(
      canvas,
      textFor(settings,
              "Fn/WASD move  Enter open  Del back",
              "W/S选 Enter开 Del退"));
}

template <typename Canvas>
void drawApprovalContent(
    Canvas& canvas,
    const BuddyApprovalRequest& request,
    const AppSettings& settings) {
  setUiFont(canvas, settings);
  drawPageHeader(
      canvas,
      textFor(settings, "CODEX approval", "CODEX 审批"),
      TFT_ORANGE);
  if (!request.active) {
    canvas.setTextColor(TFT_WHITE, TFT_BLACK);
    canvas.setCursor(12, 32);
    printUiText(canvas, textFor(settings, "No active request", "没有审批请求"));
    canvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
    canvas.setCursor(12, 52);
    printUiText(canvas, textFor(settings, "Ready for tool approval", "等待工具审批"));
    canvas.setCursor(12, 72);
    printUiText(canvas, textFor(settings, "Y/Enter approve", "Y/Enter 批准"));
    canvas.setCursor(12, 88);
    printUiText(canvas, textFor(settings, "N/Del deny", "N/Del 拒绝"));
    drawPageFooter(canvas, textFor(settings, "M menu  Del back", "M菜单 Del退"));
    return;
  }

  canvas.setTextColor(TFT_WHITE, TFT_BLACK);
  canvas.setCursor(12, 30);
  printUiText(canvas, textFor(settings, "Tool ", "工具 "));
  canvas.setTextColor(TFT_CYAN, TFT_BLACK);
  printClipped(canvas, request.tool[0] ? request.tool : "-", 24);

  canvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  canvas.setCursor(12, 48);
  canvas.print("ID   ");
  printClipped(canvas, request.id, 24);

  canvas.setTextColor(TFT_WHITE, TFT_BLACK);
  drawMarqueeText(
      canvas,
      request.hint[0]
          ? request.hint
          : textFor(settings, "Approve tool call?", "批准这个工具调用?"),
      12,
      66,
      216,
      16,
      TFT_WHITE,
      TFT_BLACK);

  drawActionButton(
      canvas,
      18,
      92,
      86,
      18,
      TFT_DARKGREEN,
      textFor(settings, "Y approve", "Y 批准"));

  drawActionButton(
      canvas,
      136,
      92,
      86,
      18,
      TFT_MAROON,
      textFor(settings, "N deny", "N 拒绝"));

  drawPageFooter(
      canvas,
      textFor(settings, "Enter approve  Del deny", "Enter批 Del拒"));
}

const char* settingsLabel(uint8_t index, const AppSettings& settings) {
  switch (index) {
    case 0:
      return textFor(settings, "Brightness", "亮度");
    case 1:
      return textFor(settings, "Language", "语言");
    case 2:
      return textFor(settings, "Sound", "声音");
    case 3:
      return "LED";
    case 4:
      return textFor(settings, "Auto sleep", "自动休眠");
    case 5:
      return textFor(settings, "Pet motion", "宠物动作");
    case 6:
      return textFor(settings, "Connection", "连接");
    case 7:
      return textFor(settings, "Summary", "摘要");
    case 8:
      return textFor(settings, "Home layout", "首页布局");
    default:
      return "";
  }
}

template <typename Canvas>
void printSettingValue(
    Canvas& canvas,
    const AppSettings& settings,
    uint8_t index) {
  switch (index) {
    case 0:
      canvas.printf("%u", settings.brightness);
      break;
    case 1:
      canvas.print(
          settings.language == LanguageMode::ZhCn ? "中文" : languageModeLabel(settings.language));
      break;
    case 2:
      canvas.print(boolLabel(settings.soundEnabled, settings));
      break;
    case 3:
      canvas.print(boolLabel(settings.ledEnabled, settings));
      break;
    case 4:
      if (settings.autoSleepSeconds == 0) {
        canvas.print("off");
      } else {
        canvas.printf("%us", settings.autoSleepSeconds);
      }
      break;
    case 5:
      canvas.print(boolLabel(settings.petMotionEnabled, settings));
      break;
    case 6:
      canvas.print(connectionModeLabel(settings.connectionMode));
      break;
    case 7:
      canvas.print(boolLabel(settings.summaryVisible, settings));
      break;
    case 8:
      canvas.print(
          settings.homeLayout == HomeLayoutMode::Focus
              ? textFor(settings, "focus", "聚焦")
              : textFor(settings, "detail", "详情"));
      break;
    default:
      break;
  }
}

template <typename Canvas>
void drawSettingsContent(
    Canvas& canvas,
    const AppSettings& settings,
    uint8_t selectedIndex) {
  setUiFont(canvas, settings);
  drawPageHeader(
      canvas,
      textFor(settings, "CODEX settings", "CODEX 设置"),
      TFT_GREEN);

  const uint8_t safeIndex =
      selectedIndex < kSettingsCount ? selectedIndex : 0;
  const uint8_t prevIndex =
      safeIndex == 0 ? kSettingsCount - 1 : safeIndex - 1;
  const uint8_t nextIndex =
      safeIndex + 1 >= kSettingsCount ? 0 : safeIndex + 1;

  canvas.fillRect(8, 25, 224, 43, kPanelBg);
  canvas.drawRect(8, 25, 224, 43, TFT_GREEN);
  canvas.fillRect(8, 25, 3, 43, TFT_GREEN);

  canvas.setTextColor(TFT_DARKGREY, kPanelBg);
  canvas.setCursor(18, 32);
  canvas.printf("%u/%u", safeIndex + 1, kSettingsCount);

  canvas.setTextColor(TFT_WHITE, kPanelBg);
  canvas.setCursor(58, 32);
  printClipped(canvas, settingsLabel(safeIndex, settings), 10);

  canvas.setTextColor(TFT_CYAN, kPanelBg);
  canvas.setCursor(18, 52);
  printUiText(canvas, textFor(settings, "Value ", "值 "));
  printSettingValue(canvas, settings, safeIndex);

  canvas.drawFastHLine(8, 77, 224, kDimLine);
  canvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
  canvas.setCursor(14, 87);
  printUiText(canvas, textFor(settings, "Prev ", "上项 "));
  printClipped(canvas, settingsLabel(prevIndex, settings), 7);

  canvas.setCursor(126, 87);
  printUiText(canvas, textFor(settings, "Next ", "下项 "));
  printClipped(canvas, settingsLabel(nextIndex, settings), 7);

  canvas.setTextColor(TFT_GREEN, TFT_BLACK);
  canvas.setCursor(14, 106);
  printUiText(canvas, textFor(settings, "W/S select", "W/S 选择"));
  canvas.setCursor(112, 106);
  printUiText(canvas, textFor(settings, "A/D change", "A/D 改值"));

  drawPageFooter(
      canvas,
      textFor(settings,
              "W/S select  A/D change  Del back",
              "W/S选 A/D改 Del退"));
}

const char* wifiFieldLabel(uint8_t index, const AppSettings& settings) {
  switch (index) {
    case 0:
      return "SSID";
    case 1:
      return textFor(settings, "Password", "密码");
    case 2:
      return "Host";
    case 3:
      return "Port";
    case 4:
      return "Token";
    case 5:
      return textFor(settings, "Connect", "连接");
    default:
      return "";
  }
}

template <typename Canvas>
void printEditableText(
    Canvas& canvas,
    const char* value,
    size_t cursor,
    size_t maxChars) {
  if (value == nullptr || value[0] == '\0') {
    canvas.print("|");
    return;
  }

  size_t count = 0;
  size_t byteIndex = 0;
  bool cursorPrinted = false;
  const char* text = value;
  while (*text != '\0' && count < maxChars) {
    if (!cursorPrinted && byteIndex >= cursor) {
      canvas.print("|");
      cursorPrinted = true;
    }
    const uint8_t first = static_cast<uint8_t>(*text);
    const size_t length = utf8Length(first);
    char buffer[5] = {};
    size_t copied = 0;
    while (copied < length && text[copied] != '\0') {
      buffer[copied] = text[copied];
      ++copied;
    }
    buffer[copied] = '\0';
    printUiText(canvas, buffer);
    text += copied;
    byteIndex += copied;
    ++count;
  }
  if (!cursorPrinted && byteIndex >= cursor) {
    canvas.print("|");
  }
  if (*text != '\0') {
    canvas.print("...");
  }
}

template <typename Canvas>
void printSecretMask(
    Canvas& canvas,
    const char* value,
    bool showLength,
    size_t cursor = 0,
    bool showCursor = false) {
  size_t length = value == nullptr ? 0 : strlen(value);
  if (length == 0) {
    canvas.print(showCursor ? "|" : "-");
    if (showLength) {
      if (showCursor) {
        canvas.print(" [0/0]");
      } else {
        canvas.print(" [0]");
      }
    }
    return;
  }
  if (cursor > length) {
    cursor = length;
  }
  const size_t maxVisible = showLength ? 8 : 10;
  size_t visible = length > maxVisible ? maxVisible : length;
  bool cursorPrinted = false;
  for (size_t i = 0; i < visible; ++i) {
    if (showCursor && !cursorPrinted && cursor <= i) {
      canvas.print("|");
      cursorPrinted = true;
    }
    canvas.print("*");
  }
  if (showCursor && !cursorPrinted && cursor <= visible) {
    canvas.print("|");
  }
  if (length > visible) {
    canvas.print("...");
  }
  if (showLength) {
    if (showCursor) {
      canvas.printf(
          " [%u/%u]",
          static_cast<unsigned>(cursor),
          static_cast<unsigned>(length));
    } else {
      canvas.printf(" [%u]", static_cast<unsigned>(length));
    }
  }
}

template <typename Canvas>
void printWifiFieldValue(
    Canvas& canvas,
    const WifiViewInfo& info,
    uint8_t index) {
  const bool editing = info.editing && info.focus == index;
  switch (index) {
    case 0:
      if (editing) {
        printEditableText(canvas, info.ssid, info.editCursor, 17);
      } else {
        printClipped(canvas, info.ssid[0] ? info.ssid : "-", 18);
      }
      if (info.networkCount > 0) {
        canvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
        canvas.print(" ");
        canvas.printf("%dd", info.networks[info.selectedNetwork].rssi);
      }
      break;
    case 1:
      printSecretMask(canvas, info.password, editing, info.editCursor, editing);
      break;
    case 2:
      if (editing) {
        printEditableText(canvas, info.host, info.editCursor, 19);
      } else {
        printClipped(canvas, info.host[0] ? info.host : "-", 20);
      }
      break;
    case 3:
      if (editing) {
        printEditableText(canvas, info.port, info.editCursor, 6);
      } else {
        canvas.print(info.port[0] ? info.port : "47392");
      }
      break;
    case 4:
      printSecretMask(canvas, info.token, editing, info.editCursor, editing);
      break;
    case 5:
      canvas.print(info.tcpConnected ? "online" : "start");
      break;
    default:
      break;
  }
}

template <typename Canvas>
void drawWifiContent(
    Canvas& canvas,
    const WifiViewInfo& info,
    const AppSettings& settings) {
  setUiFont(canvas, settings);
  drawPageHeader(canvas, "CODEX WiFi", TFT_CYAN);

  canvas.setTextColor(info.tcpConnected ? TFT_GREEN : TFT_LIGHTGREY, TFT_BLACK);
  canvas.setCursor(10, 24);
  if (info.tcpConnected) {
    canvas.print(textFor(settings, "TCP online ", "TCP 在线 "));
  } else if (info.wifiConnected) {
    canvas.print(textFor(settings, "WiFi online ", "WiFi 在线 "));
  } else {
    canvas.print(textFor(settings, "WiFi setup ", "WiFi 设置 "));
  }
  printClipped(canvas, info.status, 18);

  if (info.ip[0] != '\0') {
    canvas.setTextColor(TFT_DARKGREY, TFT_BLACK);
    canvas.setCursor(146, 24);
    if (info.rssi != 0) {
      canvas.printf("%dd", info.rssi);
    } else {
      printClipped(canvas, info.ip, 10);
    }
  }

  for (uint8_t i = 0; i < kWifiFieldCount; ++i) {
    int y = 39 + i * 13;
    bool selected = i == info.focus;
    uint16_t bg = selected ? TFT_DARKGREY : TFT_BLACK;
    uint16_t fg = selected ? TFT_WHITE : TFT_LIGHTGREY;
    if (selected) {
      canvas.fillRect(8, y - 1, 224, 12, bg);
    }
    canvas.setTextColor(fg, bg);
    canvas.setCursor(14, y);
    canvas.print(wifiFieldLabel(i, settings));
    canvas.setCursor(76, y);
    if (selected && info.editing && i < kWifiFieldCount - 1) {
      canvas.setTextColor(TFT_ORANGE, bg);
      canvas.print("> ");
    }
    printWifiFieldValue(canvas, info, i);
  }

  canvas.setTextColor(info.editing ? TFT_ORANGE : TFT_DARKGREY, TFT_BLACK);
  canvas.setCursor(8, 118);
  if (info.editing) {
    canvas.print(
        textFor(settings,
                "Fn </> move  Del delete",
                "Fn </>移 Del删"));
  } else {
    canvas.print(
        textFor(settings,
                "W/S move A/D net R scan C connect",
                "W/S选 A/D网 R扫 C连"));
  }
}

template <typename Canvas>
void drawDeviceContent(
    Canvas& canvas,
    const DeviceInfo& info,
    const BuddyHeartbeat& heartbeat,
    const AppSettings& settings,
    const PetStatsInfo& petStats) {
  setUiFont(canvas, settings);
  drawPageHeader(
      canvas,
      textFor(settings, "CODEX device", "CODEX 设备"),
      TFT_CYAN);

  char uptime[16] = {};
  char heartbeatAge[16] = {};
  char heap[12] = {};
  char battery[16] = {};
  char usb[12] = {};
  char rssi[12] = {};
  char host[80] = {};
  char petSummary[32] = {};
  formatDuration(uptime, sizeof(uptime), info.uptimeMs);
  formatDuration(heartbeatAge, sizeof(heartbeatAge), info.heartbeatAgeMs);
  formatHeap(heap, sizeof(heap), info.freeHeap);
  formatMilliVolts(usb, sizeof(usb), info.vbusMv);

  if (info.batteryLevel >= 0) {
    snprintf(battery,
             sizeof(battery),
             "%ld%%%s",
             static_cast<long>(info.batteryLevel),
             info.chargingKnown && info.charging ? "+" : "");
  } else {
    formatMilliVolts(battery, sizeof(battery), info.batteryMv);
  }

  if (info.wifiRssi != 0) {
    snprintf(rssi, sizeof(rssi), "%ldd", static_cast<long>(info.wifiRssi));
  } else {
    snprintf(rssi, sizeof(rssi), "-");
  }

  if (info.wifiHost[0]) {
    snprintf(host,
             sizeof(host),
             "%s:%u%s",
             info.wifiHost,
             info.wifiPort,
             info.wifiTokenConfigured ? " tok" : "");
  } else {
    snprintf(host, sizeof(host), "-");
  }

  snprintf(petSummary,
           sizeof(petSummary),
           "Lv%u A%lu D%lu",
           petStats.level,
           static_cast<unsigned long>(petStats.approvals),
           static_cast<unsigned long>(petStats.denials));

  drawInfoLine(
      canvas, 10, 34, 24, "FW", info.firmwareVersion, 196, TFT_WHITE);
  drawInfoLine(canvas,
               10,
               45,
               36,
               textFor(settings, "Bat", "电量"),
               battery,
               62,
               info.charging ? TFT_GREEN : TFT_LIGHTGREY);
  drawInfoLine(canvas,
               122,
               160,
               36,
               "USB",
               usb,
               68,
               info.vbusMv > 0 ? TFT_GREEN : TFT_DARKGREY);
  drawInfoLine(canvas,
               10,
               45,
               48,
               textFor(settings, "Up", "开机"),
               uptime,
               62);
  drawInfoLine(canvas,
               122,
               160,
               48,
               textFor(settings, "Last", "心跳"),
               heartbeatAge,
               68,
               info.heartbeatAgeMs > 30000 ? TFT_ORANGE : TFT_LIGHTGREY);
  drawInfoLine(canvas, 10, 45, 60, "Heap", heap, 62);
  drawInfoLine(canvas,
               122,
               160,
               60,
               textFor(settings, "Trans", "链路"),
               info.transport,
               68,
               info.wifiTcpConnected ? TFT_GREEN : TFT_CYAN);
  drawInfoLine(canvas,
               10,
               45,
               72,
               "BLE",
               bleStatusLabel(info, settings),
               62,
               info.bleConnected ? TFT_GREEN : TFT_DARKGREY);
  drawInfoLine(canvas,
               122,
               160,
               72,
               "WiFi",
               info.wifiStatus,
               68,
               info.wifiTcpConnected
                   ? TFT_GREEN
                   : (info.wifiConnected ? TFT_CYAN : TFT_LIGHTGREY));
  drawInfoLine(canvas,
               10,
               45,
               84,
               "IP",
               info.wifiIp[0] ? info.wifiIp : "-",
               62);
  drawInfoLine(canvas, 122, 160, 84, "RSSI", rssi, 68);
  drawInfoLine(canvas,
               10,
               45,
               96,
               textFor(settings, "Host", "主机"),
               host,
               62);
  drawInfoLine(canvas,
               122,
               160,
               96,
               "IMU",
               info.imuStatus,
               68,
               strcmp(info.imuStatus, "off") == 0 ? TFT_DARKGREY : TFT_CYAN);
  drawInfoLine(canvas,
               10,
               45,
               108,
               "PET",
               petSummary,
               62,
               TFT_CYAN);
  drawInfoLine(canvas,
               122,
               160,
               108,
               textFor(settings, "Pair", "配对"),
               info.blePairCode[0] ? info.blePairCode : "-",
               68,
               TFT_GREEN);
  drawPageFooter(canvas, textFor(settings, "M menu  Del back", "M菜单 Del退"));
}

template <typename Canvas>
void drawHelpContent(Canvas& canvas, const AppSettings& settings) {
  setUiFont(canvas, settings);
  drawPageHeader(
      canvas,
      textFor(settings, "CODEX help", "CODEX 帮助"),
      TFT_LIGHTGREY);
  canvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  canvas.setCursor(10, 25);
  canvas.print(textFor(settings, "M menu      Enter stats/open", "M菜单      Enter统计/开"));
  canvas.setCursor(10, 41);
  canvas.print(textFor(settings, "Y approve   N deny", "Y批准      N拒绝"));
  canvas.setCursor(10, 57);
  canvas.print(textFor(settings, "Del back    W/S move", "Del退      W/S选"));
  canvas.setCursor(10, 73);
  canvas.print(textFor(settings, "Fn+;/Fn+.   up/down", "Fn+;/Fn+.  上/下"));
  canvas.setCursor(10, 89);
  canvas.print(textFor(settings, "Fn+,/Fn+/   left/right", "Fn+,/Fn+/  左/右"));
  canvas.setCursor(10, 105);
  canvas.print(textFor(settings, "R scan      C connect", "R扫描      C连接"));
}

template <typename Canvas>
void drawSleepContent(
    Canvas& canvas,
    const AppSettings& settings,
    const DeviceInfo& info) {
  setUiFont(canvas, settings);
  drawPageHeader(
      canvas,
      textFor(settings, "CODEX sleep", "CODEX 休眠"),
      TFT_DARKGREY);
  canvas.setTextColor(TFT_LIGHTGREY, TFT_BLACK);
  canvas.setCursor(12, 30);
  canvas.print(textFor(settings, "Display rest page", "屏幕休眠页面"));
  canvas.setCursor(12, 50);
  canvas.print(textFor(settings, "Auto sleep ", "自动休眠 "));
  if (settings.autoSleepSeconds == 0) {
    canvas.print("off");
  } else {
    canvas.printf("%us", settings.autoSleepSeconds);
  }
  canvas.setCursor(12, 70);
  canvas.printf(isZh(settings) ? "更新 %lus" : "Last update %lus",
                static_cast<unsigned long>(info.heartbeatAgeMs / 1000));
  canvas.setCursor(12, 90);
  canvas.print(textFor(settings, "Approval keeps screen on", "审批时保持亮屏"));
  drawPageFooter(
      canvas,
      textFor(settings, "Enter sleep  Del back", "Enter睡 Del退"));
}

void pushCanvas() {
  M5Cardputer.Display.startWrite();
  screenCanvas.pushSprite(0, 0);
  M5Cardputer.Display.endWrite();
}

}  // namespace

void StatusView::begin() {
  M5Cardputer.Display.setRotation(1);
  M5Cardputer.Display.setTextWrap(false);
  M5Cardputer.Display.setTextDatum(top_left);
  M5Cardputer.Display.setTextSize(1);

  screenCanvas.setColorDepth(16);
  screenCanvasReady = screenCanvas.createSprite(
      M5Cardputer.Display.width(),
      M5Cardputer.Display.height()) != nullptr;
  if (screenCanvasReady) {
    screenCanvas.setTextWrap(false);
    screenCanvas.setTextDatum(top_left);
    screenCanvas.setTextSize(1);
  }
}

void StatusView::drawBoot(const char* message) {
  if (screenCanvasReady) {
    drawBootContent(screenCanvas, message);
    pushCanvas();
    return;
  }

  drawBootContent(M5Cardputer.Display, message);
}

void StatusView::drawLowBatterySafeBoot(
    const AppSettings& settings,
    int32_t batteryLevel,
    int16_t batteryMv,
    int16_t vbusMv) {
  if (screenCanvasReady) {
    drawLowBatterySafeContent(
        screenCanvas,
        settings,
        batteryLevel,
        batteryMv,
        vbusMv);
    pushCanvas();
    return;
  }

  drawLowBatterySafeContent(
      M5Cardputer.Display,
      settings,
      batteryLevel,
      batteryMv,
      vbusMv);
}

void StatusView::draw(
    const BuddyHeartbeat& heartbeat,
    const BuddyApprovalRequest& approvalRequest,
    ViewMode mode,
    const AppSettings& settings,
    const DeviceInfo& deviceInfo,
    const WifiViewInfo& wifiInfo,
    const PetStatsInfo& petStats,
    bool petStatsMode,
    uint8_t menuIndex,
    uint8_t settingsIndex) {
  if (screenCanvasReady) {
    switch (mode) {
      case ViewMode::Menu:
        drawMenuContent(screenCanvas, menuIndex, settings);
        break;
      case ViewMode::Approval:
        drawApprovalContent(screenCanvas, approvalRequest, settings);
        break;
      case ViewMode::Settings:
        drawSettingsContent(screenCanvas, settings, settingsIndex);
        break;
      case ViewMode::Wifi:
        drawWifiContent(screenCanvas, wifiInfo, settings);
        break;
      case ViewMode::Device:
        drawDeviceContent(screenCanvas, deviceInfo, heartbeat, settings, petStats);
        break;
      case ViewMode::Help:
        drawHelpContent(screenCanvas, settings);
        break;
      case ViewMode::Sleep:
        drawSleepContent(screenCanvas, settings, deviceInfo);
        break;
      case ViewMode::Status:
      default:
        drawStatusContent(
            screenCanvas,
            heartbeat,
            approvalRequest,
            deviceInfo,
            settings,
            petStats,
            petStatsMode);
        break;
    }
    pushCanvas();
    return;
  }

  switch (mode) {
    case ViewMode::Menu:
      drawMenuContent(M5Cardputer.Display, menuIndex, settings);
      break;
    case ViewMode::Approval:
      drawApprovalContent(M5Cardputer.Display, approvalRequest, settings);
      break;
    case ViewMode::Settings:
      drawSettingsContent(M5Cardputer.Display, settings, settingsIndex);
      break;
    case ViewMode::Wifi:
      drawWifiContent(M5Cardputer.Display, wifiInfo, settings);
      break;
    case ViewMode::Device:
      drawDeviceContent(
          M5Cardputer.Display,
          deviceInfo,
          heartbeat,
          settings,
          petStats);
      break;
    case ViewMode::Help:
      drawHelpContent(M5Cardputer.Display, settings);
      break;
    case ViewMode::Sleep:
      drawSleepContent(M5Cardputer.Display, settings, deviceInfo);
      break;
    case ViewMode::Status:
    default:
      drawStatusContent(
          M5Cardputer.Display,
          heartbeat,
          approvalRequest,
          deviceInfo,
          settings,
          petStats,
          petStatsMode);
      break;
  }
}
