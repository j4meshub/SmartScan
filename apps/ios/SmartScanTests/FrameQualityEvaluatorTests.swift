@testable import SmartScan
import XCTest

final class FrameQualityEvaluatorTests: XCTestCase {
    private let evaluator = FrameQualityEvaluator()

    func testDarkUniformFrameReportsExposureSharpnessAndDocumentWarnings() throws {
        let quality = try evaluator.evaluate(
            luma: [UInt8](repeating: 18, count: 64 * 64),
            width: 64,
            height: 64,
            bytesPerRow: 64,
            rectangleConfidence: nil
        )

        XCTAssertTrue(quality.issues.contains(.tooDark))
        XCTAssertTrue(quality.issues.contains(.blurry))
        XCTAssertTrue(quality.issues.contains(.documentNotFound))
        XCTAssertFalse(quality.ready)
    }

    func testBrightClippedFrameReportsOverexposureAndGlare() throws {
        let quality = try evaluator.evaluate(
            luma: [UInt8](repeating: 255, count: 64 * 64),
            width: 64,
            height: 64,
            bytesPerRow: 64,
            rectangleConfidence: 0.9
        )

        XCTAssertTrue(quality.issues.contains(.tooBright))
        XCTAssertTrue(quality.issues.contains(.glare))
    }

    func testTexturedBalancedFrameWithRectangleIsReady() throws {
        let pixels = (0 ..< 64 * 64).map { index -> UInt8 in
            let x = index % 64
            let y = index / 64
            return (x / 4 + y / 4).isMultiple(of: 2) ? 45 : 215
        }

        let quality = try evaluator.evaluate(
            luma: pixels,
            width: 64,
            height: 64,
            bytesPerRow: 64,
            rectangleConfidence: 0.95
        )

        XCTAssertTrue(quality.ready)
        XCTAssertEqual(quality.rectangleConfidence, 0.95)
    }

    func testInvalidGeometryIsRejected() {
        XCTAssertThrowsError(
            try evaluator.evaluate(
                luma: [0, 1, 2, 3],
                width: 1,
                height: 4,
                bytesPerRow: 1,
                rectangleConfidence: nil
            )
        ) { error in
            XCTAssertEqual(error as? FrameQualityError, .invalidGeometry)
        }
    }
}
