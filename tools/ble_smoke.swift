import CoreBluetooth
import Foundation
import AppKit
import Network

private let serviceUUID = CBUUID(string: "6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
private let rxUUID = CBUUID(string: "6E400002-B5A3-F393-E0A9-E50E24DCCA9E")
private let txUUID = CBUUID(string: "6E400003-B5A3-F393-E0A9-E50E24DCCA9E")
private let logURL = URL(fileURLWithPath: "/tmp/codex-buddy-ble-bridge.log")

func emit(_ message: String) {
    print(message)
    let line = message + "\n"
    guard let data = line.data(using: .utf8) else {
        return
    }
    if FileManager.default.fileExists(atPath: logURL.path),
       let handle = try? FileHandle(forWritingTo: logURL) {
        handle.seekToEndOfFile()
        handle.write(data)
        try? handle.close()
    } else {
        try? data.write(to: logURL)
    }
}

final class LineServer {
    private let listener: NWListener
    private let queue = DispatchQueue(label: "codex-buddy-ble-socket")
    private let onLine: (String, @escaping (String) -> Void) -> Void

    init(port: UInt16, onLine: @escaping (String, @escaping (String) -> Void) -> Void) throws {
        guard let endpointPort = NWEndpoint.Port(rawValue: port) else {
            throw NSError(domain: "CodexBuddyBLE", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "invalid port \(port)"
            ])
        }
        self.onLine = onLine
        self.listener = try NWListener(using: .tcp, on: endpointPort)
        self.listener.newConnectionHandler = { [weak self] connection in
            self?.handle(connection)
        }
        self.listener.stateUpdateHandler = { state in
            emit("socket state \(state)")
        }
        self.listener.start(queue: queue)
        emit("socket listening 127.0.0.1:\(port)")
    }

    private func handle(_ connection: NWConnection) {
        var buffer = Data()
        connection.start(queue: queue)

        func receiveNext() {
            connection.receive(minimumIncompleteLength: 1, maximumLength: 4096) {
                [weak self] data, _, isComplete, error in
                if let data, !data.isEmpty {
                    buffer.append(data)
                    if let newline = buffer.firstIndex(of: 0x0A) {
                        let lineData = buffer[..<newline]
                        let line = String(decoding: lineData, as: UTF8.self)
                        self?.onLine(line) { response in
                            let payload = Data((response + "\n").utf8)
                            connection.send(content: payload, completion: .contentProcessed { _ in
                                connection.cancel()
                            })
                        }
                        return
                    }
                }
                if isComplete || error != nil {
                    connection.cancel()
                    return
                }
                receiveNext()
            }
        }

        receiveNext()
    }
}

private struct BleRequest {
    let data: Data
    let expectedType: String?
    let timeout: TimeInterval
    let reply: (String) -> Void
}

final class BleBridge: NSObject, CBCentralManagerDelegate, CBPeripheralDelegate {
    private var central: CBCentralManager!
    private let centralQueue = DispatchQueue(label: "codex-buddy-ble-central")
    private var peripheral: CBPeripheral?
    private var rxCharacteristic: CBCharacteristic?
    private var txBuffer = Data()
    private var pendingWrite = Data()
    private var requestQueue: [BleRequest] = []
    private var activeRequest: BleRequest?
    private var activeTimer: DispatchSourceTimer?
    private let onceLine: String?
    private let requestTimeout: TimeInterval
    private let deviceName: String
    private let pairCode: String
    private let chunkSize = 20
    private var isReady = false
    private var onceCompleted = false
    private var server: LineServer?

