import Foundation

actor AuthenticationRepository {
    private let api: SmartScanAuthenticationAPI
    private let accountDeletionAPI: SmartScanAccountDeletionAPI?
    private let sessions: SessionStoring
    private let cache: UserScopedProjectCaching
    private let localDataPurger: UserScopedLocalDataPurging?

    init(
        api: SmartScanAuthenticationAPI,
        sessions: SessionStoring,
        cache: UserScopedProjectCaching,
        accountDeletionAPI: SmartScanAccountDeletionAPI? = nil,
        localDataPurger: UserScopedLocalDataPurging? = nil
    ) {
        self.api = api
        self.sessions = sessions
        self.cache = cache
        self.accountDeletionAPI = accountDeletionAPI
        self.localDataPurger = localDataPurger
    }

    func requestRegistrationChallenge(phone: String) async throws -> RegistrationChallenge {
        guard !phone.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw AuthenticationError.invalidInput
        }
        return try await api.requestRegistrationChallenge(phone: phone)
    }

    func register(_ input: RegistrationInput) async throws -> UserProfile {
        try await authenticate { try await api.register(input) }
    }

    func login(username: String, password: String) async throws -> UserProfile {
        guard !username.isEmpty, !password.isEmpty else { throw AuthenticationError.invalidInput }
        return try await authenticate { try await api.login(username: username, password: password) }
    }

    func restore() async throws -> UserProfile? {
        guard sessions.current() != nil else { return nil }
        do {
            return try await api.currentUser()
        } catch APIClientError.http(statusCode: 401, detail: _) {
            do {
                _ = try await refresh()
                return try await api.currentUser()
            } catch {
                await clearLocalSession()
                throw error
            }
        }
    }

    func refresh() async throws -> SessionCredentials {
        guard let current = sessions.current() else { throw AuthenticationError.sessionMissing }
        do {
            let token = try await api.refresh(refreshToken: current.refreshToken)
            let replacement = try token.credentials(userID: current.userID)
            try sessions.save(replacement)
            return replacement
        } catch {
            if let apiError = error as? APIClientError,
               case .http(statusCode: 401, detail: _) = apiError {
                await clearLocalSession()
            }
            throw error
        }
    }

    func logout() async throws {
        let remoteError: Error?
        do {
            try await api.logout()
            remoteError = nil
        } catch {
            remoteError = error
        }
        await clearLocalSession()
        if let remoteError { throw remoteError }
    }

    func requestAccountDeletionChallenge(phone: String) async throws -> RegistrationChallenge {
        try validatePhone(phone)
        guard let accountDeletionAPI else { throw AuthenticationError.accountDeletionUnavailable }
        return try await accountDeletionAPI.requestSMSChallenge(phone: phone, purpose: "account_deletion")
    }

    func requestAccountDeletion(
        phone: String,
        challengeID: String,
        code: String
    ) async throws -> AccountDeletionOutcome {
        try validatePhone(phone)
        guard !challengeID.isEmpty, !code.isEmpty else { throw AuthenticationError.invalidInput }
        guard let userID = sessions.current()?.userID else { throw AuthenticationError.sessionMissing }
        guard let accountDeletionAPI else { throw AuthenticationError.accountDeletionUnavailable }
        let receipt: AccountDeletionReceipt
        do {
            receipt = try await accountDeletionAPI.requestAccountDeletion(
                phone: phone,
                challengeID: challengeID,
                code: code
            )
        } catch let error as APIClientError {
            guard case .http(statusCode: 401, detail: _) = error else { throw error }
            _ = try await refresh()
            receipt = try await accountDeletionAPI.requestAccountDeletion(
                phone: phone,
                challengeID: challengeID,
                code: code
            )
        }
        var cleanupSucceeded = true
        do { try sessions.clear() } catch { cleanupSucceeded = false }
        do { try await cache.clearUser(userID) } catch { cleanupSucceeded = false }
        if let localDataPurger {
            do { try await localDataPurger.clearUser(userID) } catch { cleanupSucceeded = false }
        }
        return AccountDeletionOutcome(receipt: receipt, localCleanupSucceeded: cleanupSucceeded)
    }

    func requestAccountDeletionCancellationChallenge(phone: String) async throws -> RegistrationChallenge {
        try validatePhone(phone)
        guard let accountDeletionAPI else { throw AuthenticationError.accountDeletionUnavailable }
        return try await accountDeletionAPI.requestSMSChallenge(phone: phone, purpose: "account_deletion_cancel")
    }

    func cancelAccountDeletion(
        phone: String,
        challengeID: String,
        code: String
    ) async throws -> AccountDeletionReceipt {
        try validatePhone(phone)
        guard !challengeID.isEmpty, !code.isEmpty else { throw AuthenticationError.invalidInput }
        guard let accountDeletionAPI else { throw AuthenticationError.accountDeletionUnavailable }
        return try await accountDeletionAPI.cancelAccountDeletion(
            phone: phone,
            challengeID: challengeID,
            code: code
        )
    }

    private func authenticate(_ request: () async throws -> TokenResponse) async throws -> UserProfile {
        let token = try await request()
        let provisional = try token.credentials()
        do {
            try sessions.save(provisional)
            let user = try await api.currentUser()
            try sessions.save(provisional.assigning(userID: user.id))
            return user
        } catch {
            try? sessions.clear()
            throw error
        }
    }

    private func clearLocalSession() async {
        let userID = sessions.current()?.userID
        try? sessions.clear()
        if let userID { try? await cache.clearUser(userID) }
    }

    private func validatePhone(_ phone: String) throws {
        guard phone.range(of: #"^\+[1-9][0-9]{7,14}$"#, options: .regularExpression) != nil else {
            throw AuthenticationError.invalidInput
        }
    }
}

enum AuthenticationError: Error, Equatable {
    case invalidInput
    case sessionMissing
    case accountDeletionUnavailable
}
