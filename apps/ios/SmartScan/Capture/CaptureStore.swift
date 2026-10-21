import CryptoKit
import Foundation

protocol OriginalCaptureStoring {
    func saveOriginal(_ data: Data, evidence: CaptureEvidence, userID: String) async throws -> CaptureRecord
}

actor FileOriginalCaptureStore: OriginalCaptureStoring {
    private let root: URL
    private let fileManager: FileManager
    private let encoder: JSONEncoder

    init(root: URL? = nil, fileManager: FileManager = .default) {
        self.fileManager = fileManager
        if let root {
            self.root = root
        } else {
            let support = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            self.root = support.appendingPathComponent("SmartScan/captures", isDirectory: true)
        }
        encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
    }

    func saveOriginal(_ data: Data, evidence: CaptureEvidence, userID: String) throws -> CaptureRecord {
        guard !data.isEmpty else { throw CaptureStoreError.emptyImage }
        let userDigest = SHA256.hash(data: Data(userID.utf8)).map { String(format: "%02x", $0) }.joined()
        let directory = root.appendingPathComponent(userDigest, isDirectory: true)
        try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        let identifier = UUID().uuidString.lowercased()
        let originalURL = directory.appendingPathComponent("\(identifier).original.jpg")
        let evidenceURL = directory.appendingPathComponent("\(identifier).evidence.json")
        do {
            try data.write(to: originalURL, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
            try encoder.encode(evidence).write(
                to: evidenceURL,
                options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
            )
            return CaptureRecord(id: identifier, originalURL: originalURL, evidenceURL: evidenceURL)
        } catch {
            try? fileManager.removeItem(at: originalURL)
            try? fileManager.removeItem(at: evidenceURL)
            throw error
        }
    }
}

enum CaptureStoreError: Error, Equatable {
    case emptyImage
}
