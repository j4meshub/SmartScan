import PDFKit
import PhotosUI
import SwiftUI
import UIKit

struct WorkspaceView: View {
    @StateObject private var store: WorkspaceStore

    init(repository: WorkspaceServicing, userID: String) {
        _store = StateObject(wrappedValue: WorkspaceStore(repository: repository, userID: userID))
    }

    var body: some View {
        List {
            if store.projects.isEmpty, !store.busy {
                ContentUnavailableView(
                    "No projects yet",
                    systemImage: "doc.viewfinder",
                    description: Text("Scan a page, then refresh this workspace.")
                )
            }
            ForEach(store.projects) { project in
                NavigationLink {
                    ProjectWorkspaceView(project: project, store: store)
                } label: {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(project.displayName).font(.headline)
                        Text("\(project.mode) · \(project.updatedAt)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
        .navigationTitle(String(localized: "Workspace"))
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await store.loadProjects() }
                } label: {
                    Label(String(localized: "Refresh"), systemImage: "arrow.clockwise")
                }
                .disabled(store.busy)
            }
        }
        .overlay { if store.busy, store.projects.isEmpty { ProgressView() } }
        .task { await store.loadProjects() }
        .alert(String(localized: "Action failed"), isPresented: errorBinding) {
            Button(String(localized: "OK")) { store.clearError() }
        } message: {
            Text(store.errorMessage ?? "")
        }
    }

    private var errorBinding: Binding<Bool> {
        Binding(get: { store.errorMessage != nil }, set: { if !$0 { store.clearError() } })
    }
}

private struct ProjectWorkspaceView: View {
    let project: WorkspaceProject
    @ObservedObject var store: WorkspaceStore
    @State private var exportFormat = WorkspaceExportFormat.pdf
    @State private var exportQuality = WorkspaceExportQuality.balanced
    @State private var includeOCRText = true

