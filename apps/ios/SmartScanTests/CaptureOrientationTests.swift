@testable import SmartScan
import ImageIO
import XCTest

final class CaptureOrientationTests: XCTestCase {
    func testDeviceOrientationProducesStableExifEvidence() {
        XCTAssertEqual(DeviceOrientationEvidence.portrait.exifOrientation, .right)
        XCTAssertEqual(DeviceOrientationEvidence.portraitUpsideDown.exifOrientation, .left)
        XCTAssertEqual(DeviceOrientationEvidence.landscapeLeft.exifOrientation, .up)
        XCTAssertEqual(DeviceOrientationEvidence.landscapeRight.exifOrientation, .down)
    }

    func testRotationAnglesUseIOS17ConnectionCoordinates() {
        XCTAssertEqual(DeviceOrientationEvidence.portrait.videoRotationAngle, 90)
        XCTAssertEqual(DeviceOrientationEvidence.portraitUpsideDown.videoRotationAngle, 270)
        XCTAssertEqual(DeviceOrientationEvidence.landscapeLeft.videoRotationAngle, 0)
        XCTAssertEqual(DeviceOrientationEvidence.landscapeRight.videoRotationAngle, 180)
    }
}
