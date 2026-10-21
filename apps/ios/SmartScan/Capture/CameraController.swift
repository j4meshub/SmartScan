import AVFoundation
import Combine
import CoreMedia
import Foundation
import ImageIO
import UIKit
import Vision

final class CameraController: NSObject, ObservableObject {
    @Published private(set) var state = CaptureState()
    let session = AVCaptureSession()

    private let userID: String
    private let mode: ScanModeKind
    private let store: OriginalCaptureStoring
    private let evaluator = FrameQualityEvaluator()
    private let sessionQueue = DispatchQueue(label: "com.j4meshub.smartscan.camera.session")
    private let analysisQueue = DispatchQueue(label: "com.j4meshub.smartscan.camera.analysis")
    private let photoOutput = AVCapturePhotoOutput()
    private var camera: AVCaptureDevice?
    private var configured = false
    private var lastAnalysisTime = Date.distantPast
    private let orientationLock = NSLock()
    private var currentOrientation: DeviceOrientationEvidence = .portrait
    private var pendingCaptureOrientation: DeviceOrientationEvidence = .portrait
    private var pendingQuality: FrameQuality = .analyzing
    private var pendingRectangle: NormalizedQuadrilateral?

    init(userID: String, mode: ScanModeKind, store: OriginalCaptureStoring = FileOriginalCaptureStore()) {
        self.userID = userID
        self.mode = mode
        self.store = store
        super.init()
    }

    func start() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            transition(.permissionGranted)
            configureAndStart()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.transition(granted ? .permissionGranted : .permissionDenied)
                    if granted { self.configureAndStart() }
                }
            }
        default:
            transition(.permissionDenied)
        }
    }

    func stop() {
        sessionQueue.async { [weak self] in
            guard let self, self.session.isRunning else { return }
            self.session.stopRunning()
        }
    }

    func capture(orientation: DeviceOrientationEvidence) {
        guard state.phase == .ready else { return }
        updateOrientation(orientation)
        pendingCaptureOrientation = orientation
        pendingQuality = state.quality
        pendingRectangle = state.rectangle
        transition(.shutterPressed)
        sessionQueue.async { [weak self] in
            guard let self else { return }
            if let connection = self.photoOutput.connection(with: .video),
               connection.isVideoRotationAngleSupported(orientation.videoRotationAngle) {
                connection.videoRotationAngle = orientation.videoRotationAngle
            }
            let settings = AVCapturePhotoSettings(format: [AVVideoCodecKey: AVVideoCodecType.jpeg])
            settings.photoQualityPrioritization = .quality
            self.photoOutput.capturePhoto(with: settings, delegate: self)
        }
    }

    func continueCapturing() {
        transition(.continueCapturing)
    }

    func retry() {
        let failed = state.phase
        transition(.retry)
        if failed == .failed(.saveFailed) { return }
        start()
    }

    func updateOrientation(_ orientation: DeviceOrientationEvidence) {
        guard orientation != .unknown, orientation != .faceUp, orientation != .faceDown else { return }
        orientationLock.lock()
        currentOrientation = orientation
        orientationLock.unlock()
    }

    func focus(at devicePoint: CGPoint) {
        sessionQueue.async { [weak self] in
            guard let camera = self?.camera else { return }
            do {
                try camera.lockForConfiguration()
                if camera.isFocusPointOfInterestSupported {
                    camera.focusPointOfInterest = devicePoint
                    camera.focusMode = .autoFocus
                }
                if camera.isExposurePointOfInterestSupported {
                    camera.exposurePointOfInterest = devicePoint
                    camera.exposureMode = .continuousAutoExposure
                }
                camera.unlockForConfiguration()
            } catch {
                return
            }
        }
    }

    func setExposure(_ normalized: Double) {
        sessionQueue.async { [weak self] in
            guard let camera = self?.camera else { return }
            let clamped = max(-1, min(1, normalized))
            let minimum = Double(camera.minExposureTargetBias)
            let maximum = Double(camera.maxExposureTargetBias)
            let bias = Float(minimum + ((clamped + 1) / 2) * (maximum - minimum))
            do {
                try camera.lockForConfiguration()
                camera.setExposureTargetBias(bias)
                camera.unlockForConfiguration()
            } catch {
                return
            }
        }
    }

    private func configureAndStart() {
        sessionQueue.async { [weak self] in
            guard let self else { return }
            do {
                if self.configured {
                    if !self.session.isRunning { self.session.startRunning() }
                    DispatchQueue.main.async { self.transition(.cameraReady) }
                    return
                }
                self.session.beginConfiguration()
                var configurationOpen = true
                defer {
                    if configurationOpen { self.session.commitConfiguration() }
                }
                self.session.sessionPreset = .photo
                guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back) else {
                    throw CaptureFailure.cameraUnavailable
                }
                let input = try AVCaptureDeviceInput(device: camera)
                guard self.session.canAddInput(input), self.session.canAddOutput(self.photoOutput) else {
                    throw CaptureFailure.cameraUnavailable
                }
                self.session.addInput(input)
                self.session.addOutput(self.photoOutput)
                let videoOutput = AVCaptureVideoDataOutput()
                videoOutput.alwaysDiscardsLateVideoFrames = true
                videoOutput.videoSettings = [
                    kCVPixelBufferPixelFormatTypeKey as String:
                        kCVPixelFormatType_420YpCbCr8BiPlanarFullRange,
                ]
                videoOutput.setSampleBufferDelegate(self, queue: self.analysisQueue)
                guard self.session.canAddOutput(videoOutput) else { throw CaptureFailure.cameraUnavailable }
                self.session.addOutput(videoOutput)
                self.camera = camera
                self.session.commitConfiguration()
                configurationOpen = false
                self.configured = true
                self.session.startRunning()
                DispatchQueue.main.async { self.transition(.cameraReady) }
            } catch {
                DispatchQueue.main.async { self.transition(.cameraFailed) }
            }
        }
    }

    private func transition(_ event: CaptureEvent) {
        state = reduceCaptureState(state, event: event)
    }
}

