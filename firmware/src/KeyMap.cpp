#include "KeyMap.h"

namespace {

constexpr uint8_t kHidArrowRight = 0x4F;
constexpr uint8_t kHidArrowLeft = 0x50;
constexpr uint8_t kHidArrowDown = 0x51;
constexpr uint8_t kHidArrowUp = 0x52;

bool setAction(KeyAction* out, KeyAction action) {
  if (out == nullptr) {
    return false;
  }
  *out = action;
  return true;
}

}  // namespace

bool isFnLayerActionChar(char c) {
  switch (c) {
    case ';':
    case ':':
    case ',':
    case '<':
    case '.':
    case '>':
    case '/':
    case '?':
    case '\\':
    case '|':
    case '`':
    case '~':
      return true;
    default:
      return false;
  }
}

bool fnLayerActionForChar(char c, KeyAction* action) {
  switch (c) {
    case ';':
    case ':':
      return setAction(action, KeyAction::Up);
    case ',':
    case '<':
      return setAction(action, KeyAction::Left);
    case '.':
    case '>':
      return setAction(action, KeyAction::Down);
    case '/':
    case '?':
      return setAction(action, KeyAction::Right);
    case '\\':
    case '|':
    case '`':
    case '~':
      return setAction(action, KeyAction::Back);
    default:
      return false;
  }
}

bool hidKeyAction(uint8_t hid, KeyAction* action) {
  switch (hid & 0x7F) {
    case kHidArrowUp:
      return setAction(action, KeyAction::Up);
    case kHidArrowDown:
      return setAction(action, KeyAction::Down);
    case kHidArrowLeft:
      return setAction(action, KeyAction::Left);
    case kHidArrowRight:
      return setAction(action, KeyAction::Right);
    default:
      return false;
  }
}

bool wordKeyAction(char c, KeyAction* action) {
  switch (c) {
    case 'w':
    case 'W':
    case 'k':
    case 'K':
    case '[':
    case '{':
    case ';':
    case ':':
      return setAction(action, KeyAction::Up);
    case 's':
    case 'S':
    case 'j':
    case 'J':
    case ']':
    case '}':
    case '.':
    case '>':
      return setAction(action, KeyAction::Down);
    case 'a':
    case 'A':
    case 'h':
    case 'H':
    case ',':
    case '<':
      return setAction(action, KeyAction::Left);
    case 'd':
    case 'D':
    case 'l':
    case 'L':
    case '/':
    case '?':
      return setAction(action, KeyAction::Right);
    case 'm':
    case 'M':
      return setAction(action, KeyAction::Menu);
    case 'r':
    case 'R':
      return setAction(action, KeyAction::Refresh);
    case 'c':
    case 'C':
      return setAction(action, KeyAction::Connect);
    case 'y':
    case 'Y':
      return setAction(action, KeyAction::Approve);
    case 'n':
    case 'N':
      return setAction(action, KeyAction::Deny);
    case '1':
      return setAction(action, KeyAction::Shortcut1);
    case '2':
      return setAction(action, KeyAction::Shortcut2);
    case '3':
      return setAction(action, KeyAction::Shortcut3);
    case '4':
      return setAction(action, KeyAction::Shortcut4);
    case '5':
      return setAction(action, KeyAction::Shortcut5);
    case '6':
      return setAction(action, KeyAction::Shortcut6);
    case '7':
      return setAction(action, KeyAction::Shortcut7);
    case 27:
      return setAction(action, KeyAction::Back);
    default:
      return false;
  }
}
