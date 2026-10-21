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

    @Test
    fun `page edit sends four normalized corners and filter`() = runTest {
        server.enqueue(
            MockResponse().setHeader("Content-Type", "application/json").setBody(
                """{"id":"page-1","project_id":"project-1","page_number":1,"quality_warning":null,"quality_details":null,"active_result_version":2,"review_status":"pending","ocr_status":"completed"}""",
            ),
        )
        val api = api()

        api.editPage(
            "page-1",
            PageEditRequestDto(
                corners = listOf(PageCornerDto(0.0, 0.0), PageCornerDto(1.0, 0.0), PageCornerDto(1.0, 1.0), PageCornerDto(0.0, 1.0)),
                filter = "grayscale",
            ),
        )
        val request = server.takeRequest()
        val body = request.body.readUtf8()

        assertEquals("/v1/pages/page-1/edits", request.path)
        assertTrue(body.contains("\"filter\":\"grayscale\""))
        assertEquals(4, "\"x\":".toRegex().findAll(body).count())
    }

    @Test
    fun `exam suggestion dismissal keeps result version in JSON body`() = runTest {
        server.enqueue(
            MockResponse().setHeader("Content-Type", "application/json").setBody(
                """{"id":"page-1","project_id":"project-1","page_number":1,"quality_warning":null,"quality_details":null,"active_result_version":2,"review_status":"pending","ocr_status":"completed","exam_result_version":2,"exam_confidence_band":"high","exam_recommendation":"suggest_cleanup","exam_suggestion_visible":false}""",
            ),
        )
        val api = api()

        val page = api.dismissExamSuggestion("page-1", ExamSuggestionDismissalRequestDto(2))
        val request = server.takeRequest()

        assertEquals("/v1/pages/page-1/exam-suggestion-dismissal", request.path)
        assertTrue(request.body.readUtf8().contains("\"result_version\":2"))
        assertFalse(page.examSuggestionVisible)
        assertEquals(2, page.examResultVersion)
    }

    @Test
    fun `account deletion keeps verification data in body`() = runTest {
        server.enqueue(
            MockResponse().setHeader("Content-Type", "application/json").setBody(
                """{"id":"deletion-1","status":"pending","requested_at":"2026-10-21T00:00:00Z","execute_after":"2026-10-28T00:00:00Z","canceled_at":null,"completed_at":null}""",
            ),
        )
        val api = api()

        api.requestAccountDeletion(AccountDeletionRequestDto("+8613800001234", "challenge-id", "123456"))
        val request = server.takeRequest()

        assertEquals("/v1/me/account-deletion", request.path)
        assertTrue(request.body.readUtf8().contains("\"sms_challenge_id\":\"challenge-id\""))
        assertFalse(request.requestUrl!!.queryParameterNames.contains("sms_code"))
    }

    @Test
    fun `artifact download remains authenticated without query token`() = runTest {
        server.enqueue(MockResponse().setHeader("Content-Type", "application/pdf").setBody("pdf-bytes"))
        val api = api()

        val body = api.downloadExportArtifact("artifact-1")
        val request = server.takeRequest()

        assertEquals("pdf-bytes", body.string())
        assertEquals("/v1/export-artifacts/artifact-1/content", request.path)
        assertEquals("Bearer access-token", request.getHeader("Authorization"))
        assertFalse(request.requestUrl!!.queryParameterNames.contains("token"))
    }

    private fun api() = SmartScanApiFactory.create(
        ApiClientConfig(
            baseUrl = server.url("/").toString(),
            deviceId = "android:test-device",
            deviceName = "Android 测试设备",
            allowInsecureLoopback = true,
        ),
        tokenProvider = AccessTokenProvider { "access-token" },
    )
}
