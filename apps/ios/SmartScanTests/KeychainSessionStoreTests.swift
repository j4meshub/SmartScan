@testable import SmartScan
import Foundation
import XCTest

final class KeychainSessionStoreTests: XCTestCase {
    func testSessionRoundTripAndRotation() throws {
        let values = MemoryKeychainValues()
        let store = KeychainSessionStore(values: values)
        let first = try token().credentials(userID: "user-1")
        let rotated = try token(access: "access-2", refresh: "refresh-2").credentials(userID: "user-1")

        try store.save(first)
        XCTAssertEqual(store.current(), first)
        try store.save(rotated)

        XCTAssertEqual(KeychainSessionStore(values: values).current(), rotated)
    }

    func testDeviceIdentifierIsStableAndSeparateFromSession() throws {
        let values = MemoryKeychainValues()
        let store = KeychainSessionStore(values: values)
        let first = try store.deviceIdentifier()
        try store.save(token().credentials())
        try store.clear()

        XCTAssertTrue(first.hasPrefix("ios:"))
        XCTAssertEqual(try KeychainSessionStore(values: values).deviceIdentifier(), first)
    }

    func testCorruptSessionIsDiscarded() throws {
        let values = MemoryKeychainValues()
        try? values.write(Data("not-json".utf8), account: "device-session-v1")

        XCTAssertNil(KeychainSessionStore(values: values).current())
        let persisted = try values.read(account: "device-session-v1")
        XCTAssertNil(persisted)
    }
}

final class MemoryKeychainValues: KeychainValueStoring {
    private var values: [String: Data] = [:]

    func read(account: String) throws -> Data? { values[account] }
    func write(_ data: Data, account: String) throws { values[account] = data }
    func delete(account: String) throws { values.removeValue(forKey: account) }
}