extension CameraController: AVCapturePhotoCaptureDelegate {
    func photoOutput(
        _ output: AVCapturePhotoOutput,
        didFinishProcessingPhoto photo: AVCapturePhoto,
        error: Error?
    ) {
        guard error == nil, let data = photo.fileDataRepresentation() else {
            DispatchQueue.main.async { self.transition(.captureFailed) }
            return
        }
        let dimensions = photo.resolvedSettings.photoDimensions
        let rawExif = (photo.metadata[kCGImagePropertyOrientation as String] as? NSNumber)?.uint32Value
            ?? pendingCaptureOrientation.exifOrientation.rawValue
        let evidence = CaptureEvidence(
            capturedAt: ISO8601DateFormatter().string(from: Date()),
            mode: mode,
            deviceOrientation: pendingCaptureOrientation,
            exifOrientation: rawExif,
            pixelWidth: Int(dimensions.width),
            pixelHeight: Int(dimensions.height),
            quality: pendingQuality,
            rectangle: pendingRectangle
        )
        Task {
            do {
                let record = try await store.saveOriginal(data, evidence: evidence, userID: userID)
                await MainActor.run { self.transition(.captureSucceeded(record)) }
            } catch {
                await MainActor.run { self.transition(.captureFailed) }
            }
        }
    }
}

extension CameraController: AVCaptureVideoDataOutputSampleBufferDelegate {
    func captureOutput(
        _ output: AVCaptureOutput,
        didOutput sampleBuffer: CMSampleBuffer,
        from connection: AVCaptureConnection
    ) {
        let now = Date()
        guard now.timeIntervalSince(lastAnalysisTime) >= 0.25,
              let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lastAnalysisTime = now

        let orientation = orientationSnapshot().exifOrientation
        let detection = detectRectangle(in: pixelBuffer, orientation: orientation)
        guard let quality = analyzeLuma(pixelBuffer, rectangleConfidence: detection?.confidence) else { return }
        DispatchQueue.main.async { [weak self] in
            self?.transition(.frameAnalyzed(quality, detection?.quadrilateral))
        }
    }

    private func analyzeLuma(_ pixelBuffer: CVPixelBuffer, rectangleConfidence: Double?) -> FrameQuality? {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }
        guard CVPixelBufferGetPlaneCount(pixelBuffer) > 0,
              let base = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0) else { return nil }
        let width = CVPixelBufferGetWidthOfPlane(pixelBuffer, 0)
        let height = CVPixelBufferGetHeightOfPlane(pixelBuffer, 0)
        let bytesPerRow = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0)
        let bytes = Array(UnsafeBufferPointer(start: base.assumingMemoryBound(to: UInt8.self), count: bytesPerRow * height))
        return try? evaluator.evaluate(
            luma: bytes,
            width: width,
            height: height,
            bytesPerRow: bytesPerRow,
            rectangleConfidence: rectangleConfidence
        )
    }

    private func detectRectangle(
        in pixelBuffer: CVPixelBuffer,
        orientation: CGImagePropertyOrientation
    ) -> DetectedRectangle? {
        let request = VNDetectRectanglesRequest()
        request.maximumObservations = 1
        request.minimumConfidence = 0.6
        request.minimumAspectRatio = 0.2
        request.quadratureTolerance = 30
        try? VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: orientation).perform([request])
        guard let observation = request.results?.first else { return nil }
        return DetectedRectangle(
            quadrilateral: NormalizedQuadrilateral(
                topLeft: observation.topLeft,
                topRight: observation.topRight,
                bottomRight: observation.bottomRight,
                bottomLeft: observation.bottomLeft
            ),
            confidence: Double(observation.confidence)
        )
    }

    private func orientationSnapshot() -> DeviceOrientationEvidence {
        orientationLock.lock()
        defer { orientationLock.unlock() }
        return currentOrientation
    }
}

private struct DetectedRectangle {
    let quadrilateral: NormalizedQuadrilateral
    let confidence: Double
}

extension CaptureFailure: Error {}

extension DeviceOrientationEvidence {
    init(_ orientation: UIDeviceOrientation) {
        switch orientation {
        case .portrait: self = .portrait
        case .portraitUpsideDown: self = .portraitUpsideDown
        case .landscapeLeft: self = .landscapeLeft
        case .landscapeRight: self = .landscapeRight
        case .faceUp: self = .faceUp
        case .faceDown: self = .faceDown
        default: self = .unknown
        }
    }
}
