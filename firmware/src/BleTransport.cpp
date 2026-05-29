#include "BleTransport.h"

#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

#include <string>

namespace {

constexpr char kServiceUuid[] = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
constexpr char kRxUuid[] = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";
constexpr char kTxUuid[] = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";
constexpr size_t kMaxRxLineBytes = 8192;
constexpr uint8_t kRxLineCapacity = 4;

BLECharacteristic* txCharacteristic = nullptr;
bool isConnected = false;
String rxBuffer;
String rxLines[kRxLineCapacity];
uint8_t rxHead = 0;
uint8_t rxTail = 0;
uint8_t rxCount = 0;
SemaphoreHandle_t rxMutex = nullptr;

bool lockRx() {
  return rxMutex == nullptr ||
         xSemaphoreTake(rxMutex, pdMS_TO_TICKS(20)) == pdTRUE;
}

void unlockRx() {
  if (rxMutex != nullptr) {
    xSemaphoreGive(rxMutex);
  }
}

void queueLineLocked(const String& line) {
  if (rxCount >= kRxLineCapacity) {
    rxHead = (rxHead + 1) % kRxLineCapacity;
    --rxCount;
  }
  rxLines[rxTail] = line;
  rxTail = (rxTail + 1) % kRxLineCapacity;
  ++rxCount;
}

void appendCharLocked(char c) {
  if (c == '\n' || c == '\r') {
    if (rxBuffer.length() > 0) {
      queueLineLocked(rxBuffer);
      rxBuffer = "";
    }
    return;
  }

  if (rxBuffer.length() >= kMaxRxLineBytes) {
    rxBuffer = "";
    return;
  }
  rxBuffer += c;
}

void appendIncoming(const std::string& value) {
  if (!lockRx()) {
    return;
  }
  for (char c : value) {
    appendCharLocked(c);
  }
  unlockRx();
}

void appendIncoming(const String& value) {
  if (!lockRx()) {
    return;
  }
  for (size_t i = 0; i < value.length(); ++i) {
    appendCharLocked(value[i]);
  }
  unlockRx();
}

class ServerCallbacks final : public BLEServerCallbacks {
  void onConnect(BLEServer*) override {
    isConnected = true;
  }

  void onDisconnect(BLEServer* server) override {
    isConnected = false;
    server->startAdvertising();
  }
};

class RxCallbacks final : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* characteristic) override {
    appendIncoming(characteristic->getValue());
  }
};

}  // namespace

void CodexBuddyBle::begin(const char* deviceName) {
  if (rxMutex == nullptr) {
    rxMutex = xSemaphoreCreateMutex();
  }
  BLEDevice::init(deviceName);
  BLEServer* server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  BLEService* service = server->createService(kServiceUuid);
  txCharacteristic = service->createCharacteristic(
      kTxUuid, BLECharacteristic::PROPERTY_NOTIFY);
  txCharacteristic->addDescriptor(new BLE2902());

  BLECharacteristic* rxCharacteristic = service->createCharacteristic(
      kRxUuid, BLECharacteristic::PROPERTY_WRITE |
                   BLECharacteristic::PROPERTY_WRITE_NR);
  rxCharacteristic->setCallbacks(new RxCallbacks());

  service->start();
  BLEAdvertising* advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(kServiceUuid);
  advertising->setScanResponse(true);
  advertising->start();
}

bool CodexBuddyBle::connected() const {
  return isConnected;
}

bool CodexBuddyBle::pollLine(String& line) {
  if (!lockRx()) {
    return false;
  }
  if (rxCount == 0) {
    unlockRx();
    return false;
  }
  line = rxLines[rxHead];
  rxLines[rxHead] = "";
  rxHead = (rxHead + 1) % kRxLineCapacity;
  --rxCount;
  unlockRx();
  return true;
}

void CodexBuddyBle::sendLine(const String& line) {
  if (!isConnected || txCharacteristic == nullptr) {
    return;
  }
  txCharacteristic->setValue(line.c_str());
  txCharacteristic->notify();
}
