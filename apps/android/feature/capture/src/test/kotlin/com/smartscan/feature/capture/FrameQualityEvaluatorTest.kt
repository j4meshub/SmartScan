package com.smartscan.feature.capture

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class FrameQualityEvaluatorTest {
    private val evaluator = FrameQualityEvaluator()

    @Test
    fun `dark uniform frame reports exposure and sharpness warnings`() {
        val quality = evaluator.evaluate(ByteArray(64 * 64) { 18 }, 64, 64, 64, 1)

        assertTrue(QualityIssue.TOO_DARK in quality.issues)
        assertTrue(QualityIssue.BLURRY in quality.issues)
        assertFalse(quality.ready)
    }

    @Test
    fun `bright clipped frame reports overexposure and glare`() {
        val quality = evaluator.evaluate(ByteArray(64 * 64) { 255.toByte() }, 64, 64, 64, 1)

        assertTrue(QualityIssue.TOO_BRIGHT in quality.issues)
        assertTrue(QualityIssue.GLARE in quality.issues)
    }

    @Test
    fun `textured balanced frame is ready`() {
        val pixels = ByteArray(64 * 64) { index ->
            val x = index % 64
            val y = index / 64
            if ((x / 4 + y / 4) % 2 == 0) 45.toByte() else 215.toByte()
        }

        val quality = evaluator.evaluate(pixels, 64, 64, 64, 1)

        assertTrue(quality.ready)
        assertTrue(quality.issues.isEmpty())
    }

    @Test(expected = IllegalArgumentException::class)
    fun `invalid frame geometry is rejected`() {
        evaluator.evaluate(ByteArray(4), 1, 4, 1, 1)
    }
}
