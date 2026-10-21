import AVFoundation
import SwiftUI

struct CaptureView: View {
    let mode: ScanModeKind
    let userID: String
    let uploads: UploadCoordinator
    private let localProjectID: String
    @StateObject private var camera: CameraController
    @State private var exposure = 0.0
    @State private var queueMessage: String?

    init(mode: ScanModeKind, userID: String, uploads: UploadCoordinator) {
        self.mode = mode
        self.userID = userID
        self.uploads = uploads
        localProjectID = UUID().uuidString.lowercased()
        _camera = StateObject(wrappedValue: CameraController(userID: userID, mode: mode))
    }

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            CameraPreview(session: camera.session, onFocus: camera.focus)
                .ignoresSafeArea()
            if let rectangle = camera.state.rectangle {
                RectangleGuide(rectangle: rectangle)
                    .stroke(.green, style: StrokeStyle(lineWidth: 3, lineJoin: .round))
                    .allowsHitTesting(false)
            }
            VStack {
                qualityBanner
                Spacer()
                controls
            }
            .padding()
        }
        .navigationTitle(mode.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbarColorScheme(.dark, for: .navigationBar)
        .onAppear {
            camera.updateOrientation(DeviceOrientationEvidence(UIDevice.current.orientation))
            camera.start()
        }
        .onDisappear { camera.stop() }
        .onReceive(NotificationCenter.default.publisher(for: UIDevice.orientationDidChangeNotification)) { _ in
            camera.updateOrientation(DeviceOrientationEvidence(UIDevice.current.orientation))
        }
        .onChange(of: camera.state.phase) { _, phase in
            guard case let .captured(record) = phase else { return }
            Task {
                let enqueued = await uploads.enqueue(
                    record: record,
                    ownerUserID: userID,
                    localProjectID: localProjectID,
                    title: mode.title,
                    mode: mode
                )
                await MainActor.run {
                    queueMessage = enqueued
                        ? String(localized: "Original saved and queued")
                        : String(localized: "Original saved, but could not be queued")
                }
            }
        }
    }

    private var qualityBanner: some View {
        Text(qualityMessage)
            .font(.subheadline.bold())
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(.black.opacity(0.65))
            .foregroundStyle(.white)
            .clipShape(Capsule())
            .accessibilityIdentifier("capture-quality-message")
    }

    private var controls: some View {
        VStack(spacing: 16) {
            HStack {
                Image(systemName: "sun.min")
                Slider(value: $exposure, in: -1 ... 1) { editing in
                    if !editing { camera.setExposure(exposure) }
                }
                .accessibilityLabel(String(localized: "Exposure"))
                Image(systemName: "sun.max")
            }
            .foregroundStyle(.white)

            switch camera.state.phase {
            case .captured:
                Button(String(localized: "Continue scanning")) {
                    queueMessage = nil
                    camera.continueCapturing()
                }
                    .buttonStyle(.borderedProminent)
            case let .failed(failure):
                Text(failureMessage(failure)).foregroundStyle(.white)
                Button(String(localized: "Retry")) { camera.retry() }
                    .buttonStyle(.borderedProminent)
            default:
                Button {
                    camera.capture(orientation: DeviceOrientationEvidence(UIDevice.current.orientation))
                } label: {
                    Circle()
                        .fill(.white)
                        .frame(width: 74, height: 74)
                        .overlay(Circle().stroke(.black.opacity(0.3), lineWidth: 3).padding(5))
                }
                .disabled(camera.state.phase != .ready)
                .accessibilityLabel(String(localized: "Capture photo"))
            }
        }
        .padding()
        .background(.black.opacity(0.45))
        .clipShape(RoundedRectangle(cornerRadius: 22))
    }

    private var qualityMessage: String {
        switch camera.state.phase {
        case .waitingPermission: return String(localized: "Waiting for camera permission…")
        case .bindingCamera: return String(localized: "Starting camera…")
        case .capturing: return String(localized: "Saving original…")
        case .captured: return queueMessage ?? String(localized: "Original saved")
        case .failed: return String(localized: "Camera unavailable")
        case .ready:
            if camera.state.quality.ready { return String(localized: "Ready to capture") }
            let priority: [CaptureQualityIssue] = [
                .tooDark, .tooBright, .blurry, .glare, .documentNotFound, .analyzing,
            ]
            let issue = priority.first { camera.state.quality.issues.contains($0) }
            switch issue {
            case .tooDark: return String(localized: "Too dark")
            case .tooBright: return String(localized: "Too bright")
            case .blurry: return String(localized: "Hold steady and tap to focus")
            case .glare: return String(localized: "Possible glare")
            case .documentNotFound: return String(localized: "Align the full document")
            default: return String(localized: "Analyzing image…")
            }
        }
    }

    private func failureMessage(_ failure: CaptureFailure) -> String {
        switch failure {
        case .permissionDenied: String(localized: "Camera permission is required.")
        case .cameraUnavailable: String(localized: "The rear camera is unavailable.")
        case .saveFailed: String(localized: "The original could not be saved.")
        }
    }
}

private struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession
    let onFocus: (CGPoint) -> Void

    func makeUIView(context: Context) -> PreviewView {
        let view = PreviewView()
        view.previewLayer.session = session
        view.previewLayer.videoGravity = .resizeAspectFill
        view.onFocus = onFocus
        return view
    }

    func updateUIView(_ uiView: PreviewView, context: Context) {
        uiView.previewLayer.session = session
        uiView.onFocus = onFocus
    }
}

private final class PreviewView: UIView {
    override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
    var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    var onFocus: ((CGPoint) -> Void)?

    override init(frame: CGRect) {
        super.init(frame: frame)
        addGestureRecognizer(UITapGestureRecognizer(target: self, action: #selector(tapped(_:))))
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    @objc private func tapped(_ gesture: UITapGestureRecognizer) {
        onFocus?(previewLayer.captureDevicePointConverted(fromLayerPoint: gesture.location(in: self)))
    }
}

private struct RectangleGuide: Shape {
    let rectangle: NormalizedQuadrilateral

    func path(in rect: CGRect) -> Path {
        func point(_ normalized: CGPoint) -> CGPoint {
            CGPoint(x: normalized.x * rect.width, y: (1 - normalized.y) * rect.height)
        }
        var path = Path()
        path.move(to: point(rectangle.topLeft))
        path.addLine(to: point(rectangle.topRight))
        path.addLine(to: point(rectangle.bottomRight))
        path.addLine(to: point(rectangle.bottomLeft))
        path.closeSubpath()
        return path
    }
}
