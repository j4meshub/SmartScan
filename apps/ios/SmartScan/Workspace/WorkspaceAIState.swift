import Foundation

private let runningAIStatuses: Set<String> = ["queued", "processing"]

func latestAIEnhancement(
    _ enhancements: [WorkspaceAIEnhancement],
    sourceVersion: Int,
    enhancementKind: String
) -> WorkspaceAIEnhancement? {
    enhancements.first {
        $0.enhancementKind == enhancementKind && $0.sourceResultVersion == sourceVersion
    } ?? enhancements.first { $0.enhancementKind == enhancementKind }
}

func shouldPollAIEnhancements(_ enhancements: [WorkspaceAIEnhancement]) -> Bool {
    enhancements.contains { runningAIStatuses.contains($0.status) }
}

func canDecideAIEnhancement(_ enhancement: WorkspaceAIEnhancement?, activeResultVersion: Int) -> Bool {
    enhancement?.status == "candidate_ready" && enhancement?.sourceResultVersion == activeResultVersion
}

func supportsAIEnhancement(_ capabilities: WorkspaceAICapabilities?, kind: String) -> Bool {
    guard let capabilities else { return false }
    if kind == "recommended" { return capabilities.enhancementKinds.contains(kind) }
    if kind == "complex_ocr" {
        return capabilities.enhancementKinds.contains(kind) && capabilities.taskTypes.contains("ocr_formula")
    }
    return false
}

func aiConfidencePercent(_ value: Double?) -> Int? {
    guard let value, value.isFinite else { return nil }
    return Int((min(max(value, 0), 1) * 100).rounded())
}

func makeAIIdempotencyKey(
    pageID: String,
    sourceResultVersion: Int,
    randomID: String = UUID().uuidString
) throws -> String {
    guard sourceResultVersion > 0 else { throw WorkspaceError.invalidAISourceVersion }
    let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "_.:-"))
    let safePage = String(pageID.unicodeScalars.map { allowed.contains($0) ? Character(String($0)) : "_" }.prefix(24))
    let page = safePage.isEmpty ? "page" : safePage
    return String("ios-ai.\(page).v\(sourceResultVersion).\(randomID)".prefix(100))
}