    init(
        onceLine: String?,
        serverPort: UInt16?,
        requestTimeout: TimeInterval,
        deviceName: String,
        pairCode: String
    ) {
        self.onceLine = onceLine
        self.requestTimeout = max(1, requestTimeout)
        self.deviceName = deviceName
        self.pairCode = pairCode
        super.init()
        emit("central init")
        central = CBCentralManager(delegate: self, queue: centralQueue)
        emit("central created")

        if let serverPort {
            do {
                server = try LineServer(port: serverPort) { [weak self] line, reply in
                    self?.send(line: line, reply: reply)
                }
            } catch {
                fail("socket server failed: \(error.localizedDescription)")
            }
        }
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        guard central.state == .poweredOn else {
            emit("Bluetooth is not powered on: \(central.state.rawValue)")
            return
        }
        emit("scan start")
        central.scanForPeripherals(withServices: [serviceUUID], options: [
            CBCentralManagerScanOptionAllowDuplicatesKey: false
        ])
    }

    func centralManager(
        _ central: CBCentralManager,
        didDiscover peripheral: CBPeripheral,
        advertisementData: [String: Any],
        rssi RSSI: NSNumber
    ) {
        let localName = advertisementData[CBAdvertisementDataLocalNameKey] as? String
        let name = peripheral.name ?? localName ?? ""
        guard isSupportedDeviceName(name) else {
            if !name.isEmpty {
                emit("ignored \(name) rssi \(RSSI)")
            }
            return
        }

        emit("found \(name.isEmpty ? peripheral.identifier.uuidString : name) rssi \(RSSI)")
        self.peripheral = peripheral
        central.stopScan()
        peripheral.delegate = self
        central.connect(peripheral)
    }

    private func isSupportedDeviceName(_ name: String) -> Bool {
        let normalized = name.trimmingCharacters(in: .whitespacesAndNewlines)
        return normalized == deviceName
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        emit("connected")
        peripheral.discoverServices([serviceUUID])
    }

    func centralManager(
        _ central: CBCentralManager,
        didDisconnectPeripheral peripheral: CBPeripheral,
        error: Error?
    ) {
        emit("disconnected \(error?.localizedDescription ?? "")")
        self.peripheral = nil
        self.rxCharacteristic = nil
        self.isReady = false
        failActiveAndQueued("ble disconnected")
        self.pendingWrite.removeAll()
        central.scanForPeripherals(withServices: [serviceUUID], options: [
            CBCentralManagerScanOptionAllowDuplicatesKey: false
        ])
    }

    func centralManager(
        _ central: CBCentralManager,
        didFailToConnect peripheral: CBPeripheral,
        error: Error?
    ) {
        fail("connect failed: \(error?.localizedDescription ?? "unknown")")
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        if let error {
            fail("discover services failed: \(error.localizedDescription)")
        }
        guard let service = peripheral.services?.first(where: { $0.uuid == serviceUUID }) else {
            fail("NUS service not found")
        }
        peripheral.discoverCharacteristics([rxUUID, txUUID], for: service)
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didDiscoverCharacteristicsFor service: CBService,
        error: Error?
    ) {
        if let error {
            fail("discover characteristics failed: \(error.localizedDescription)")
        }
        for characteristic in service.characteristics ?? [] {
            if characteristic.uuid == rxUUID {
                rxCharacteristic = characteristic
            } else if characteristic.uuid == txUUID {
                peripheral.setNotifyValue(true, for: characteristic)
            }
        }
        if service.characteristics?.contains(where: { $0.uuid == txUUID }) != true {
            fail("TX notify characteristic not found")
        }
        if rxCharacteristic == nil {
            fail("RX write characteristic not found")
        }
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateNotificationStateFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if let error {
            fail("subscribe failed: \(error.localizedDescription)")
        }
        guard characteristic.uuid == txUUID, characteristic.isNotifying else {
            return
        }
        emit("subscribed")
        isReady = true
        if let onceLine, !onceCompleted {
            sendOnceAfterPair(line: onceLine) { response in
                emit(response)
                if response.contains(#""type":"device_status""#) {
                    self.onceCompleted = true
                    exit(0)
                }
                if response.contains(#""type":"error""#) {
                    self.onceCompleted = true
                    fputs(response + "\n", stderr)
                    exit(1)
                }
            }
        }
        drainWrites()
    }

