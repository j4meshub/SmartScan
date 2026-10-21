import Foundation

protocol SmartScanWorkspaceAPI {
    func listProjects() async throws -> [WorkspaceProject]
    func listPages(projectID: String) async throws -> [WorkspacePage]
    func listExports(projectID: String) async throws -> [WorkspaceExport]
    func reorderPages(projectID: String, pageIDs: [String]) async throws -> [WorkspacePage]
    func rotatePage(id: String, degrees: Int) async throws -> WorkspacePage
    func editPage(id: String, corners: [WorkspaceCorner], filter: WorkspaceFilter) async throws -> WorkspacePage
    func reviewPage(id: String, confirmed: Bool) async throws -> WorkspacePage
    func dismissExamSuggestion(id: String, resultVersion: Int) async throws -> WorkspacePage
    func retakeBookSide(id: String, data: Data, mimeType: String) async throws -> WorkspacePage
    func createExport(
        projectID: String,
        format: WorkspaceExportFormat,
        quality: WorkspaceExportQuality,
        includeOCRText: Bool
    ) async throws -> WorkspaceExport
    func getExport(id: String) async throws -> WorkspaceExport
    func downloadPage(id: String) async throws -> RemoteDownload
    func downloadArtifact(id: String) async throws -> RemoteDownload
}

protocol SmartScanAccountDeletionAPI {
    func requestSMSChallenge(phone: String, purpose: String) async throws -> RegistrationChallenge
    func requestAccountDeletion(phone: String, challengeID: String, code: String) async throws -> AccountDeletionReceipt
    func cancelAccountDeletion(phone: String, challengeID: String, code: String) async throws -> AccountDeletionReceipt
}

extension URLSessionSmartScanAPI: SmartScanWorkspaceAPI, SmartScanAccountDeletionAPI {
    func listProjects() async throws -> [WorkspaceProject] {
        try await execute(makeRequest(path: "v1/projects", method: "GET", authenticated: true))
    }

    func listPages(projectID: String) async throws -> [WorkspacePage] {
        try await execute(
            makeRequest(path: "v1/projects/\(projectID)/pages", method: "GET", authenticated: true)
        )
    }

    func listExports(projectID: String) async throws -> [WorkspaceExport] {
        try await execute(
            makeRequest(path: "v1/projects/\(projectID)/exports", method: "GET", authenticated: true)
        )
    }

    func reorderPages(projectID: String, pageIDs: [String]) async throws -> [WorkspacePage] {
        var request = try makeRequest(
            path: "v1/projects/\(projectID)/pages/order",
            method: "PATCH",
            authenticated: true
        )
        request.httpBody = try JSONEncoder().encode(PageOrderRequest(pageIDs: pageIDs))
        return try await execute(request)
    }

    func rotatePage(id: String, degrees: Int) async throws -> WorkspacePage {
        var request = try makeRequest(path: "v1/pages/\(id)/rotations", method: "POST", authenticated: true)
        request.httpBody = try JSONEncoder().encode(PageRotationRequest(degrees: degrees))
        return try await execute(request)
    }

    func editPage(id: String, corners: [WorkspaceCorner], filter: WorkspaceFilter) async throws -> WorkspacePage {
        var request = try makeRequest(path: "v1/pages/\(id)/edits", method: "POST", authenticated: true)
        request.httpBody = try JSONEncoder().encode(PageEditRequest(corners: corners, filter: filter.rawValue))
        return try await execute(request)
    }

    func reviewPage(id: String, confirmed: Bool) async throws -> WorkspacePage {
        var request = try makeRequest(path: "v1/pages/\(id)/review", method: "PATCH", authenticated: true)
        request.httpBody = try JSONEncoder().encode(
            PageReviewRequest(status: confirmed ? "confirmed" : "pending", note: nil)
        )
        return try await execute(request)
    }

    func dismissExamSuggestion(id: String, resultVersion: Int) async throws -> WorkspacePage {
        var request = try makeRequest(
            path: "v1/pages/\(id)/exam-suggestion-dismissal",
            method: "PUT",
            authenticated: true
        )
        request.httpBody = try JSONEncoder().encode(
            ExamSuggestionDismissalRequest(resultVersion: resultVersion, reason: "user_dismissed")
        )
        return try await execute(request)
    }

