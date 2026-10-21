import Foundation

struct SessionCredentials: Codable, Equatable, Sendable {
    let accessToken: String
    let accessExpiresAt: String
    let refreshToken: String
    let refreshExpiresAt: String
    let sessionID: String
    let deviceID: String
    let userID: String?

    init(
        accessToken: String,
        accessExpiresAt: String,
        refreshToken: String,
        refreshExpiresAt: String,
        sessionID: String,
        deviceID: String,
        userID: String? = nil
    ) throws {
        guard !accessToken.isEmpty, !refreshToken.isEmpty, !sessionID.isEmpty, !deviceID.isEmpty else {
            throw IdentityValidationError.incompleteSession
        }
        self.accessToken = accessToken
        self.accessExpiresAt = accessExpiresAt
        self.refreshToken = refreshToken
        self.refreshExpiresAt = refreshExpiresAt
        self.sessionID = sessionID
        self.deviceID = deviceID
        self.userID = userID
    }

    func assigning(userID: String) throws -> SessionCredentials {
        try SessionCredentials(
            accessToken: accessToken,
            accessExpiresAt: accessExpiresAt,
            refreshToken: refreshToken,
            refreshExpiresAt: refreshExpiresAt,
            sessionID: sessionID,
            deviceID: deviceID,
            userID: userID
        )
    }
}

enum IdentityValidationError: Error, Equatable {
    case incompleteSession
    case invalidTokenType
}

struct TokenResponse: Codable, Equatable, Sendable {
    let accessToken: String
    let tokenType: String
    let expiresAt: String
    let refreshToken: String?
    let refreshExpiresAt: String?
    let sessionID: String?
    let deviceID: String?

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case tokenType = "token_type"
        case expiresAt = "expires_at"
        case refreshToken = "refresh_token"
        case refreshExpiresAt = "refresh_expires_at"
        case sessionID = "session_id"
        case deviceID = "device_id"
    }

    func credentials(userID: String? = nil) throws -> SessionCredentials {
        guard tokenType.caseInsensitiveCompare("bearer") == .orderedSame else {
            throw IdentityValidationError.invalidTokenType
        }
        guard let refreshToken, let refreshExpiresAt, let sessionID, let deviceID else {
            throw IdentityValidationError.incompleteSession
        }
        return try SessionCredentials(
            accessToken: accessToken,
            accessExpiresAt: expiresAt,
            refreshToken: refreshToken,
            refreshExpiresAt: refreshExpiresAt,
            sessionID: sessionID,
            deviceID: deviceID,
            userID: userID
        )
    }
}

struct UserProfile: Codable, Equatable, Sendable {
    let id: String
    let username: String
    let phoneMasked: String
    let role: String
    let status: String
    let locale: String
    let mustChangePassword: Bool
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id, username, role, status, locale
        case phoneMasked = "phone_masked"
        case mustChangePassword = "must_change_password"
        case createdAt = "created_at"
    }
}

struct RegistrationInput: Equatable, Sendable {
    let phone: String
    let code: String
    let challengeID: String
    let username: String
    let password: String
    let locale: String
}

struct RegistrationChallenge: Codable, Equatable, Sendable {
    let challengeID: String
    let expiresAt: String
    let retryAfterSeconds: Int

    enum CodingKeys: String, CodingKey {
        case challengeID = "challenge_id"
        case expiresAt = "expires_at"
        case retryAfterSeconds = "retry_after_seconds"
    }
}

struct CachedProject: Codable, Equatable, Sendable {
    let id: String
    let title: String
    let mode: String
    let updatedAt: String
}
