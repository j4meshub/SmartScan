package com.smartscan.data.repository

import com.smartscan.core.auth.SessionCredentials
import com.smartscan.core.auth.SessionStore
import com.smartscan.core.model.ScanProject
import com.smartscan.core.network.AuthenticationApi
import com.smartscan.core.network.LoginRequestDto
import com.smartscan.core.network.RefreshRequestDto
import com.smartscan.core.network.RegisterRequestDto
import com.smartscan.core.network.SmsChallengeDto
import com.smartscan.core.network.SmsChallengeRequestDto
import com.smartscan.core.network.TokenDto
import com.smartscan.core.network.UserDto
import java.io.IOException
import kotlinx.coroutines.test.runTest
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Test

class AuthenticationRepositoryTest {
    @Test
    fun `registration forwards verified challenge and persists returned user`() = runTest {
        val sessions = MemorySessionStore()
        val api = FakeAuthenticationApi()
        val repository = DefaultAuthenticationRepository(api, sessions, RecordingCache())

        val result = repository.register(
            RegistrationInput(
                phone = "+8613800001234",
                smsCode = "123456",
                smsChallengeId = "challenge-id",
                username = "student",
                password = "long-password",
                locale = "zh-CN",
            ),
        )

        assertEquals("challenge-id", api.lastRegister?.smsChallengeId)
        assertEquals("zh-CN", api.lastRegister?.locale)
        assertEquals("user-1", (result as ApiResult.Success).value.id)
    }

    @Test
    fun `login persists tokens only after fetching the authenticated user`() = runTest {
        val sessions = MemorySessionStore()
        val repository = DefaultAuthenticationRepository(FakeAuthenticationApi(), sessions, RecordingCache())

        val result = repository.login("student", "long-password")

        assertEquals("student", (result as ApiResult.Success).value.username)
        assertEquals("user-1", sessions.current()?.userId)
        assertEquals("refresh-1", sessions.current()?.refreshToken)
    }

    @Test
    fun `refresh atomically replaces access and one-time refresh tokens`() = runTest {
        val sessions = MemorySessionStore(credentials())
        val api = FakeAuthenticationApi(
            refreshedToken = token(access = "access-2", refresh = "refresh-2"),
        )
        val repository = DefaultAuthenticationRepository(api, sessions, RecordingCache())

        val result = repository.refresh()

        assertEquals("refresh-1", api.lastRefreshToken)
        assertEquals("refresh-2", (result as ApiResult.Success).value.refreshToken)
        assertEquals("access-2", sessions.current()?.accessToken)
    }

    @Test
    fun `logout clears local session and current user cache when network fails`() = runTest {
        val sessions = MemorySessionStore(credentials())
        val cache = RecordingCache()
        val repository = DefaultAuthenticationRepository(
            FakeAuthenticationApi(logoutError = IOException("private-host")),
            sessions,
            cache,
        )

        val result = repository.logout()

        assertEquals(FailureKind.NETWORK, (result as ApiResult.Failure).kind)
        assertNull(sessions.current())
        assertEquals(listOf("user-1"), cache.clearedUsers)
    }

    @Test
    fun `restore without credentials remains signed out without calling network`() = runTest {
        val api = FakeAuthenticationApi()
        val repository = DefaultAuthenticationRepository(api, MemorySessionStore(), RecordingCache())

        assertNull((repository.restore() as ApiResult.Success).value)
        assertEquals(0, api.meCalls)
    }
}

private class MemorySessionStore(initial: SessionCredentials? = null) : SessionStore {
    private var value = initial
    override fun current(): SessionCredentials? = value
    override fun save(credentials: SessionCredentials) { value = credentials }
    override fun clear() { value = null }
}

private class RecordingCache : UserScopedCache {
    val clearedUsers = mutableListOf<String>()
    override suspend fun replaceProjects(userId: String, projects: List<ScanProject>) = Unit
    override suspend fun listProjects(userId: String): List<ScanProject> = emptyList()
    override suspend fun clearUser(userId: String) { clearedUsers += userId }
}

private class FakeAuthenticationApi(
    private val refreshedToken: TokenDto = token("access-2", "refresh-2"),
    private val logoutError: IOException? = null,
) : AuthenticationApi {
    var lastRefreshToken: String? = null
    var lastRegister: RegisterRequestDto? = null
    var meCalls = 0

    override suspend fun requestSmsChallenge(request: SmsChallengeRequestDto) = SmsChallengeDto(
        challengeId = "challenge-id",
        expiresAt = "2026-10-20T00:05:00Z",
        retryAfterSeconds = 60,
    )

    override suspend fun register(request: RegisterRequestDto): TokenDto {
        lastRegister = request
        return token()
    }
    override suspend fun login(request: LoginRequestDto) = token()

    override suspend fun refresh(request: RefreshRequestDto): TokenDto {
        lastRefreshToken = request.refreshToken
        return refreshedToken
    }

    override suspend fun logout() {
        logoutError?.let { throw it }
    }

    override suspend fun me(): UserDto {
        meCalls += 1
        return UserDto(
            id = "user-1",
            username = "student",
            phoneMasked = "+86******1234",
            role = "user",
            status = "active",
            locale = "zh-CN",
            mustChangePassword = false,
            createdAt = "2026-10-20T00:00:00Z",
        )
    }
}

private fun token(
    access: String = "access-1",
    refresh: String = "refresh-1",
) = TokenDto(
    accessToken = access,
    tokenType = "bearer",
    expiresAt = "2026-10-20T01:00:00Z",
    refreshToken = refresh,
    refreshExpiresAt = "2026-11-19T00:00:00Z",
    sessionId = "session-id",
    deviceId = "android:test-device",
)

private fun credentials() = SessionCredentials(
    accessToken = "access-1",
    accessExpiresAt = "2026-10-20T01:00:00Z",
    refreshToken = "refresh-1",
    refreshExpiresAt = "2026-11-19T00:00:00Z",
    sessionId = "session-id",
    deviceId = "android:test-device",
    userId = "user-1",
)
