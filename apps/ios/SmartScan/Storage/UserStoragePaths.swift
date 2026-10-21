import CryptoKit
import Foundation

enum UserStoragePaths {
    static func digest(for userID: String) -> String {
        SHA256.hash(data: Data(userID.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    static func applicationSupportRoot(fileManager: FileManager = .default) -> URL {
        fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("SmartScan", isDirectory: true)
    }

    static func isDescendant(_ candidate: URL, of directory: URL) -> Bool {
        let resolvedCandidate = candidate.standardizedFileURL.resolvingSymlinksInPath()
        let resolvedDirectory = directory.standardizedFileURL.resolvingSymlinksInPath()
        let candidateComponents = resolvedCandidate.pathComponents
        let directoryComponents = resolvedDirectory.pathComponents
        return candidateComponents.count > directoryComponents.count
            && Array(candidateComponents.prefix(directoryComponents.count)) == directoryComponents
    }
}
