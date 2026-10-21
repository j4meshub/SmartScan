import Foundation
import Security

protocol SessionStoring: AnyObject {
    func current() -> SessionCredentials?
    func save(_ credentials: SessionCredentials) throws
    func clear() throws
    func deviceIdentifier() throws -> String
}

protocol KeychainValueStoring {
    func read(account: String) throws -> Data?
    func write(_ data: Data, account: String) throws
    func delete(account: String) throws
}

enum KeychainStoreError: Error, Equatable {
    case unexpectedStatus(OSStatus)
}

final class SystemKeychainValueStore: KeychainValueStoring {
    private let service: String

    init(service: String = "com.j4meshub.smartscan.credentials") {
        self.service = service
    }

    func read(account: String) throws -> Data? {
        var query = baseQuery(account: account)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw KeychainStoreError.unexpectedStatus(status) }
        return item as? Data
    }

    func write(_ data: Data, account: String) throws {
        let query = baseQuery(account: account)
        let attributes = [kSecValueData as String: data]
        let updateStatus = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if updateStatus == errSecSuccess { return }
        guard updateStatus == errSecItemNotFound else {
            throw KeychainStoreError.unexpectedStatus(updateStatus)
        }
        var addition = query
        addition[kSecValueData as String] = data
        addition[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let addStatus = SecItemAdd(addition as CFDictionary, nil)
        guard addStatus == errSecSuccess else { throw KeychainStoreError.unexpectedStatus(addStatus) }
    }

    func delete(account: String) throws {
        let status = SecItemDelete(baseQuery(account: account) as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw KeychainStoreError.unexpectedStatus(status)
        }
    }

    private func baseQuery(account: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }
}

final class KeychainSessionStore: SessionStoring {
    private enum Account {
        static let session = "device-session-v1"
        static let deviceID = "device-identifier-v1"
    }

    private let values: KeychainValueStoring
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()
    private let lock = NSLock()
    private var cachedSession: SessionCredentials?

    init(values: KeychainValueStoring = SystemKeychainValueStore()) {
        self.values = values
        cachedSession = try? values.read(account: Account.session).map { try decoder.decode(SessionCredentials.self, from: $0) }
        if cachedSession == nil {
            try? values.delete(account: Account.session)
        }
    }

    func current() -> SessionCredentials? {
        lock.lock()
        defer { lock.unlock() }
        return cachedSession
    }

    func save(_ credentials: SessionCredentials) throws {
        let encoded = try encoder.encode(credentials)
        try values.write(encoded, account: Account.session)
        lock.lock()
        cachedSession = credentials
        lock.unlock()
    }

    func clear() throws {
        try values.delete(account: Account.session)
        lock.lock()
        cachedSession = nil
        lock.unlock()
    }

    func deviceIdentifier() throws -> String {
        if let data = try values.read(account: Account.deviceID),
           let value = String(data: data, encoding: .utf8),
           !value.isEmpty {
            return value
        }
        let value = "ios:\(UUID().uuidString.lowercased())"
        try values.write(Data(value.utf8), account: Account.deviceID)
        return value
    }
}
