import CoreGraphics
import Foundation
import ImageIO

enum CapturePhase: Equatable, Sendable {
    case waitingPermission
    case bindingCamera
    case ready
    case capturing
    case captured(CaptureRecord)
    case failed(CaptureFailure)
}

enum CaptureFailure: String, Codable, Equatable, Sendable {
    case permissionDenied
    case cameraUnavailable
    case saveFailed
}

enum CaptureQualityIssue: String, Codable, CaseIterable, Sendable {
    case analyzing
    case tooDark
    case tooBright
    case blurry
    case glare
    case documentNotFound
}

struct FrameQuality: Codable, Equatable, Sendable {
    let brightness: Double
    let sharpness: Double
    let highlightRatio: Double
    let rectangleConfidence: Double?
    let issues: Set<CaptureQualityIssue>

    static let analyzing = FrameQuality(
        brightness: 0,
        sharpness: 0,
        highlightRatio: 0,
        rectangleConfidence: nil,
        issues: [.analyzing]
    )

    var ready: Bool { issues.isEmpty }
}

struct NormalizedQuadrilateral: Codable, Equatable, Sendable {
    let topLeft: CGPoint
    let topRight: CGPoint
    let bottomRight: CGPoint
    let bottomLeft: CGPoint
}

enum DeviceOrientationEvidence: String, Codable, Equatable, Sendable {
    case portrait
    case portraitUpsideDown
    case landscapeLeft
    case landscapeRight
    case faceUp
    case faceDown
    case unknown

    var exifOrientation: CGImagePropertyOrientation {
        switch self {
        case .portrait: .right
        case .portraitUpsideDown: .left
        case .landscapeLeft: .up
        case .landscapeRight: .down
        case .faceUp, .faceDown, .unknown: .right
        }
    }

    var videoRotationAngle: CGFloat {
        switch self {
        case .portrait: 90
        case .portraitUpsideDown: 270
        case .landscapeLeft: 0
        case .landscapeRight: 180
        case .faceUp, .faceDown, .unknown: 90
        }
    }
}

struct CaptureEvidence: Codable, Equatable, Sendable {
    let capturedAt: String
    let mode: ScanModeKind
    let deviceOrientation: DeviceOrientationEvidence
    let exifOrientation: UInt32
    let pixelWidth: Int
    let pixelHeight: Int
    let quality: FrameQuality
    let rectangle: NormalizedQuadrilateral?
}

struct CaptureRecord: Codable, Equatable, Sendable {
    let id: String
    let originalURL: URL
    let evidenceURL: URL
}

struct CaptureState: Equatable, Sendable {
    var phase: CapturePhase = .waitingPermission
    var quality: FrameQuality = .analyzing
    var rectangle: NormalizedQuadrilateral?
}

enum CaptureEvent: Equatable, Sendable {
    case permissionGranted
    case permissionDenied
    case cameraReady
    case cameraFailed
    case frameAnalyzed(FrameQuality, NormalizedQuadrilateral?)
    case shutterPressed
    case captureSucceeded(CaptureRecord)
    case captureFailed
    case continueCapturing
    case retry
}

func reduceCaptureState(_ state: CaptureState, event: CaptureEvent) -> CaptureState {
    var next = state
    switch event {
    case .permissionGranted:
        next.phase = .bindingCamera
    case .permissionDenied:
        next.phase = .failed(.permissionDenied)
    case .cameraReady:
        next.phase = .ready
    case .cameraFailed:
        next.phase = .failed(.cameraUnavailable)
    case let .frameAnalyzed(quality, rectangle):
        guard state.phase == .ready else { return state }
        next.quality = quality
        next.rectangle = rectangle
    case .shutterPressed:
        guard state.phase == .ready else { return state }
        next.phase = .capturing
    case let .captureSucceeded(record):
        guard state.phase == .capturing else { return state }
        next.phase = .captured(record)
    case .captureFailed:
        guard state.phase == .capturing else { return state }
        next.phase = .failed(.saveFailed)
    case .continueCapturing:
        guard case .captured = state.phase else { return state }
        next.phase = .ready
        next.quality = .analyzing
        next.rectangle = nil
    case .retry:
        guard case let .failed(failure) = state.phase else { return state }
        next.phase = failure == .saveFailed ? .ready : .waitingPermission
    }
    return next
}
