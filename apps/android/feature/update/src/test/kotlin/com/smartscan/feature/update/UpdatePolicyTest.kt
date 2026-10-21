package com.smartscan.feature.update

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import java.security.KeyPairGenerator
import java.security.spec.ECGenParameterSpec
import java.util.Base64
import java.util.concurrent.TimeUnit
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
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
    fun `manager requires complete configuration and safe fixed urls`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val publicKeyBytes = KeyPairGenerator.getInstance("EC").apply {
            initialize(ECGenParameterSpec("secp256r1"))
        }.generateKeyPair().public.encoded
        val publicKey = Base64.getEncoder().encodeToString(publicKeyBytes)

        assertNull(AndroidUpdateManager.createOrNull(context, "", "", ""))
        assertNull(
            AndroidUpdateManager.createOrNull(
                context,
                "https://updates.example.com/latest.json?token=secret",
                "https://updates.example.com/latest.json.sig",
                publicKey,
            ),
        )
        assertNotNull(
            AndroidUpdateManager.createOrNull(
                context,
                "https://updates.example.com/latest.json",
                "https://updates.example.com/latest.json.sig",
                publicKey,
            ),
        )
    }
}
