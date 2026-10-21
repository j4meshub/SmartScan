import Foundation
import UIKit

struct APIConfiguration: Equatable, Sendable {
    let baseURL: URL

    init(baseURL: URL) throws {
        let scheme = baseURL.scheme?.lowercased()
        let host = baseURL.host?.lowercased()
        let loopback = host == "localhost" || host == "127.0.0.1" || host == "::1"
        guard scheme == "https" || (scheme == "http" && loopback) else {
            throw APIClientError.insecureBaseURL
        }
        self.baseURL = baseURL
    }

    static func fromBundle(_ bundle: Bundle = .main) -> APIConfiguration {
        let raw = bundle.object(forInfoDictionaryKey: "SMARTSCAN_API_BASE_URL") as? String
        let url = raw.flatMap(URL.init(string:)) ?? URL(string: "https://api.invalid/")!
        return (try? APIConfiguration(baseURL: url)) ?? (try! APIConfiguration(baseURL: URL(string: "https://api.invalid/")!))
    }
}

enum APIClientError: Error, Equatable {
    case insecureBaseURL
    case invalidResponse
    case http(statusCode: Int, detail: String?)
    case decoding
}

protocol SmartScanAuthenticationAPI {
    func requestRegistrationChallenge(phone: String) async throws -> RegistrationChallenge
    func register(_ input: RegistrationInput) async throws -> TokenResponse
    func login(username: String, password: String) async throws -> TokenResponse
    func refresh(refreshToken: String) async throws -> TokenResponse
    func currentUser() async throws -> UserProfile
    func logout() async throws
}

final class URLSessionSmartScanAPI: SmartScanAuthenticationAPI {
    private let configuration: APIConfiguration
    private let sessions: SessionStoring
    private let urlSession: URLSession
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()
    private let deviceName: String

    init(
        configuration: APIConfiguration,
        sessions: SessionStoring,
        urlSession: URLSession = .shared,
        deviceName: String = UIDevice.current.name
    ) {
        self.configuration = configuration
        self.sessions = sessions
        self.urlSession = urlSession
        self.deviceName = deviceName
    }

    func requestRegistrationChallenge(phone: String) async throws -> RegistrationChallenge {
        try await send(
            path: "v1/auth/sms-challenges",
            method: "POST",
            body: SMSChallengeRequest(phone: phone, purpose: "registration"),
            authenticated: false
        )
    }

    func register(_ input: RegistrationInput) async throws -> TokenResponse {
        try await send(
            path: "v1/auth/register",
            method: "POST",
            body: RegisterRequest(input: input),
            authenticated: false
        )
    }

    func login(username: String, password: String) async throws -> TokenResponse {
        try await send(
            path: "v1/auth/login",
            method: "POST",
            body: LoginRequest(username: username, password: password),
            authenticated: false
        )
    }

    func refresh(refreshToken: String) async throws -> TokenResponse {
        try await send(
            path: "v1/auth/refresh",
            method: "POST",
            body: RefreshRequest(refreshToken: refreshToken),
            authenticated: false
        )
    }

    func currentUser() async throws -> UserProfile {
        try await send(path: "v1/me", method: "GET", authenticated: true)
    }

    func logout() async throws {
        try await sendWithoutResponse(path: "v1/auth/logout", method: "POST", authenticated: true)
    }

    private func send<Response: Decodable, Body: Encodable>(
        path: String,
        method: String,
        body: Body,
        authenticated: Bool
    ) async throws -> Response {
        var request = try makeRequest(path: path, method: method, authenticated: authenticated)
        request.httpBody = try encoder.encode(body)
        return try await execute(request)
    }

    private func send<Response: Decodable>(
        path: String,
        method: String,
        authenticated: Bool
    ) async throws -> Response {
        let request = try makeRequest(path: path, method: method, authenticated: authenticated)
        return try await execute(request)
    }

    private func sendWithoutResponse(path: String, method: String, authenticated: Bool) async throws {
        let request = try makeRequest(path: path, method: method, authenticated: authenticated)
        let (_, response) = try await urlSession.data(for: request)
        try validate(response: response, data: Data())
    }

    private func execute<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        let (data, response) = try await urlSession.data(for: request)
        try validate(response: response, data: data)
        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw APIClientError.decoding
        }
    }

    private func makeRequest(path: String, method: String, authenticated: Bool) throws -> URLRequest {
        guard let url = URL(string: path, relativeTo: configuration.baseURL)?.absoluteURL else {
            throw APIClientError.invalidResponse
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(try sessions.deviceIdentifier(), forHTTPHeaderField: "X-Device-ID")
        request.setValue(encodedHeader(deviceName), forHTTPHeaderField: "X-Device-Name")
        request.setValue("ios", forHTTPHeaderField: "X-Device-Platform")
        if authenticated {
            guard let token = sessions.current()?.accessToken else {
                throw APIClientError.http(statusCode: 401, detail: "session_missing")
            }
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let response = response as? HTTPURLResponse else { throw APIClientError.invalidResponse }
        guard (200..<300).contains(response.statusCode) else {
            let detail = (try? decoder.decode(ErrorResponse.self, from: data))?.detail
            throw APIClientError.http(statusCode: response.statusCode, detail: detail)
        }
    }

    private func encodedHeader(_ value: String) -> String {
        value.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "iPhone"
    }
}

private struct SMSChallengeRequest: Encodable {
    let phone: String
    let purpose: String
}

private struct RegisterRequest: Encodable {
    let phone: String
    let smsCode: String
    let smsChallengeID: String
    let username: String
    let password: String
    let locale: String

    init(input: RegistrationInput) {
        phone = input.phone
        smsCode = input.code
        smsChallengeID = input.challengeID
        username = input.username
        password = input.password
        locale = input.locale
    }

    enum CodingKeys: String, CodingKey {
        case phone, username, password, locale
        case smsCode = "sms_code"
        case smsChallengeID = "sms_challenge_id"
    }
}

private struct LoginRequest: Encodable {
    let username: String
    let password: String
}

private struct RefreshRequest: Encodable {
    let refreshToken: String

    enum CodingKeys: String, CodingKey {
        case refreshToken = "refresh_token"
    }
}

private struct ErrorResponse: Decodable {
    let detail: String?
}