    var body: some View {
        List {
            Section(String(localized: "Pages")) {
                if store.pages.isEmpty, !store.busy {
                    Text(String(localized: "No pages are available yet."))
                        .foregroundStyle(.secondary)
                }
                ForEach(store.pages) { page in
                    VStack(alignment: .leading, spacing: 8) {
                        NavigationLink {
                            PageEditorView(pageID: page.id, store: store)
                        } label: {
                            VStack(alignment: .leading, spacing: 3) {
                                Text(String(format: String(localized: "Page %d"), page.pageNumber))
                                    .font(.headline)
                                if let side = page.bookSide {
                                    Text(bookSideLabel(side))
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                if let printedPage = page.bookPageNumberLabel {
                                    Text(String(format: String(localized: "Printed page %@"), printedPage))
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                if page.bookAssemblyIncluded == false {
                                    Text(String(localized: "Excluded from book assembly"))
                                        .font(.caption)
                                        .foregroundStyle(.red)
                                }
                                Text(pageSummary(page))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        HStack {
                            Button(String(localized: "Move up")) {
                                Task { await store.move(pageID: page.id, delta: -1) }
                            }
                            .disabled(store.busy || page.pageNumber <= 1)
                            Button(String(localized: "Move down")) {
                                Task { await store.move(pageID: page.id, delta: 1) }
                            }
                            .disabled(store.busy || page.pageNumber >= store.pages.count)
                        }
                        .buttonStyle(.borderless)
                    }
                }
            }

            if project.mode == "book" {
                Section(String(localized: "Page numbers and integrity")) {
                    if let report = store.bookIntegrity {
                        Text(
                            report.readyToAssemble
                                ? String(localized: "The book is ready to assemble.")
                                : String(
                                    format: String(localized: "%d blocking issues require attention."),
                                    report.blockingIssueCount
                                )
                        )
                        ForEach(report.issues) { issue in
                            BookIntegrityIssueRow(issue: issue, pages: store.pages, store: store)
                        }
                        Button(String(localized: "Complete book")) {
                            Task { await store.assembleBook(quality: exportQuality, includeOCRText: true) }
                        }
                        .disabled(store.busy || !report.readyToAssemble)
                    } else {
                        ProgressView()
                    }
                }
            }

            Section(String(localized: "Create export")) {
                Picker(String(localized: "Format"), selection: $exportFormat) {
                    Text("PDF").tag(WorkspaceExportFormat.pdf)
                    Text("JPG").tag(WorkspaceExportFormat.jpg)
                }
                .pickerStyle(.segmented)
                Picker(String(localized: "Quality"), selection: $exportQuality) {
                    Text(String(localized: "Clear")).tag(WorkspaceExportQuality.clear)
                    Text(String(localized: "Balanced")).tag(WorkspaceExportQuality.balanced)
                    Text(String(localized: "Small")).tag(WorkspaceExportQuality.small)
                }
                Toggle(String(localized: "Include searchable OCR text"), isOn: $includeOCRText)
                    .disabled(exportFormat != .pdf)
                Button(String(localized: "Create export")) {
                    Task {
                        await store.createExport(
                            format: exportFormat,
                            quality: exportQuality,
                            includeOCRText: includeOCRText
                        )
                    }
                }
                .disabled(store.busy || store.pages.isEmpty)
            }

            Section(String(localized: "Exports")) {
                if store.exports.isEmpty {
                    Text(String(localized: "No exports yet."))
                        .foregroundStyle(.secondary)
                }
                ForEach(store.exports) { item in
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("\(item.format.uppercased()) · \(item.quality)")
                                .font(.headline)
                            Spacer()
                            Text(exportStatus(item.status))
                                .font(.caption)
                                .foregroundStyle(item.status == "ready" ? Color.green : Color.gray)
                        }
                        if item.status != "ready" {
                            Button(String(localized: "Refresh status")) {
                                Task { await store.refresh(exportID: item.id) }
                            }
                            .disabled(store.busy)
                        }
                        ForEach(item.artifacts) { artifact in
                            HStack {
                                Text(artifact.fileName).lineLimit(1)
                                Spacer()
                                Button(String(localized: "Preview")) {
                                    Task { await store.present(artifact, sharing: false) }
                                }
                                Button(String(localized: "Share")) {
                                    Task { await store.present(artifact, sharing: true) }
                                }
                            }
                            .buttonStyle(.borderless)
                        }
                    }
                }
            }
        }
        .navigationTitle(project.displayName)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    Task { await store.refreshProject() }
                } label: {
                    Label(String(localized: "Refresh"), systemImage: "arrow.clockwise")
                }
                .disabled(store.busy)
            }
        }
        .overlay { if store.busy { ProgressView() } }
        .task(id: project.id) { await store.open(project) }
        .sheet(item: $store.presentation) { presentation in
            switch presentation {
            case let .preview(document):
                DocumentPreviewSheet(document: document)
            case let .share(document):
                ActivitySheet(items: [document.url])
            }
        }
    }

    private func pageSummary(_ page: WorkspacePage) -> String {
        let review: String
        switch page.reviewStatus {
        case "confirmed": review = String(localized: "Reviewed")
        case "not_required": review = String(localized: "No review required")
        default: review = String(localized: "Needs review")
        }
        return "\(review) · OCR: \(ocrStatus(page.ocrStatus)) · v\(page.activeResultVersion)"
    }

    private func bookSideLabel(_ side: String) -> String {
        switch side {
        case "left": return String(localized: "Left page")
        case "right": return String(localized: "Right page")
        default: return String(localized: "Single page")
        }
    }

    private func exportStatus(_ status: String) -> String {
        switch status {
        case "ready": return String(localized: "Ready")
        case "failed": return String(localized: "Failed")
        case "generating": return String(localized: "Processing")
        default: return String(localized: "Queued")
        }
    }

    private func ocrStatus(_ status: String) -> String {
        switch status {
        case "ready": return String(localized: "Ready")
        case "disabled": return String(localized: "Disabled")
        case "stale": return String(localized: "Needs refresh")
        case "legacy": return String(localized: "Legacy result")
        default: return String(localized: "Pending")
        }
    }
}

