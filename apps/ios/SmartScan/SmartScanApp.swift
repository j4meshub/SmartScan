import SwiftUI

@main
struct SmartScanApp: App {
    var body: some Scene {
        WindowGroup {
            HomeView()
        }
    }
}

enum ScanModeKind: String, CaseIterable {
    case document
    case exam
    case book

    var title: String {
        switch self {
        case .document: String(localized: "Smart Scan")
        case .exam: String(localized: "Clean Exam")
        case .book: String(localized: "Scan a Book")
        }
    }

    var subtitle: String {
        switch self {
        case .document: String(localized: "Auto crop · Rotate · Enhance")
        case .exam: "✦"
        case .book: "◫"
        }
    }
}

struct HomeView: View {
    private let ink = Color(red: 0.067, green: 0.094, blue: 0.153)
    private let paper = Color(red: 0.957, green: 0.945, blue: 0.922)

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    HStack {
                        Text("⌗  SmartScan").font(.headline.bold())
                        Spacer()
                        HStack(spacing: 4) {
                            Text("●")
                            Text(String(localized: "READY"))
                        }
                        .font(.caption2.bold())
                        .padding(.horizontal, 12)
                        .padding(.vertical, 8)
                        .background(.white)
                        .clipShape(Capsule())
                        .foregroundStyle(.green)
                    }
                    Spacer().frame(height: 30)
                    Text(String(localized: "Capture every detail on paper."))
                        .font(.system(size: 47, weight: .black, design: .rounded)).tracking(-2.0)
                    ScanMode(kind: .document, dark: true)
                    HStack(spacing: 12) {
                        ScanMode(kind: .exam)
                        ScanMode(kind: .book)
                    }
                }
                .padding(20)
            }
            .background(paper.ignoresSafeArea())
            .tint(ink)
        }
    }
}

struct ScanMode: View {
    let kind: ScanModeKind
    var dark = false

    var body: some View {
        Button(action: {}) {
            VStack(alignment: .leading) {
                Text("⌗")
                    .font(.title2)
                    .padding(10)
                    .background(Color(red: 0.72, green: 0.97, blue: 0.83))
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                Spacer()
                Text(kind.title).font(.title3.bold())
                Text(kind.subtitle).font(.caption).opacity(0.7)
            }
            .frame(maxWidth: .infinity, minHeight: 120, alignment: .leading)
            .padding(18)
            .background(dark ? Color(red: 0.067, green: 0.094, blue: 0.153) : .white)
            .foregroundStyle(dark ? .white : .primary)
            .clipShape(RoundedRectangle(cornerRadius: 22))
        }
        .buttonStyle(.plain)
    }
}

