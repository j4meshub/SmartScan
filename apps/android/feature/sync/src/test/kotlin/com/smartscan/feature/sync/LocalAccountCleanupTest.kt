package com.smartscan.feature.sync

import java.nio.file.Files
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalAccountCleanupTest {
    @Test
    fun `cleanup deletes only files below private capture root`() {
        val temporaryRoot = Files.createTempDirectory("smartscan-cleanup-test").toFile()
        try {
            val captureRoot = temporaryRoot.resolve("captures/originals").apply { mkdirs() }
            val owned = captureRoot.resolve("owned.jpg").apply { writeBytes(ByteArray(32) { 1 }) }
            val outside = temporaryRoot.resolve("outside.jpg").apply { writeBytes(ByteArray(32) { 2 }) }

            assertTrue(deletePrivateCapture(captureRoot, owned.absolutePath))
            assertFalse(owned.exists())
            assertFalse(deletePrivateCapture(captureRoot, outside.absolutePath))
            assertTrue(outside.exists())
            assertFalse(deletePrivateCapture(captureRoot, captureRoot.absolutePath))
        } finally {
            temporaryRoot.deleteRecursively()
        }
    }
}