    private func sendOnceAfterPair(line: String, reply: @escaping (String) -> Void) {
        let code = pairCode.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !code.isEmpty else {
            send(line: line, reply: reply)
            return
        }
        let escaped = code
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        send(line: #"{"v":0,"type":"pair_request","code":"\#(escaped)"}"#) {
            response in
            if response.contains(#""type":"error""#) ||
               !response.contains(#""status":"pair_ok""#) {
                reply(response)
                return
            }
            self.send(line: line, reply: reply)
        }
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didWriteValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if let error {
            fail("write failed: \(error.localizedDescription)")
        }
        writeNextChunk()
    }

    func peripheral(
        _ peripheral: CBPeripheral,
        didUpdateValueFor characteristic: CBCharacteristic,
        error: Error?
    ) {
        if let error {
            fail("notify failed: \(error.localizedDescription)")
        }
        guard let value = characteristic.value else {
            return
        }
        txBuffer.append(value)
        while let newline = txBuffer.firstIndex(of: 0x0A) {
            let lineData = txBuffer[..<newline]
            txBuffer.removeSubrange(...newline)
            let response = String(decoding: lineData, as: UTF8.self)
            emit(response)
            if let request = activeRequest,
               matchesExpectedType(response, expected: request.expectedType) {
                completeActive(response)
                drainWrites()
            }
        }
    }

    func send(line: String, reply: @escaping (String) -> Void) {
        centralQueue.async {
            let request = self.preparedRequest(for: line)
            if self.activeRequest?.expectedType == "approval_decision" {
                emit("socket request rejected: approval pending")
                reply(self.errorLine("approval pending"))
                return
            }
            self.requestQueue.append(BleRequest(
                data: Data(request.line.utf8),
                expectedType: request.expectedType,
                timeout: request.timeout,
                reply: reply
            ))
            self.drainWrites()
        }
    }

    private func drainWrites() {
        guard isReady, activeRequest == nil, !requestQueue.isEmpty else {
            return
        }
        let request = requestQueue.removeFirst()
        pendingWrite = request.data
        activeRequest = request
        startActiveTimer(expectedType: request.expectedType, timeout: request.timeout)
        writeNextChunk()
    }

    private func preparedRequest(for line: String) -> (
        line: String,
        expectedType: String?,
        timeout: TimeInterval
    ) {
        let normalized = line.hasSuffix("\n") ? line : line + "\n"
        guard let data = normalized.data(using: .utf8),
              var object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = object["type"] as? String else {
            return (normalized, expectedResponseType(for: normalized), requestTimeout)
        }

        var timeout = requestTimeout
        if let value = object["timeout"] as? NSNumber {
            timeout = max(1, value.doubleValue)
            object.removeValue(forKey: "timeout")
            if let sanitized = try? JSONSerialization.data(withJSONObject: object),
               let sanitizedLine = String(data: sanitized, encoding: .utf8) {
                return (
                    sanitizedLine + "\n",
                    type == "approval_request" ? "approval_decision" : "device_status",
                    timeout
                )
            }
        }

        return (
            normalized,
            type == "approval_request" ? "approval_decision" : "device_status",
            timeout
        )
    }

    private func expectedResponseType(for line: String) -> String? {
        guard let data = line.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data),
              let object = json as? [String: Any],
              let type = object["type"] as? String else {
            return nil
        }
        if type == "approval_request" {
            return "approval_decision"
        }
        return "device_status"
    }

