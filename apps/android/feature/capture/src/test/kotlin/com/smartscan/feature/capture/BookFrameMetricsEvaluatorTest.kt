package com.smartscan.feature.capture

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BookFrameMetricsEvaluatorTest {
    @Test
    fun `motion compares consecutive samples and reset requires a new baseline`() {
        val evaluator = BookFrameMetricsEvaluator()
        val first = ByteArray(48 * 48) { 220.toByte() }
        val changed = ByteArray(48 * 48) { index -> if (index % 2 == 0) 40.toByte() else 220.toByte() }

        assertEquals(0.0, evaluator.evaluate(first, 48, 48, 48, 1).motionScore)
        assertTrue(evaluator.evaluate(changed, 48, 48, 48, 1).motionScore > 0.08)
        evaluator.reset()
        assertEquals(0.0, evaluator.evaluate(changed, 48, 48, 48, 1).motionScore)
    }

    @Test
    fun `dark center line yields a measurable spine signal`() {
        val pixels = ByteArray(120 * 80) { 225.toByte() }
        for (y in 0 until 80) for (x in 56 until 64) pixels[y * 120 + x] = 30.toByte()

        val metrics = BookFrameMetricsEvaluator().evaluate(pixels, 120, 80, 120, 1, sampleStep = 4)

        assertTrue(metrics.spineConfidence > 0.035)
        assertTrue(metrics.occlusionRatio < 0.2)
    }
}
