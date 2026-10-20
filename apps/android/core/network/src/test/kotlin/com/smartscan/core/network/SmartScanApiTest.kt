package com.smartscan.core.network

import kotlinx.coroutines.test.runTest
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer

class SmartScanApiTest {
    private val server = MockWebServer()

    @AfterTest
    fun tearDown() = server.shutdown()

    @Test
    fun `project request carries device and bearer headers and parses compatible fields`() = runTest {
        server.enqueue(
            MockResponse().setHeader("Content-Type", "application/json").setBody(
                """[{"id":"p1","owner_user_id":"u1","title":"资料","suggested_name":null,"suggested_name_source":null,"suggested_name_updated_at":null,"mode":"document","reading_order":"ltr","created_at":"2026-10-20T00:00:00Z","updated_at":"2026-10-20T00:00:00Z","future_optional_field":true}]""",
            ),
        )
        val api = SmartScanApiFactory.create(
            config = ApiClientConfig(
                baseUrl = server.url("/").toString(),
                deviceId = "android:test-device",
                deviceName = "Pixel 测试设备",
                allowInsecureLoopback = true,
            ),
            tokenProvider = AccessTokenProvider { "access-token" },
        )

        val projects = api.listProjects()
        val request = server.takeRequest()

        assertEquals("资料", projects.single().title)
        assertEquals("/v1/projects", request.path)
        assertEquals("Bearer access-token", request.getHeader("Authorization"))
        assertEquals("android:test-device", request.getHeader("X-Device-ID"))
        assertEquals("Pixel%20%E6%B5%8B%E8%AF%95%E8%AE%BE%E5%A4%87", request.getHeader("X-Device-Name"))
        assertEquals("android", request.getHeader("X-Device-Platform"))
        assertFalse(request.requestUrl!!.queryParameterNames.contains("token"))
    }
}
