package com.smartscan.feature.workspace

import com.smartscan.core.model.AiCapabilities
import com.smartscan.core.model.AiEnhancement
import kotlin.math.roundToInt

private val RunningAiStatuses = setOf("queued", "processing")

internal fun latestAiEnhancement(
    enhancements: List<AiEnhancement>,
    sourceVersion: Int,
    enhancementKind: String,
): AiEnhancement? = enhancements
    .filter { it.enhancementKind == enhancementKind }
    .firstOrNull { it.sourceResultVersion == sourceVersion }
    ?: enhancements.firstOrNull { it.enhancementKind == enhancementKind }

internal fun shouldPollAiEnhancements(enhancements: List<AiEnhancement>): Boolean =
    enhancements.any { it.status in RunningAiStatuses }

internal fun canDecideAiEnhancement(enhancement: AiEnhancement?, activeResultVersion: Int): Boolean =
    enhancement?.status == "candidate_ready" && enhancement.sourceResultVersion == activeResultVersion

internal fun supportsAiEnhancement(capabilities: AiCapabilities?, enhancementKind: String): Boolean = when (enhancementKind) {
    "recommended" -> capabilities?.enhancementKinds?.contains("recommended") == true
    "complex_ocr" -> capabilities?.enhancementKinds?.contains("complex_ocr") == true &&
        capabilities.taskTypes.contains("ocr_formula")
    else -> false
}

internal fun aiConfidencePercent(value: Double?): Int? = value
    ?.takeIf { it.isFinite() }
    ?.coerceIn(0.0, 1.0)
    ?.times(100)
    ?.roundToInt()

