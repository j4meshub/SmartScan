@testable import SmartScan
import Foundation
import XCTest

final class UserLocalDataPurgerTests: XCTestCase {
    func testPurgerRemovesOnlyRequestedUsersPartitionAcrossAllRoots() async throws {
        let base = FileManager.default.temporaryDirectory
            .appendingPathComponent("smartscan-purge-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: base) }
        let roots = ["users", "captures", "upload-queue", "downloads"].map {
            base.appendingPathComponent($0, isDirectory: true)
        }
        for root in roots {
            for userID in ["user-a", "user-b"] {
                let directory = root.appendingPathComponent(UserStoragePaths.digest(for: userID), isDirectory: true)
                try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
                try Data("private".utf8).write(to: directory.appendingPathComponent("item"))
            }
        }
        let purger = FileUserLocalDataPurger(roots: roots)

        try await purger.clearUser("user-a")

        for root in roots {
            XCTAssertFalse(
                FileManager.default.fileExists(
                    atPath: root.appendingPathComponent(UserStoragePaths.digest(for: "user-a")).path
                )
            )
            XCTAssertTrue(
                FileManager.default.fileExists(
                    atPath: root.appendingPathComponent(UserStoragePaths.digest(for: "user-b")).path
                )
            )
        }
    }
}
