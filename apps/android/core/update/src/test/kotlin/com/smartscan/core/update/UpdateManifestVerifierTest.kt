package com.smartscan.core.update

import java.nio.file.Path
import java.security.KeyPairGenerator
import java.security.Signature
import java.util.Base64
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertInstanceOf
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir

class UpdateManifestVerifierTest {
    @TempDir
    lateinit var temporaryDirectory: Path

    @Test
    fun `valid signed manifest exposes mandatory update`() {
        val fixture = fixture(versionCode = 5, minimumSupported = 3)
        val result = fixture.verifier.verify(fixture.payload, fixture.signature, "com.smartscan.app", 2)

        val available = assertInstanceOf(UpdateVerificationResult.Available::class.java, result)
        assertTrue(available.update.mandatory)
        assertEquals(5, available.update.manifest.versionCode)
    }

    @Test
    fun `tampered manifest and wrong package are rejected`() {
        val fixture = fixture()
        val tampered = fixture.payload.decodeToString().replace("1.1.0", "9.9.0").encodeToByteArray()

        assertInstanceOf(
            UpdateVerificationResult.Rejected::class.java,
            fixture.verifier.verify(tampered, fixture.signature, "com.smartscan.app", 1),
        )
        assertInstanceOf(
            UpdateVerificationResult.Rejected::class.java,
            fixture.verifier.verify(fixture.payload, fixture.signature, "com.other.app", 1),
        )
    }

    @Test
    fun `current or older version is not offered`() {
        val fixture = fixture(versionCode = 2)
        assertEquals(
            UpdateVerificationResult.Current,
            fixture.verifier.verify(fixture.payload, fixture.signature, "com.smartscan.app", 2),
        )
    }

    @Test
    fun `apk hash accepts exact file and rejects changed bytes`() {
        val apk = temporaryDirectory.resolve("SmartScan.apk").toFile().apply { writeText("signed-apk") }
        val expected = "19414629577da02c41742a2b05a8a40b2698f0a7b0353e56cd1a306d95d249a2"
        assertTrue(verifyApkSha256(apk, expected))
        apk.appendText("tampered")
        assertFalse(verifyApkSha256(apk, expected))
    }

    private fun fixture(versionCode: Long = 2, minimumSupported: Long = 1): Fixture {
        val keyPair = KeyPairGenerator.getInstance("Ed25519").generateKeyPair()
        val payload = """{"schema_version":1,"package_name":"com.smartscan.app","version_code":$versionCode,"version_name":"1.1.0","minimum_supported_version_code":$minimumSupported,"apk_url":"https://updates.example.com/SmartScan.apk","apk_sha256":"${"a".repeat(64)}","apk_signing_certificate_sha256":"${"b".repeat(64)}","published_at":"2026-10-21T00:00:00Z"}""".encodeToByteArray()
        val signer = Signature.getInstance("Ed25519").apply {
            initSign(keyPair.private)
            update(payload)
        }
        return Fixture(
            verifier = UpdateManifestVerifier(Base64.getEncoder().encodeToString(keyPair.public.encoded)),
            payload = payload,
            signature = Base64.getEncoder().encodeToString(signer.sign()),
        )
    }
}

private data class Fixture(
    val verifier: UpdateManifestVerifier,
    val payload: ByteArray,
    val signature: String,
)
