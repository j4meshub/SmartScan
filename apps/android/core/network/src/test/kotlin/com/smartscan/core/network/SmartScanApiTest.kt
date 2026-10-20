package com.smartscan.core.network

import kotlinx.coroutines.test.runTest
import kotlin.test.AfterTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody

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

    @Test
    fun `login credentials stay in JSON body and token response is parsed`() = runTest {
        server.enqueue(
            MockResponse().setHeader("Content-Type", "application/json").setBody(
                """{"access_token":"access","token_type":"bearer","expires_at":"2026-10-20T01:00:00Z","refresh_token":"refresh","refresh_expires_at":"2026-11-19T00:00:00Z","session_id":"session","device_id":"android:test-device"}""",
            ),
        )
        val api = SmartScanApiFactory.create(
            ApiClientConfig(
                baseUrl = server.url("/").toString(),
                deviceId = "android:test-device",
                deviceName = "Android 测试设备",
                allowInsecureLoopback = true,
            ),
        )

        val token = api.login(LoginRequestDto("student", "private-password"))
        val request = server.takeRequest()

        assertEquals("refresh", token.refreshToken)
        assertEquals("/v1/auth/login", request.path)
        assertFalse(request.requestUrl!!.queryParameterNames.contains("password"))
        assertTrue(request.body.readUtf8().contains("\"password\":\"private-password\""))
    }

    @Test
    fun `chunk upload keeps hash in header and bytes in body`() = runTest {
        server.enqueue(
            MockResponse().setHeader("Content-Type", "application/json").setBody(
                """{"upload_id":"upload-1","chunk_index":2,"size_bytes":4,"sha256":"${"a".repeat(64)}"}""",
            ),
        )
        val api = SmartScanApiFactory.create(
            ApiClientConfig(
                baseUrl = server.url("/").toString(),
                deviceId = "android:test-device",
                deviceName = "Android 测试设备",
                allowInsecureLoopback = true,
            ),
            tokenProvider = AccessTokenProvider { "access-token" },
        )
        val bytes = byteArrayOf(1, 2, 3, 4)

        api.putUploadChunk(
            "upload-1",
            2,
            "a".repeat(64),
            bytes.toRequestBody("application/octet-stream".toMediaType()),
        )
        val request = server.takeRequest()

        assertEquals("/v1/uploads/upload-1/chunks/2", request.path)
        assertEquals("a".repeat(64), request.getHeader("X-Chunk-Sha256"))
        assertTrue(request.body.readByteArray().contentEquals(bytes))
        assertFalse(request.requestUrl!!.queryParameterNames.contains("token"))
    }
}
