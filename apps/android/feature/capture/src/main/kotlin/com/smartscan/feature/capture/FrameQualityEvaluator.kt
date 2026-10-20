package com.smartscan.feature.capture

data class QualityThresholds(
    val minimumBrightness: Double = 0.18,
    val maximumBrightness: Double = 0.88,
    val minimumSharpness: Double = 0.055,
    val maximumHighlightRatio: Double = 0.12,
)

class FrameQualityEvaluator(
    private val thresholds: QualityThresholds = QualityThresholds(),
) {
    fun evaluate(
        luma: ByteArray,
        width: Int,
        height: Int,
        rowStride: Int,
        pixelStride: Int,
        sampleStep: Int = 4,
    ): FrameQuality {
        require(width > 1 && height > 1) { "帧尺寸必须大于 1" }
        require(rowStride >= width) { "行跨度不能小于帧宽" }
        require(pixelStride > 0) { "像素跨度必须为正数" }
        require(sampleStep > 0) { "采样步长必须为正数" }

        var samples = 0L
        var lumaTotal = 0L
        var highlightSamples = 0L
        var gradientTotal = 0L
        var gradientSamples = 0L

        var y = 0
        while (y < height) {
            var x = 0
            while (x < width) {
                val index = y * rowStride + x * pixelStride
                if (index >= luma.size) break
                val value = luma[index].toInt() and 0xFF
                lumaTotal += value
                samples += 1
                if (value >= 250) highlightSamples += 1

                val rightIndex = index + sampleStep * pixelStride
                if (x + sampleStep < width && rightIndex < luma.size) {
                    gradientTotal += kotlin.math.abs(value - (luma[rightIndex].toInt() and 0xFF))
                    gradientSamples += 1
                }
                val lowerIndex = index + sampleStep * rowStride
                if (y + sampleStep < height && lowerIndex < luma.size) {
                    gradientTotal += kotlin.math.abs(value - (luma[lowerIndex].toInt() and 0xFF))
                    gradientSamples += 1
                }
                x += sampleStep
            }
            y += sampleStep
        }

        require(samples > 0) { "帧中没有可用亮度样本" }
        val brightness = lumaTotal.toDouble() / samples / 255.0
        val sharpness = if (gradientSamples == 0L) 0.0 else gradientTotal.toDouble() / gradientSamples / 255.0
        val highlightRatio = highlightSamples.toDouble() / samples
        val issues = buildSet {
            if (brightness < thresholds.minimumBrightness) add(QualityIssue.TOO_DARK)
            if (brightness > thresholds.maximumBrightness) add(QualityIssue.TOO_BRIGHT)
            if (sharpness < thresholds.minimumSharpness) add(QualityIssue.BLURRY)
            if (highlightRatio > thresholds.maximumHighlightRatio) add(QualityIssue.GLARE)
        }
        return FrameQuality(brightness, sharpness, highlightRatio, issues)
    }
}
