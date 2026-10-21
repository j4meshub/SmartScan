import Foundation

struct BookFrameMetrics: Equatable, Sendable {
    let motionScore: Double
    let boundaryConfidence: Double
    let spineConfidence: Double
    let occlusionRatio: Double
}

final class BookFrameMetricsEvaluator {
    private var previousSample: [UInt8]?

    func evaluate(
        luma: [UInt8],
        width: Int,
        height: Int,
        bytesPerRow: Int,
        rectangleConfidence: Double?,
        sampleStep: Int = 12
    ) -> BookFrameMetrics? {
        guard width > 1, height > 1, bytesPerRow >= width, sampleStep > 0 else { return nil }
        let current = sample(luma, width: width, height: height, bytesPerRow: bytesPerRow, step: sampleStep)
        guard !current.isEmpty else { return nil }
        let motionScore: Double
        if let previousSample, previousSample.count == current.count {
            let total = zip(previousSample, current).reduce(0.0) { result, pair in
                result + Double(abs(Int(pair.0) - Int(pair.1)))
            }
            motionScore = total / Double(current.count) / 255
        } else {
            motionScore = 0
        }
        previousSample = current

        let sideMean = (
            mean(luma, width: width, height: height, bytesPerRow: bytesPerRow, x: 0.2 ..< 0.4, y: 0.15 ..< 0.85, step: sampleStep)
                + mean(luma, width: width, height: height, bytesPerRow: bytesPerRow, x: 0.6 ..< 0.8, y: 0.15 ..< 0.85, step: sampleStep)
        ) / 2
        let centerMean = mean(
            luma,
            width: width,
            height: height,
            bytesPerRow: bytesPerRow,
            x: 0.47 ..< 0.53,
            y: 0.15 ..< 0.85,
            step: sampleStep
        )
        let spineConfidence = max(0, min(1, (sideMean - centerMean) / 255))
        let occlusionRatio = Double(current.filter { $0 < 42 }.count) / Double(current.count)
        return BookFrameMetrics(
            motionScore: max(0, min(1, motionScore)),
            boundaryConfidence: max(0, min(1, rectangleConfidence ?? 0)),
            spineConfidence: spineConfidence,
            occlusionRatio: occlusionRatio
        )
    }

    func reset() { previousSample = nil }

    private func sample(
        _ luma: [UInt8],
        width: Int,
        height: Int,
        bytesPerRow: Int,
        step: Int
    ) -> [UInt8] {
        var values: [UInt8] = []
        for y in stride(from: 0, to: height, by: step) {
            for x in stride(from: 0, to: width, by: step) {
                let index = y * bytesPerRow + x
                if index < luma.count { values.append(luma[index]) }
            }
        }
        return values
    }

    private func mean(
        _ luma: [UInt8],
        width: Int,
        height: Int,
        bytesPerRow: Int,
        x: Range<Double>,
        y: Range<Double>,
        step: Int
    ) -> Double {
        let startX = max(0, min(width - 1, Int(Double(width) * x.lowerBound)))
        let endX = max(startX + 1, min(width, Int(Double(width) * x.upperBound)))
        let startY = max(0, min(height - 1, Int(Double(height) * y.lowerBound)))
        let endY = max(startY + 1, min(height, Int(Double(height) * y.upperBound)))
        var total = 0
        var count = 0
        for row in stride(from: startY, to: endY, by: step) {
            for column in stride(from: startX, to: endX, by: step) {
                let index = row * bytesPerRow + column
                if index < luma.count {
                    total += Int(luma[index])
                    count += 1
                }
            }
        }
        return count == 0 ? 0 : Double(total) / Double(count)
    }
}
