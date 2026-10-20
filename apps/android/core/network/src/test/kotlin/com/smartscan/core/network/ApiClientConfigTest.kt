package com.smartscan.core.network

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class ApiClientConfigTest {
    @Test
    fun `production base URL requires HTTPS and excludes credentials`() {
        assertFailsWith<IllegalArgumentException> { config("http://api.example.test") }
        assertFailsWith<IllegalArgumentException> { config("https://user:secret@api.example.test") }
        assertFailsWith<IllegalArgumentException> { config("https://api.example.test?token=secret") }
        assertEquals("https://api.example.test/", config("https://api.example.test").normalizedBaseUrl)
    }

    @Test
    fun `development may explicitly allow loopback HTTP only`() {
        assertEquals(
            "http://127.0.0.1:8000/",
            config("http://127.0.0.1:8000", allowInsecureLoopback = true).normalizedBaseUrl,
        )
        assertFailsWith<IllegalArgumentException> {
            config("http://192.168.1.10:8000", allowInsecureLoopback = true)
        }
    }

    private fun config(url: String, allowInsecureLoopback: Boolean = false) = ApiClientConfig(
        baseUrl = url,
        deviceId = "android:test-device",
        deviceName = "Android 测试设备",
        allowInsecureLoopback = allowInsecureLoopback,
    )
}
