package com.smartscan.core.security

import com.smartscan.core.auth.SessionCredentials
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SecureSessionStoreTest {
    @Test
    fun `session is restored and refresh rotation replaces both tokens`() {
        val values = MemoryEncryptedValueStore()
        val first = credentials("access-1", "refresh-1")
        SecureSessionStore(values).save(first)

        val restored = SecureSessionStore(values)
        assertEquals(first, restored.current())

        val rotated = credentials("access-2", "refresh-2")
        restored.save(rotated)
        assertEquals(rotated, SecureSessionStore(values).current())
    }

    @Test
    fun `damaged encrypted value is cleared without returning partial credentials`() {
        val values = MemoryEncryptedValueStore("not-json")
        assertNull(SecureSessionStore(values).current())
        assertNull(values.value)
    }

    @Test
    fun `clear removes memory and persistent credentials`() {
        val values = MemoryEncryptedValueStore()
        val store = SecureSessionStore(values)
        store.save(credentials("access", "refresh"))
        store.clear()
        assertNull(store.current())
        assertNull(values.value)
    }

    private fun credentials(access: String, refresh: String) = SessionCredentials(
        accessToken = access,
        accessExpiresAt = "2026-10-20T01:00:00Z",
        refreshToken = refresh,
        refreshExpiresAt = "2026-11-19T00:00:00Z",
        sessionId = "session-id",
        deviceId = "android:test-device",
        userId = "user-id",
    )
}

private class MemoryEncryptedValueStore(var value: String? = null) : EncryptedValueStore {
    override fun read(): String? = value
    override fun write(value: String) { this.value = value }
    override fun clear() { value = null }
}
