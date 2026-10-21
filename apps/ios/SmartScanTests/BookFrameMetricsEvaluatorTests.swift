@testable import SmartScan
import XCTest

final class BookFrameMetricsEvaluatorTests: XCTestCase {
    func testMotionUsesConsecutiveFramesAndResetCreatesNewBaseline() throws {
        let evaluator = BookFrameMetricsEvaluator()
        let first = [UInt8](repeating: 220, count: 48 * 48)
        let changed = (0 ..< 48 * 48).map { $0.isMultiple(of: 2) ? UInt8(40) : UInt8(220) }

        XCTAssertEqual(try XCTUnwrap(evaluator.evaluate(luma: first, width: 48, height: 48, bytesPerRow: 48, rectangleConfidence: 0.9)).motionScore, 0)
        XCTAssertGreaterThan(try XCTUnwrap(evaluator.evaluate(luma: changed, width: 48, height: 48, bytesPerRow: 48, rectangleConfidence: 0.9)).motionScore, 0.08)
        evaluator.reset()
        XCTAssertEqual(try XCTUnwrap(evaluator.evaluate(luma: changed, width: 48, height: 48, bytesPerRow: 48, rectangleConfidence: 0.9)).motionScore, 0)
    }

    func testDarkCenterLineProducesSpineSignalWithoutLargeOcclusion() throws {
        var pixels = [UInt8](repeating: 225, count: 120 * 80)
        for y in 0 ..< 80 {
            for x in 56 ..< 64 { pixels[y * 120 + x] = 30 }
        }

        let metrics = try XCTUnwrap(
            BookFrameMetricsEvaluator().evaluate(
                luma: pixels,
                width: 120,
                height: 80,
                bytesPerRow: 120,
                rectangleConfidence: 0.9,
                sampleStep: 4
            )
        )

        XCTAssertGreaterThan(metrics.spineConfidence, 0.035)
        XCTAssertLessThan(metrics.occlusionRatio, 0.2)
        XCTAssertEqual(metrics.boundaryConfidence, 0.9)
    }
}