private struct BookIntegrityIssueRow: View {
    let issue: WorkspaceBookIntegrityIssue
    let pages: [WorkspacePage]
    @ObservedObject var store: WorkspaceStore
    @State private var supplementItem: PhotosPickerItem?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(issueText).font(.headline)
            if let decision = issue.decision {
                Text(String(format: String(localized: "Handled: %@"), decision))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Button(String(localized: "Reopen")) {
                    Task { await store.decideBookIntegrity(issueKey: issue.key, decision: "reopen") }
                }
            } else {
                HStack {
                    if issue.kind == "missing_page", issue.printedPageLabel != nil {
                        PhotosPicker(selection: $supplementItem, matching: .images) {
                            Text(String(localized: "Supplement page"))
                        }
                        Button(String(localized: "Confirm page does not exist")) {
                            decide("confirmed_absent")
                        }
                    } else if ["duplicate_page", "number_conflict"].contains(issue.kind) {
                        Button(String(localized: "Exclude duplicate")) { decide("exclude_duplicate") }
                        Button(String(localized: "Keep both")) { decide("keep_both") }
                    }
                    Button(String(localized: "Ignore")) { decide("ignored") }
                }
                .buttonStyle(.borderless)
            }
        }
        .onChange(of: supplementItem) { _, item in
            guard let item, let label = issue.printedPageLabel else { return }
            Task {
                if let data = try? await item.loadTransferable(type: Data.self) {
                    let insertAt = pages.first(where: { $0.id == issue.relatedPageID })?.pageNumber
                        ?? (pages.count + 1)
                    await store.supplementBookPage(
                        data: data,
                        mimeType: "image/jpeg",
                        insertAt: insertAt,
                        expectedPageLabel: label
                    )
                }
                supplementItem = nil
            }
        }
    }

    private var issueText: String {
        let text: String
        switch issue.kind {
        case "missing_page": text = String(localized: "Missing printed page")
        case "duplicate_page": text = String(localized: "Possible duplicate page")
        case "number_conflict": text = String(localized: "Page number conflict")
        case "number_order_conflict": text = String(localized: "Page number order conflict")
        case "number_gap_uncertain": text = String(localized: "Large page number gap")
        case "number_ambiguous": text = String(localized: "Ambiguous page number")
        case "expected_number_mismatch": text = String(localized: "Supplement page number mismatch")
        case "missing_side": text = String(localized: "A side is missing")
        default: text = String(localized: "Page quality requires review")
        }
        if let label = issue.printedPageLabel { return "\(text) · \(label)" }
        return text
    }

    private func decide(_ decision: String) {
        Task { await store.decideBookIntegrity(issueKey: issue.key, decision: decision) }
    }
}

private struct PageEditorView: View {
    @ObservedObject var store: WorkspaceStore
    @State private var currentPageID: String
    @State private var corners = WorkspaceCorner.fullPage
    @State private var filter = WorkspaceFilter.original
    @State private var bookRetakeItem: PhotosPickerItem?

    init(pageID: String, store: WorkspaceStore) {
        self.store = store
        _currentPageID = State(initialValue: pageID)
    }

