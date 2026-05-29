#pragma once

#include <stdint.h>

enum class KeyAction : uint8_t {
  Up,
  Down,
  Left,
  Right,
  Select,
  Back,
  Menu,
  Approve,
  Deny,
  Refresh,
  Connect,
  Shortcut1,
  Shortcut2,
  Shortcut3,
  Shortcut4,
  Shortcut5,
  Shortcut6,
  Shortcut7,
};

bool isFnLayerActionChar(char c);
bool fnLayerActionForChar(char c, KeyAction* action);
bool hidKeyAction(uint8_t hid, KeyAction* action);
bool wordKeyAction(char c, KeyAction* action);