    func retakeBookSide(id: String, data: Data, mimeType: String) async throws -> WorkspacePage {
        let boundary = "SmartScan-Book-Retake-\(UUID().uuidString)"
        var request = try makeRequest(
            path: "v1/pages/\(id)/book-retakes",
            method: "POST",
            authenticated: true
        )
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = multipartBody(
            boundary: boundary,
            fieldName: "file",
            fileName: "book-retake.jpg",
            mimeType: mimeType,
            data: data
        )
        return try await execute(request)
    }

    func createExport(
        projectID: String,
        format: WorkspaceExportFormat,
        quality: WorkspaceExportQuality,
        includeOCRText: Bool
    ) async throws -> WorkspaceExport {
        var request = try makeRequest(
            path: "v1/projects/\(projectID)/exports",
            method: "POST",
            authenticated: true
        )
        request.httpBody = try JSONEncoder().encode(
            ExportCreateRequest(
                format: format.rawValue,
                quality: quality.rawValue,
                includeOCRText: includeOCRText,
                pageIDs: nil
            )
        )
        return try await execute(request)
    }

    func getExport(id: String) async throws -> WorkspaceExport {
        try await execute(makeRequest(path: "v1/exports/\(id)", method: "GET", authenticated: true))
    }

    func downloadPage(id: String) async throws -> RemoteDownload {
        try await executeDownload(
            makeRequest(path: "v1/pages/\(id)/content?variant=active", method: "GET", authenticated: true)
        )
    }

    func downloadArtifact(id: String) async throws -> RemoteDownload {
        try await executeDownload(
            makeRequest(path: "v1/export-artifacts/\(id)/content", method: "GET", authenticated: true)
        )
    }

    func requestSMSChallenge(phone: String, purpose: String) async throws -> RegistrationChallenge {
        var request = try makeRequest(path: "v1/auth/sms-challenges", method: "POST", authenticated: false)
        request.httpBody = try JSONEncoder().encode(AccountSMSChallengeRequest(phone: phone, purpose: purpose))
        return try await execute(request)
    }

    func requestAccountDeletion(
        phone: String,
        challengeID: String,
        code: String
    ) async throws -> AccountDeletionReceipt {
        var request = try makeRequest(path: "v1/me/account-deletion", method: "POST", authenticated: true)
        request.httpBody = try JSONEncoder().encode(
            AccountDeletionRequest(phone: phone, challengeID: challengeID, code: code)
        )
        return try await execute(request)
    }

    func cancelAccountDeletion(
        phone: String,
        challengeID: String,
        code: String
    ) async throws -> AccountDeletionReceipt {
        var request = try makeRequest(
            path: "v1/auth/account-deletion/cancel",
            method: "POST",
            authenticated: false
        )
        request.httpBody = try JSONEncoder().encode(
            AccountDeletionRequest(phone: phone, challengeID: challengeID, code: code)
        )
        return try await execute(request)
    }
}

private func multipartBody(
    boundary: String,
    fieldName: String,
    fileName: String,
    mimeType: String,
    data: Data
) -> Data {
    var body = Data()
    body.append("--\(boundary)\r\n".data(using: .utf8)!)
    body.append(
        "Content-Disposition: form-data; name=\"\(fieldName)\"; filename=\"\(fileName)\"\r\n"
            .data(using: .utf8)!
    )
    body.append("Content-Type: \(mimeType)\r\n\r\n".data(using: .utf8)!)
    body.append(data)
    body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
    return body
}

private struct PageOrderRequest: Encodable {
    let pageIDs: [String]

    enum CodingKeys: String, CodingKey { case pageIDs = "page_ids" }
}

private struct PageRotationRequest: Encodable { let degrees: Int }

private struct PageEditRequest: Encodable {
    let corners: [WorkspaceCorner]
    let filter: String
}

private struct PageReviewRequest: Encodable {
    let status: String
    let note: String?
}

private struct ExamSuggestionDismissalRequest: Encodable {
    let resultVersion: Int
    let reason: String

    enum CodingKeys: String, CodingKey {
        case resultVersion = "result_version"
        case reason
    }
}

private struct ExportCreateRequest: Encodable {
    let format: String
    let quality: String
    let includeOCRText: Bool
    let pageIDs: [String]?

    enum CodingKeys: String, CodingKey {
        case format, quality
        case includeOCRText = "include_ocr_text"
        case pageIDs = "page_ids"
    }
}

private struct AccountSMSChallengeRequest: Encodable {
    let phone: String
    let purpose: String
}

private struct AccountDeletionRequest: Encodable {
    let phone: String
    let challengeID: String
    let code: String

    enum CodingKeys: String, CodingKey {
        case phone
        case challengeID = "sms_challenge_id"
        case code = "sms_code"
    }
}
