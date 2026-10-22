@testable import SmartScan
import Foundation
import XCTest

final class WorkspaceAPITests: XCTestCase {
    override func tearDown() {
        StubURLProtocol.handler = nil
        super.tearDown()
    }

    func testPageEditUsesFormalPathAndNormalizedCorners() async throws {
        let api = try makeAPI()
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/pages/page-1/edits")
            XCTAssertEqual(request.httpMethod, "POST")
            let body = try XCTUnwrap(requestBody(request))
            let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
            XCTAssertEqual(json["filter"] as? String, "grayscale")
            XCTAssertEqual((json["corners"] as? [[String: Any]])?.count, 4)
            return apiResponse(for: request, body: legacyPageJSON)
        }

        let page = try await api.editPage(
            id: "page-1",
            corners: WorkspaceCorner.fullPage,
            filter: .grayscale
        )

        XCTAssertEqual(page.activeResultVersion, 2)
    }

    func testExportCreationKeepsOCRFlagInsideJSONBody() async throws {
        let api = try makeAPI()
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/projects/project-1/exports")
            let body = try XCTUnwrap(requestBody(request))
            let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
            XCTAssertEqual(json["format"] as? String, "pdf")
            XCTAssertEqual(json["quality"] as? String, "clear")
            XCTAssertEqual(json["include_ocr_text"] as? Bool, true)
            return apiResponse(for: request, status: 201, body: exportJSON)
        }

        let result = try await api.createExport(
            projectID: "project-1",
            format: .pdf,
            quality: .clear,
            includeOCRText: true
        )

        XCTAssertEqual(result.artifacts.first?.sha256, String(repeating: "a", count: 64))
    }

    func testExamSuggestionDismissalUsesCurrentResultVersion() async throws {
        let api = try makeAPI()
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/pages/page-1/exam-suggestion-dismissal")
            XCTAssertEqual(request.httpMethod, "PUT")
            let body = try XCTUnwrap(requestBody(request))
            let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
            XCTAssertEqual(json["result_version"] as? Int, 2)
            XCTAssertEqual(json["reason"] as? String, "user_dismissed")
            return apiResponse(for: request, body: pageJSON)
        }

        let page = try await api.dismissExamSuggestion(id: "page-1", resultVersion: 2)

        XCTAssertEqual(page.examResultVersion, 2)
        XCTAssertEqual(page.examConfidenceBand, "high")
        XCTAssertEqual(page.examSuggestionVisible, false)
    }

    func testBookSideRetakeUsesMultipartAndParsesLogicalPageEvidence() async throws {
        let api = try makeAPI()
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/pages/page-1/book-retakes")
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertTrue(request.value(forHTTPHeaderField: "Content-Type")?.hasPrefix("multipart/form-data; boundary=") == true)
            let body = try XCTUnwrap(requestBody(request))
            let text = String(decoding: body, as: UTF8.self)
            XCTAssertTrue(text.contains("name=\"file\""))
            XCTAssertTrue(text.contains("filename=\"book-retake.jpg\""))
            XCTAssertTrue(text.contains("Content-Type: image/jpeg"))
            return apiResponse(for: request, status: 202, body: bookRetakePageJSON)
        }

        let page = try await api.retakeBookSide(
            id: "page-1",
            data: Data([0xff, 0xd8, 0xff, 0xd9]),
            mimeType: "image/jpeg"
        )

        XCTAssertEqual(page.bookSide, "left")
        XCTAssertEqual(page.bookSplitStatus, "retake")
        XCTAssertEqual(page.bookIsCurrent, true)
    }

    func testBookIntegrityDecisionAndAssemblyUseVersionedEndpoints() async throws {
        let api = try makeAPI()
        var requestCount = 0
        StubURLProtocol.handler = { request in
            requestCount += 1
            if requestCount == 1 {
                XCTAssertEqual(request.url?.path, "/v1/projects/project-1/book-integrity/decision")
                XCTAssertEqual(request.httpMethod, "PUT")
                let body = try XCTUnwrap(requestBody(request))
                let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
                XCTAssertEqual(json["issue_key"] as? String, "missing-2")
                XCTAssertEqual(json["decision"] as? String, "confirmed_absent")
                return apiResponse(for: request, body: bookIntegrityJSON)
            }
            XCTAssertEqual(request.url?.path, "/v1/projects/project-1/book-assemblies")
            let body = try XCTUnwrap(requestBody(request))
            let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
            XCTAssertEqual(json["quality"] as? String, "balanced")
            XCTAssertEqual(json["include_ocr_text"] as? Bool, true)
            return apiResponse(for: request, status: 201, body: bookAssemblyJSON)
        }

        let report = try await api.decideBookIntegrity(
            projectID: "project-1",
            issueKey: "missing-2",
            decision: "confirmed_absent"
        )
        let assembly = try await api.assembleBook(
            projectID: "project-1",
            quality: .balanced,
            includeOCRText: true
        )

        XCTAssertTrue(report.readyToAssemble)
        XCTAssertEqual(assembly.bookAssemblyRevision, 2)
        XCTAssertEqual(assembly.bookPreviousExportID, "export-previous")
    }

    func testBookSupplementIncludesPositionAndExpectedPrintedNumber() async throws {
        let api = try makeAPI()
        StubURLProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/projects/project-1/book-supplements")
            XCTAssertEqual(request.httpMethod, "POST")
            let text = String(decoding: try XCTUnwrap(requestBody(request)), as: UTF8.self)
            XCTAssertTrue(text.contains("name=\"insert_at\""))
            XCTAssertTrue(text.contains("\r\n2\r\n"))
            XCTAssertTrue(text.contains("name=\"expected_page_label\""))
            XCTAssertTrue(text.contains("\r\niv\r\n"))
            return apiResponse(for: request, status: 202, body: bookSupplementPageJSON)
        }

        let page = try await api.supplementBookPage(
            projectID: "project-1",
            data: Data([0xff, 0xd8, 0xff, 0xd9]),
            mimeType: "image/jpeg",
            insertAt: 2,
            expectedPageLabel: "iv"
        )

        XCTAssertEqual(page.bookExpectedPageLabel, "iv")
        XCTAssertEqual(page.bookSplitStatus, "supplement")
    }

    func testAccountDeletionUsesAuthenticatedRequestAndSeparateSMSPurpose() async throws {
        let api = try makeAPI()
        var requestCount = 0
        StubURLProtocol.handler = { request in
            requestCount += 1
            let body = try XCTUnwrap(requestBody(request))
            let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
            if requestCount == 1 {
                XCTAssertEqual(request.url?.path, "/v1/auth/sms-challenges")
                XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
                XCTAssertEqual(json["purpose"] as? String, "account_deletion")
                return apiResponse(
                    for: request,
                    status: 201,
                    body: #"{"challenge_id":"challenge-1","expires_at":"2026-10-21T00:05:00Z","retry_after_seconds":60}"#
                )
            }
            XCTAssertEqual(request.url?.path, "/v1/me/account-deletion")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer access-1")
            XCTAssertEqual(json["sms_challenge_id"] as? String, "challenge-1")
            return apiResponse(for: request, status: 202, body: deletionJSON)
        }

        _ = try await api.requestSMSChallenge(phone: "+8613800001234", purpose: "account_deletion")
        let receipt = try await api.requestAccountDeletion(
            phone: "+8613800001234",
            challengeID: "challenge-1",
            code: "123456"
        )

        XCTAssertEqual(receipt.status, "pending")
    }

    func testAIEndpointsUseProjectConsentAndIdempotencyWithoutClientProviderConfiguration() async throws {
        let api = try makeAPI()
        var requestCount = 0
        StubURLProtocol.handler = { request in
            requestCount += 1
            switch requestCount {
            case 1:
                XCTAssertEqual(request.url?.path, "/v1/ai/capabilities")
                XCTAssertEqual(request.httpMethod, "GET")
                return apiResponse(for: request, body: aiCapabilitiesJSON)
            case 2:
                XCTAssertEqual(request.url?.path, "/v1/projects/project-1/ai-settings")
                XCTAssertEqual(request.httpMethod, "PUT")
                let json = try XCTUnwrap(
                    JSONSerialization.jsonObject(with: try XCTUnwrap(requestBody(request))) as? [String: Any]
                )
                XCTAssertEqual(json["enabled"] as? Bool, true)
                XCTAssertEqual(json["consent_version"] as? String, "2026-10-23.1")
                return apiResponse(for: request, body: aiProjectJSON)
            case 3:
                XCTAssertEqual(request.url?.path, "/v1/pages/page-1/ai-enhancements")
                XCTAssertEqual(request.value(forHTTPHeaderField: "Idempotency-Key"), "ios-ai.stable-key-1234")
                let json = try XCTUnwrap(
                    JSONSerialization.jsonObject(with: try XCTUnwrap(requestBody(request))) as? [String: Any]
                )
                XCTAssertEqual(json["enhancement_kind"] as? String, "complex_ocr")
                XCTAssertEqual(json["source_result_version"] as? Int, 2)
                return apiResponse(for: request, status: 202, body: aiEnhancementJSON)
            default:
                XCTAssertEqual(request.url?.path, "/v1/ai-enhancements/enhancement-1/accept")
                XCTAssertEqual(request.httpMethod, "POST")
                return apiResponse(for: request, body: aiEnhancementAcceptedJSON)
            }
        }

        let capabilities = try await api.aiCapabilities()
        let project = try await api.updateProjectAI(
            projectID: "project-1",
            enabled: true,
            consentVersion: capabilities.consentVersion
        )
        let enhancement = try await api.createAIEnhancement(
            pageID: "page-1",
            kind: "complex_ocr",
            sourceResultVersion: 2,
            idempotencyKey: "ios-ai.stable-key-1234"
        )
        let accepted = try await api.decideAIEnhancement(id: enhancement.id, accepted: true)

        XCTAssertEqual(capabilities.executionMode, "mock")
        XCTAssertTrue(project.isAIEnabled)
        XCTAssertEqual(Set(enhancement.candidates.map(\.kind)), ["formula", "table", "layout"])
        XCTAssertEqual(accepted.status, "accepted")
    }

    private func makeAPI() throws -> URLSessionSmartScanAPI {
        let sessions = TestSessionStore()
        try sessions.save(token().credentials(userID: "user-1"))
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [StubURLProtocol.self]
        return URLSessionSmartScanAPI(
            configuration: try APIConfiguration(baseURL: URL(string: "https://api.example.test/")!),
            sessions: sessions,
            urlSession: URLSession(configuration: configuration)
        )
    }
}