    private var page: WorkspacePage? { store.pages.first { $0.id == currentPageID } }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if let page {
                    if page.canRetakeBookSide {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(String(localized: "Only this logical page is replaced; the other side and physical original remain unchanged."))
                            PhotosPicker(selection: $bookRetakeItem, matching: .images) {
                                Label(String(localized: "Retake this side"), systemImage: "camera.viewfinder")
                            }
                            .buttonStyle(.bordered)
                            .disabled(store.busy)
                        }
                        .padding()
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
                    }
                    if page.showsExamSuggestion, let resultVersion = page.examResultVersion {
                        VStack(alignment: .leading, spacing: 8) {
                            Text(String(localized: page.examConfidenceBand == "high"
                                ? "This may be an exam page. Exam cleanup is recommended and the original will be preserved."
                                : "This may be an exam page. Switch to exam cleanup?"))
                            Button(String(localized: "Not now")) {
                                Task {
                                    await store.dismissExamSuggestion(
                                        pageID: page.id,
                                        resultVersion: resultVersion
                                    )
                                }
                            }
                            .buttonStyle(.bordered)
                            .disabled(store.busy)
                        }
                        .padding()
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.purple.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
                    }
                    preview(page)
                    HStack {
                        Button(String(localized: "Rotate 90°")) {
                            Task { await store.rotate(pageID: page.id) }
                        }
                        .buttonStyle(.bordered)
                        Button(String(localized: "Confirm review")) {
                            Task { await store.confirm(pageID: page.id) }
                        }
                        .buttonStyle(.bordered)
                        .disabled(page.reviewStatus == "confirmed")
                    }
                    Picker(String(localized: "Filter"), selection: $filter) {
                        Text(String(localized: "Original")).tag(WorkspaceFilter.original)
                        Text(String(localized: "Enhance")).tag(WorkspaceFilter.enhance)
                        Text(String(localized: "Grayscale")).tag(WorkspaceFilter.grayscale)
                        Text(String(localized: "Black and white")).tag(WorkspaceFilter.bw)
                    }
                    .pickerStyle(.menu)
                    Text(String(localized: "Four corners")).font(.headline)
                    ForEach(corners.indices, id: \.self) { index in
                        VStack(alignment: .leading) {
                            Text(String(format: String(localized: "Corner %d"), index + 1))
                                .font(.subheadline.bold())
                            coordinateSlider(label: "X", index: index, isX: true)
                            coordinateSlider(label: "Y", index: index, isX: false)
                        }
                    }
                    Button(String(localized: "Save edit")) {
                        Task { await store.edit(pageID: page.id, corners: corners, filter: filter) }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(store.busy)
                } else {
                    ContentUnavailableView("Page unavailable", systemImage: "doc.badge.ellipsis")
                }
            }
            .padding()
        }
        .navigationTitle(page.map { String(format: String(localized: "Page %d"), $0.pageNumber) } ?? "")
        .overlay { if store.busy { ProgressView() } }
        .onChange(of: bookRetakeItem) { _, item in
            guard let item, let page else { return }
            Task {
                defer { bookRetakeItem = nil }
                guard let source = try? await item.loadTransferable(type: Data.self),
                      let image = UIImage(data: source),
                      let jpeg = image.jpegData(compressionQuality: 0.95),
                      let replacement = await store.retakeBookSide(
                          pageID: page.id,
                          data: jpeg,
                          mimeType: "image/jpeg"
                      ) else { return }
                currentPageID = replacement.id
            }
        }
    }

    @ViewBuilder
    private func preview(_ page: WorkspacePage) -> some View {
        if let document = store.previews[page.id], let image = UIImage(contentsOfFile: document.url.path) {
            Image(uiImage: image)
                .resizable()
                .scaledToFit()
                .frame(maxWidth: .infinity, minHeight: 180, maxHeight: 420)
                .accessibilityLabel(String(format: String(localized: "Page %d preview"), page.pageNumber))
        } else {
            ContentUnavailableView("Preview unavailable", systemImage: "photo")
                .frame(maxWidth: .infinity, minHeight: 180)
                .task(id: "\(page.id)-\(page.activeResultVersion)") {
                    await store.loadPreview(for: page)
                }
        }
    }

    private func coordinateSlider(label: String, index: Int, isX: Bool) -> some View {
        HStack {
            Text(label).frame(width: 24)
            Slider(
                value: Binding(
                    get: { isX ? corners[index].x : corners[index].y },
                    set: { value in
                        let current = corners[index]
                        corners[index] = WorkspaceCorner(
                            x: isX ? value : current.x,
                            y: isX ? current.y : value
                        )
                    }
                ),
                in: 0 ... 1
            )
            .accessibilityLabel(
                String(format: String(localized: "Corner %d %@"), index + 1, label)
            )
            Text(String(format: "%.2f", isX ? corners[index].x : corners[index].y))
                .monospacedDigit()
                .frame(width: 48)
        }
    }
}

private struct DocumentPreviewSheet: View {
    let document: DownloadedDocument
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Group {
                if document.mimeType == "application/pdf" || document.url.pathExtension.lowercased() == "pdf" {
                    PDFDocumentView(url: document.url)
                } else if let image = UIImage(contentsOfFile: document.url.path) {
                    ScrollView {
                        Image(uiImage: image).resizable().scaledToFit().padding()
                    }
                } else {
                    ContentUnavailableView("Preview unavailable", systemImage: "doc")
                }
            }
            .navigationTitle(document.fileName)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(String(localized: "Done")) { dismiss() }
                }
            }
        }
    }
}

private struct PDFDocumentView: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.displayMode = .singlePageContinuous
        view.document = PDFDocument(url: url)
        return view
    }

    func updateUIView(_ view: PDFView, context: Context) {
        if view.document?.documentURL != url { view.document = PDFDocument(url: url) }
    }
}

private struct ActivitySheet: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
