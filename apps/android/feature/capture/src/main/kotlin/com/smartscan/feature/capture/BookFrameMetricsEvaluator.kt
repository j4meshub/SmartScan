package com.smartscan.feature.capture

import kotlin.math.abs

data class BookFrameMetrics(
    val motionScore: Double,
    val boundaryConfidence: Double,
    val spineConfidence: Double,
    val occlusionRatio: Double,
)

class BookFrameMetricsEvaluator {
    private var previousSample: IntArray? = null

    fun evaluate(
        luma: ByteArray,
        width: Int,
        height: Int,
        rowStride: Int,
        pixelStride: Int,
        sampleStep: Int = 12,
    ): BookFrameMetrics {
        require(width > 1 && height > 1)
        require(rowStride >= width && pixelStride > 0 && sampleStep > 0)
        val sample = sample(luma, width, height, rowStride, pixelStride, sampleStep)
        val previous = previousSample
        previousSample = sample
        val motionScore = if (previous == null || previous.size != sample.size) {
            0.0
        } else {
            sample.indices.sumOf { abs(sample[it] - previous[it]).toDouble() } / sample.size / 255.0
        }

        fun mean(x0: Double, x1: Double, y0: Double, y1: Double): Double {
            var total = 0L
            var count = 0L
            var y = (height * y0).toInt().coerceIn(0, height - 1)
            val yEnd = (height * y1).toInt().coerceIn(y + 1, height)
            while (y < yEnd) {
                var x = (width * x0).toInt().coerceIn(0, width - 1)
                val xEnd = (width * x1).toInt().coerceIn(x + 1, width)
                while (x < xEnd) {
                    val index = y * rowStride + x * pixelStride
                    if (index < luma.size) {
                        total += luma[index].toInt() and 0xFF
                        count += 1
                    }
                    x += sampleStep
                }
                y += sampleStep
            }
            return if (count == 0L) 0.0 else total.toDouble() / count
        }

        val boundaryContrasts = listOf(
            abs(mean(0.0, 0.08, 0.1, 0.9) - mean(0.15, 0.3, 0.1, 0.9)),
            abs(mean(0.92, 1.0, 0.1, 0.9) - mean(0.7, 0.85, 0.1, 0.9)),
            abs(mean(0.1, 0.9, 0.0, 0.08) - mean(0.1, 0.9, 0.15, 0.3)),
            abs(mean(0.1, 0.9, 0.92, 1.0) - mean(0.1, 0.9, 0.7, 0.85)),
        )
        val boundaryConfidence = boundaryContrasts.count { it >= 9.0 } / 4.0
        val sideMean = (mean(0.2, 0.4, 0.15, 0.85) + mean(0.6, 0.8, 0.15, 0.85)) / 2
        val centerMean = mean(0.47, 0.53, 0.15, 0.85)
        val spineConfidence = ((sideMean - centerMean) / 255.0).coerceIn(0.0, 1.0)

        var occluded = 0
        var observed = 0
        for (value in sample) {
            if (value < 42) occluded += 1
            observed += 1
        }
        val occlusionRatio = if (observed == 0) 1.0 else occluded.toDouble() / observed
        return BookFrameMetrics(
            motionScore = motionScore.coerceIn(0.0, 1.0),
            boundaryConfidence = boundaryConfidence,
            spineConfidence = spineConfidence,
            occlusionRatio = occlusionRatio,
        )
    }

    fun reset() {
        previousSample = null
    }

    private fun sample(
        luma: ByteArray,
        width: Int,
        height: Int,
        rowStride: Int,
        pixelStride: Int,
        step: Int,
    ): IntArray {
        val values = ArrayList<Int>()
        var y = 0
        while (y < height) {
            var x = 0
            while (x < width) {
                val index = y * rowStride + x * pixelStride
                if (index < luma.size) values += luma[index].toInt() and 0xFF
                x += step
            }
            y += step
        }
        require(values.isNotEmpty())
        return values.toIntArray()
    }
}
