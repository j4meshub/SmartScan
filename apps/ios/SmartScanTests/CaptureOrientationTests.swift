@testable import SmartScan
import AVFoundation
import ImageIO
import XCTest

final class CaptureOrientationTests: XCTestCase {
    func testDeviceOrientationProducesStableExifEvidence() {
        XCTAssertEqual(DeviceOrientationEvidence.portrait.exifOrientation, .right)
        XCTAssertEqual(DeviceOrientationEvidence.portraitUpsideDown.exifOrientation, .left)
        XCTAssertEqual(DeviceOrientationEvidence.landscapeLeft.exifOrientation, .up)
        XCTAssertEqual(DeviceOrientationEvidence.landscapeRight.exifOrientation, .down)
    }

    func testLandscapeVideoOrientationAccountsForBackCameraCoordinates() {
        XCTAssertEqual(DeviceOrientationEvidence.landscapeLeft.videoOrientation, .landscapeRight)
        XCTAssertEqual(DeviceOrientationEvidence.landscapeRight.videoOrientation, .landscapeLeft)
    }
}
