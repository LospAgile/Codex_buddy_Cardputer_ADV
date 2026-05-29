#pragma once

#include <Arduino.h>

class CodexBuddyBle {
 public:
  void begin(const char* deviceName);
  bool connected() const;
  bool pollLine(String& line);
  void sendLine(const String& line);
};