private func requestBody(_ request: URLRequest) -> Data? {
    if let body = request.httpBody { return body }
    guard let stream = request.httpBodyStream else { return nil }
    stream.open()
    defer { stream.close() }
    var data = Data()
    var buffer = [UInt8](repeating: 0, count: 1024)
    while stream.hasBytesAvailable {
        let count = stream.read(&buffer, maxLength: buffer.count)
        if count <= 0 { break }
        data.append(contentsOf: buffer.prefix(count))
    }
    return data
}

private func apiResponse(
    for request: URLRequest,
    status: Int = 200,
    body: String
) -> (HTTPURLResponse, Data) {
    let response = HTTPURLResponse(
        url: request.url!,
        statusCode: status,
        httpVersion: "HTTP/1.1",
        headerFields: ["Content-Type": "application/json"]
    )!
    return (response, Data(body.utf8))
}

private let pageJSON = #"{"id":"page-1","project_id":"project-1","page_number":1,"quality_warning":null,"rotation_degrees":0,"active_result_version":2,"review_status":"pending","ocr_status":"ready","exam_result_version":2,"exam_confidence_band":"high","exam_recommendation":"suggest_cleanup","exam_suggestion_visible":false}"#
private let legacyPageJSON = #"{"id":"page-1","project_id":"project-1","page_number":1,"quality_warning":null,"rotation_degrees":0,"active_result_version":2,"review_status":"pending","ocr_status":"ready"}"#
private let bookRetakePageJSON = #"{"id":"replacement-page","project_id":"project-1","page_number":1,"quality_warning":null,"rotation_degrees":0,"active_result_version":0,"review_status":"not_required","ocr_status":"disabled","book_capture_id":"replacement-page","book_side":"left","book_split_status":"retake","book_split_confidence":null,"book_split_reason":"single_side_retake","book_dewarp_applied":null,"book_dewarp_source_score":null,"book_dewarp_output_score":null,"book_dewarp_reason":null,"book_replaced_by_page_id":null,"book_is_current":true}"#
private let bookSupplementPageJSON = #"{"id":"supplement-page","project_id":"project-1","page_number":2,"quality_warning":null,"rotation_degrees":0,"active_result_version":0,"review_status":"not_required","ocr_status":"pending","book_split_status":"supplement","book_expected_page_label":"iv","book_is_current":true}"#
private let bookIntegrityJSON = #"{"project_id":"project-1","pages_checked":2,"included_page_count":2,"visible_page_number_count":2,"processing_page_count":0,"blocking_issue_count":0,"ready_to_assemble":true,"issues":[]}"#
private let bookAssemblyJSON = #"{"id":"export-2","project_id":"project-1","format":"pdf","quality":"balanced","include_ocr_text":true,"status":"ready","page_count":2,"error_code":null,"artifacts":[],"created_at":"2026-10-21T00:00:00Z","completed_at":"2026-10-21T00:01:00Z","book_assembly_signature":"signature","book_assembly_revision":2,"book_previous_export_id":"export-previous"}"#
private let exportJSON = #"{"id":"export-1","project_id":"project-1","format":"pdf","quality":"clear","include_ocr_text":true,"status":"ready","page_count":1,"error_code":null,"artifacts":[{"id":"artifact-1","page_id":null,"sequence":1,"file_name":"scan.pdf","mime_type":"application/pdf","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","size_bytes":12}],"created_at":"2026-10-21T00:00:00Z","completed_at":"2026-10-21T00:01:00Z"}"#
private let deletionJSON = #"{"id":"deletion-1","status":"pending","requested_at":"2026-10-21T00:00:00Z","execute_after":"2026-10-28T00:00:00Z","canceled_at":null,"completed_at":null}"#
private let aiCapabilitiesJSON = #"{"available":true,"business_orchestration_ready":true,"execution_mode":"mock","consent_version":"2026-10-23.1","transmission_notice_code":"ai_data_transfer_v1","enhancement_kinds":["recommended","complex_ocr"],"task_types":["classify_page","ocr_formula"]}"#
private let aiProjectJSON = #"{"id":"project-1","title":"Scan","suggested_name":null,"mode":"document","reading_order":"ltr","created_at":"2026-10-23T00:00:00Z","updated_at":"2026-10-23T00:00:01Z","ai_enabled":true,"ai_consent_version":"2026-10-23.1","provider_id":"must-not-be-modeled"}"#
private let aiEnhancementJSON = #"{"id":"enhancement-1","project_id":"project-1","page_id":"page-1","processing_job_id":"job-1","enhancement_kind":"complex_ocr","requested_tasks":["ocr_formula"],"source_result_version":2,"status":"candidate_ready","candidate_result":{"tasks":{"ocr_formula":{"blocks":[{"block_type":"formula","latex_candidate":"x^2","confidence":0.92},{"block_type":"table","cells":[{"row":0,"column":0,"text_candidate":"A"},{"row":0,"column":1,"text_candidate":"B"}],"confidence":0.84},{"block_type":"layout","text_candidate":"Summary","confidence":0.73}]}}},"confidence":0.84,"error_code":null,"provider_id":"secret-provider","model":"secret-model","evidence":{"url":"https://internal.invalid"},"created_at":"2026-10-23T00:00:00Z","updated_at":"2026-10-23T00:00:01Z"}"#
private let aiEnhancementAcceptedJSON = #"{"id":"enhancement-1","project_id":"project-1","page_id":"page-1","processing_job_id":"job-1","enhancement_kind":"complex_ocr","requested_tasks":["ocr_formula"],"source_result_version":2,"status":"accepted","candidate_result":{"tasks":{"ocr_formula":{"blocks":[]}}},"confidence":0.84,"error_code":null,"created_at":"2026-10-23T00:00:00Z","updated_at":"2026-10-23T00:00:02Z"}"#
