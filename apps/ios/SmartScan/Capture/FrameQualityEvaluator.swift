import Foundation

struct CaptureQualityThresholds: Equatable, Sendable {
    let minimumBrightness: Double
    let maximumBrightness: Double
    let minimumSharpness: Double
    let maximumHighlightRatio: Double
    let minimumRectangleConfidence: Double

    init(
        minimumBrightness: Double = 0.18,
        maximumBrightness: Double = 0.88,
        minimumSharpness: Double = 0.055,
        maximumHighlightRatio: Double = 0.12,
        minimumRectangleConfidence: Double = 0.6
    ) {
        self.minimumBrightness = minimumBrightness
        self.maximumBrightness = maximumBrightness
        self.minimumSharpness = minimumSharpness
        self.maximumHighlightRatio = maximumHighlightRatio
        self.minimumRectangleConfidence = minimumRectangleConfidence
    }
}

enum FrameQualityError: Error, Equatable {
    case invalidGeometry
    case insufficientPixels
}

struct FrameQualityEvaluator: Sendable {
    let thresholds: CaptureQualityThresholds

    init(thresholds: CaptureQualityThresholds = CaptureQualityThresholds()) {
        self.thresholds = thresholds
    }

    func evaluate(
        luma: [UInt8],
        width: Int,
        height: Int,
        bytesPerRow: Int,
        sampleStep: Int = 4,
        rectangleConfidence: Double?
    ) throws -> FrameQuality {
        guard width > 1, height > 1, bytesPerRow >= width, sampleStep > 0 else {
            throw FrameQualityError.invalidGeometry
        }
        var samples = 0
        var total = 0
        var highlights = 0
        var gradientTotal = 0
        var gradientSamples = 0

        for y in stride(from: 0, to: height, by: sampleStep) {
            for x in stride(from: 0, to: width, by: sampleStep) {
                let index = y * bytesPerRow + x
                guard index < luma.count else { continue }
                let value = Int(luma[index])
                samples += 1
                total += value
                if value >= 250 { highlights += 1 }

                let right = index + sampleStep
                if x + sampleStep < width, right < luma.count {
                    gradientTotal += abs(value - Int(luma[right]))
                    gradientSamples += 1
                }
                let lower = index + sampleStep * bytesPerRow
                if y + sampleStep < height, lower < luma.count {
                    gradientTotal += abs(value - Int(luma[lower]))
                    gradientSamples += 1
                }
            }
        }
        guard samples > 0 else { throw FrameQualityError.insufficientPixels }

        let brightness = Double(total) / Double(samples) / 255
        let sharpness = gradientSamples == 0 ? 0 : Double(gradientTotal) / Double(gradientSamples) / 255
        let highlightRatio = Double(highlights) / Double(samples)
        var issues = Set<CaptureQualityIssue>()
        if brightness < thresholds.minimumBrightness { issues.insert(.tooDark) }
        if brightness > thresholds.maximumBrightness { issues.insert(.tooBright) }
        if sharpness < thresholds.minimumSharpness { issues.insert(.blurry) }
        if highlightRatio > thresholds.maximumHighlightRatio { issues.insert(.glare) }
        if (rectangleConfidence ?? 0) < thresholds.minimumRectangleConfidence {
            issues.insert(.documentNotFound)
        }
        return FrameQuality(
            brightness: brightness,
            sharpness: sharpness,
            highlightRatio: highlightRatio,
            rectangleConfidence: rectangleConfidence,
            issues: issues
        )
    }
}
