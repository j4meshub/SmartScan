package com.smartscan.feature.update

import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec
import java.util.Base64
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdatePolicyTest {
    @Test
    fun `startup checks at most once per day and clock rollback checks again`() {
        val now = 10L * TimeUnit.DAYS.toMillis(1)
        assertTrue(shouldCheckForUpdate(0, now))
        assertFalse(shouldCheckForUpdate(now - TimeUnit.HOURS.toMillis(23), now))
        assertTrue(shouldCheckForUpdate(now - TimeUnit.DAYS.toMillis(1), now))
        assertTrue(shouldCheckForUpdate(now + 1, now))
    }

    @Test
    fun `configuration requires complete values safe fixed urls and valid key`() {
        val publicKeyBytes = KeyPairGenerator.getInstance("EC").apply {
            initialize(ECGenParameterSpec("secp256r1"))
        }.generateKeyPair().public.encoded
        val publicKey = Base64.getEncoder().encodeToString(publicKeyBytes)

        assertFalse(isValidUpdateConfiguration("", "", ""))
        assertFalse(
            isValidUpdateConfiguration(
                "https://updates.example.com/latest.json?token=secret",
                "https://updates.example.com/latest.json.sig",
                publicKey,
            ),
        )
        assertFalse(
            isValidUpdateConfiguration(
                "https://updates.example.com/latest.json",
                "https://updates.example.com/latest.json.sig",
                "not-a-public-key",
            ),
        )
        assertTrue(
            isValidUpdateConfiguration(
                "https://updates.example.com/latest.json",
                "https://updates.example.com/latest.json.sig",
                publicKey,
            ),
        )
    }
}
