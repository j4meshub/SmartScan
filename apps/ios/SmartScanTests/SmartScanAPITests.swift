@testable import SmartScan
import Foundation
import XCTest

final class SmartScanAPITests: XCTestCase {
    override func tearDown() {
        StubURLProtocol.handler = nil
        super.tearDown()
    }

    func testLoginCarriesDeviceHeadersAndCredentialsStayInBody() async throws {
        let sessions = TestSessionStore()
        let urlSession = makeURLSession()
        let api = URLSessionSmartScanAPI(
            configuration: try APIConfiguration(baseURL: URL(string: "https://api.example.test/")!),
            sessions: sessions,
            urlSession: urlSession,
            deviceName: "测试 iPhone"
        )
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/auth/login")
            XCTAssertEqual(request.value(forHTTPHeaderField: "X-Device-ID"), "ios:test-device")
            XCTAssertEqual(request.value(forHTTPHeaderField: "X-Device-Platform"), "ios")
            XCTAssertNotNil(request.value(forHTTPHeaderField: "X-Device-Name"))
            XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
            let body = try XCTUnwrap(request.httpBody)
            let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: String])
            XCTAssertEqual(json["username"], "student")
            XCTAssertEqual(json["password"], "private-password")
            return Self.response(for: request, body: Self.tokenJSON)
        }

        let response = try await api.login(username: "student", password: "private-password")

        XCTAssertEqual(response.refreshToken, "refresh-1")
    }

    func testAuthenticatedRequestCarriesBearerToken() async throws {
        let sessions = TestSessionStore()
        try sessions.save(token().credentials(userID: "user-1"))
        let api = URLSessionSmartScanAPI(
            configuration: try APIConfiguration(baseURL: URL(string: "https://api.example.test/")!),
            sessions: sessions,
            urlSession: makeURLSession()
        )
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer access-1")
            return Self.response(for: request, body: Self.userJSON)
        }

        let profile = try await api.currentUser()
        XCTAssertEqual(profile.id, "user-1")
    }

    func testHTTPDetailIsPreserved() async throws {
        let api = URLSessionSmartScanAPI(
            configuration: try APIConfiguration(baseURL: URL(string: "https://api.example.test/")!),
            sessions: TestSessionStore(),
            urlSession: makeURLSession()
        )
        StubURLProtocol.handler = { request in
            Self.response(for: request, status: 401, body: #"{"detail":"invalid credentials"}"#)
        }

        do {
            _ = try await api.login(username: "student", password: "wrong-password")
            XCTFail("应抛出未授权错误")
        } catch {
            XCTAssertEqual(error as? APIClientError, .http(statusCode: 401, detail: "invalid credentials"))
        }
    }

    func testPlainHTTPIsOnlyAllowedForLoopback() throws {
        XCTAssertThrowsError(try APIConfiguration(baseURL: URL(string: "http://example.test")!))
        XCTAssertNoThrow(try APIConfiguration(baseURL: URL(string: "http://127.0.0.1:8000")!))
    }

    private func makeURLSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        return URLSession(configuration: configuration)
    }

    private static func response(for request: URLRequest, status: Int = 200, body: String) -> (HTTPURLResponse, Data) {
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: status,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
        return (response, Data(body.utf8))
    }

    private static let tokenJSON = #"{"access_token":"access-1","token_type":"bearer","expires_at":"2026-10-21T01:00:00Z","refresh_token":"refresh-1","refresh_expires_at":"2026-11-21T01:00:00Z","session_id":"session-1","device_id":"ios:test-device"}"#
    private static let userJSON = #"{"id":"user-1","username":"student","phone_masked":"138****0000","role":"user","status":"active","locale":"zh-CN","must_change_password":false,"created_at":"2026-10-21T00:00:00Z"}"#
}

final class StubURLProtocol: URLProtocol {
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            let (response, data) = try XCTUnwrap(Self.handler)(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

final class TestSessionStore: SessionStoring {
    private var session: SessionCredentials?
    var clearCount = 0

    func current() -> SessionCredentials? { session }
    func save(_ credentials: SessionCredentials) throws { session = credentials }
    func clear() throws { session = nil; clearCount += 1 }
    func deviceIdentifier() throws -> String { "ios:test-device" }
}
