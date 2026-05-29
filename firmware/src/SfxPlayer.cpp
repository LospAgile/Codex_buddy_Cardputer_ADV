#include "SfxPlayer.h"

#include <M5Cardputer.h>

namespace {

constexpr uint8_t kSfxVolume = 72;

using Note = SfxPlayer::Note;

constexpr Note kNavBlip[] = {
    {880, 22},
};

constexpr Note kConfirmArpeggio[] = {
    {660, 38},
    {0, 12},
    {880, 42},
    {0, 12},
    {1320, 50},
};

constexpr Note kApproveChord[] = {
    {784, 45},
    {988, 45},
    {1319, 80},
};

constexpr Note kApprovalAlert[] = {
    {1175, 68},
    {1568, 68},
    {2093, 84},
    {0, 54},
    {1568, 70},
};

constexpr Note kBack[] = {
    {660, 30},
    {440, 50},
};

constexpr Note kDeny[] = {
    {330, 80},
    {247, 118},
};

constexpr Note kSaveFanfare[] = {
    {988, 42},
    {1175, 44},
    {1568, 82},
};

constexpr Note kMenu[] = {
    {740, 34},
    {932, 36},
};

constexpr Note kWarn[] = {
    {494, 58},
    {0, 32},
    {494, 58},
};

constexpr Note kWarn2[] = {
    {392, 82},
    {330, 86},
    {262, 116},
};

struct Sequence {
  const Note* notes;
  uint8_t count;
};

template <size_t N>
constexpr Sequence makeSequence(const Note (&notes)[N]) {
  return {notes, static_cast<uint8_t>(N)};
}

Sequence sequenceFor(SfxEvent event) {
  switch (event) {
    case SfxEvent::NavBlip:
      return makeSequence(kNavBlip);
    case SfxEvent::ConfirmArpeggio:
      return makeSequence(kConfirmArpeggio);
    case SfxEvent::ApproveChord:
      return makeSequence(kApproveChord);
    case SfxEvent::ApprovalAlert:
      return makeSequence(kApprovalAlert);
    case SfxEvent::Back:
      return makeSequence(kBack);
    case SfxEvent::Deny:
      return makeSequence(kDeny);
    case SfxEvent::SaveFanfare:
      return makeSequence(kSaveFanfare);
    case SfxEvent::Menu:
      return makeSequence(kMenu);
    case SfxEvent::Warn:
      return makeSequence(kWarn);
    case SfxEvent::Warn2:
      return makeSequence(kWarn2);
    default:
      return {nullptr, 0};
  }
}

}  // namespace

void SfxPlayer::begin(bool enabled) {
  M5Cardputer.Speaker.begin();
  enabled_ = !enabled;
  setEnabled(enabled);
}

void SfxPlayer::setEnabled(bool enabled) {
  if (enabled_ == enabled) {
    return;
  }
  enabled_ = enabled;
  M5Cardputer.Speaker.setVolume(enabled_ ? kSfxVolume : 0);
  if (!enabled_) {
    stop();
  }
}

void SfxPlayer::play(SfxEvent event) {
  if (!enabled_) {
    return;
  }
  Sequence sequence = sequenceFor(event);
  if (sequence.notes == nullptr || sequence.count == 0) {
    return;
  }
  sequence_ = sequence.notes;
  count_ = sequence.count;
  index_ = 0;
  startCurrent(millis());
}

void SfxPlayer::update(uint32_t now) {
  if (!enabled_ || sequence_ == nullptr) {
    return;
  }
  if (static_cast<int32_t>(now - noteUntilMs_) < 0) {
    return;
  }
  ++index_;
  if (index_ >= count_) {
    stop();
    return;
  }
  startCurrent(now);
}

void SfxPlayer::stop() {
  M5Cardputer.Speaker.stop();
  sequence_ = nullptr;
  count_ = 0;
  index_ = 0;
  noteUntilMs_ = 0;
}

void SfxPlayer::startCurrent(uint32_t now) {
  if (sequence_ == nullptr || index_ >= count_) {
    stop();
    return;
  }

  const Note& note = sequence_[index_];
  noteUntilMs_ = now + note.durationMs;
  if (note.frequency == 0) {
    M5Cardputer.Speaker.stop();
    return;
  }
  M5Cardputer.Speaker.tone(
      static_cast<float>(note.frequency),
      note.durationMs);
}