    private func matchesExpectedType(_ line: String, expected: String?) -> Bool {
        guard let expected else {
            return true
        }
        guard let data = line.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data),
              let object = json as? [String: Any],
              let type = object["type"] as? String else {
            return false
        }
        if type == "error" {
            return true
        }
        return type == expected
    }

    private func startActiveTimer(expectedType: String?, timeout: TimeInterval) {
        activeTimer?.cancel()
        let timer = DispatchSource.makeTimerSource(queue: centralQueue)
        timer.schedule(deadline: .now() + timeout)
        timer.setEventHandler { [weak self] in
            let expected = expectedType ?? "response"
            emit("request timeout waiting for \(expected)")
            self?.completeActiveWithError("timeout waiting for \(expected)")
            self?.drainWrites()
        }
        activeTimer = timer
        timer.resume()
    }

    private func cancelActiveTimer() {
        activeTimer?.cancel()
        activeTimer = nil
    }

    private func completeActive(_ response: String) {
        guard let request = activeRequest else {
            return
        }
        cancelActiveTimer()
        activeRequest = nil
        request.reply(response)
    }

    private func completeActiveWithError(_ message: String) {
        guard let request = activeRequest else {
            return
        }
        cancelActiveTimer()
        activeRequest = nil
        request.reply(errorLine(message))
    }

    private func failActiveAndQueued(_ message: String) {
        cancelActiveTimer()
        if let request = activeRequest {
            request.reply(errorLine(message))
        }
        activeRequest = nil
        for request in requestQueue {
            request.reply(errorLine(message))
        }
        requestQueue.removeAll()
    }

    private func errorLine(_ message: String) -> String {
        let escaped = message
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
        return #"{"v":0,"type":"error","error":"\#(escaped)"}"#
    }

    private func writeNextChunk() {
        guard let peripheral, let rxCharacteristic else {
            fail("not connected")
        }
        if pendingWrite.isEmpty {
            emit("write complete")
            return
        }

        let count = min(chunkSize, pendingWrite.count)
        let chunk = pendingWrite.prefix(count)
        pendingWrite.removeFirst(count)
        peripheral.writeValue(Data(chunk), for: rxCharacteristic, type: .withResponse)
    }

    private func fail(_ message: String) -> Never {
        emit(message)
        fputs(message + "\n", stderr)
        exit(1)
    }
}

struct Options {
    var line: String?
    var server = false
    var port: UInt16 = 47391
    var requestTimeout: TimeInterval = 120
    var deviceName = "Codex-Buddy"
    var pairCode = ""
}

func parseOptions() -> Options {
    var options = Options()
    let args = CommandLine.arguments
    var index = 1
    while index < args.count {
        let arg = args[index]
        if arg == "--line", index + 1 < args.count {
            options.line = args[index + 1]
            index += 2
        } else if arg == "--server" {
            options.server = true
            index += 1
        } else if arg == "--port", index + 1 < args.count {
            options.port = UInt16(args[index + 1]) ?? options.port
            index += 2
        } else if arg == "--request-timeout", index + 1 < args.count {
            options.requestTimeout = TimeInterval(args[index + 1]) ?? options.requestTimeout
            index += 2
        } else if arg == "--device-name", index + 1 < args.count {
            options.deviceName = args[index + 1]
            index += 2
        } else if arg == "--pair-code", index + 1 < args.count {
            options.pairCode = args[index + 1]
            index += 2
        } else {
            index += 1
        }
    }
    if !options.server && options.line == nil {
        options.line = #"{"v":0,"type":"heartbeat","state":"review","summary":"BLE smoke test","entries":[{"kind":"tool","text":"ble_smoke"}],"pet":{"id":"codex-placeholder","displayName":"Codex Placeholder"}}"#
    }
    return options
}

let options = parseOptions()
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let hasBluetoothUsage = Bundle.main.object(forInfoDictionaryKey: "NSBluetoothAlwaysUsageDescription") != nil
emit("bundle \(Bundle.main.bundleIdentifier ?? "nil") bluetooth_usage \(hasBluetoothUsage ? "yes" : "no")")
let bridge = BleBridge(
    onceLine: options.line,
    serverPort: options.server ? options.port : nil,
    requestTimeout: options.requestTimeout,
    deviceName: options.deviceName,
    pairCode: options.pairCode
)
if !options.server {
    DispatchQueue.main.asyncAfter(deadline: .now() + 20) {
        emit("timeout waiting for device response")
        fputs("timeout waiting for device response\n", stderr)
        exit(1)
    }
}
private var bridgeRef: BleBridge? = bridge
Timer.scheduledTimer(withTimeInterval: 3600, repeats: true) { _ in
    _ = bridgeRef
}
withExtendedLifetime(bridgeRef) {
    RunLoop.main.run()
}
