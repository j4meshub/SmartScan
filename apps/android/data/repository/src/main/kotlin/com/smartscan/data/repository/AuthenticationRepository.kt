package com.smartscan.data.repository

import com.smartscan.core.auth.SessionCredentials
import com.smartscan.core.auth.SessionStore
import com.smartscan.core.model.ScanProject
import com.smartscan.core.model.AccountDeletionReceipt
import com.smartscan.core.network.AccountDeletionRequestDto
import com.smartscan.core.model.UserProfile
import com.smartscan.core.network.AuthenticationApi
import com.smartscan.core.network.LoginRequestDto
import com.smartscan.core.network.RefreshRequestDto
import com.smartscan.core.network.RegisterRequestDto
import com.smartscan.core.network.SmsChallengeRequestDto
import com.smartscan.core.network.TokenDto
import com.smartscan.core.network.UserDto
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

data class RegistrationChallenge(
    val id: String,
    val expiresAt: String,
    val retryAfterSeconds: Int,
)

data class RegistrationInput(
    val phone: String,
    val smsCode: String,
    val smsChallengeId: String,
    val username: String,
    val password: String,
    val locale: String,
)

interface UserScopedCache {
    suspend fun replaceProjects(userId: String, projects: List<ScanProject>)
    suspend fun listProjects(userId: String): List<ScanProject>
    suspend fun clearUser(userId: String)
}

interface AuthenticationRepository {
    suspend fun requestRegistrationChallenge(phone: String): ApiResult<RegistrationChallenge>
    suspend fun requestAccountDeletionChallenge(phone: String): ApiResult<RegistrationChallenge>
    suspend fun requestAccountDeletionCancellationChallenge(phone: String): ApiResult<RegistrationChallenge>
    suspend fun register(input: RegistrationInput): ApiResult<UserProfile>
    suspend fun login(username: String, password: String): ApiResult<UserProfile>
    suspend fun restore(): ApiResult<UserProfile?>
    suspend fun refresh(): ApiResult<SessionCredentials>
    suspend fun requestAccountDeletion(phone: String, challengeId: String, code: String): ApiResult<AccountDeletionReceipt>
    suspend fun cancelAccountDeletion(phone: String, challengeId: String, code: String): ApiResult<AccountDeletionReceipt>
    suspend fun logout(): ApiResult<Unit>
}

class DefaultAuthenticationRepository(
    private val api: AuthenticationApi,
    private val sessions: SessionStore,
    private val cache: UserScopedCache,
) : AuthenticationRepository {
    private val refreshMutex = Mutex()

    override suspend fun requestRegistrationChallenge(phone: String): ApiResult<RegistrationChallenge> =
        requestChallenge(phone, "registration")

    override suspend fun requestAccountDeletionChallenge(phone: String): ApiResult<RegistrationChallenge> =
        requestChallenge(phone, "account_deletion")

    override suspend fun requestAccountDeletionCancellationChallenge(phone: String): ApiResult<RegistrationChallenge> =
        requestChallenge(phone, "account_deletion_cancel")

    private suspend fun requestChallenge(phone: String, purpose: String): ApiResult<RegistrationChallenge> = safeApiCall {
        require(phone.isNotBlank()) { "phone_required" }
        api.requestSmsChallenge(SmsChallengeRequestDto(phone, purpose)).let {
            RegistrationChallenge(it.challengeId, it.expiresAt, it.retryAfterSeconds)
        }
    }

    override suspend fun register(input: RegistrationInput): ApiResult<UserProfile> = authenticate {
        api.register(
            RegisterRequestDto(
                phone = input.phone,
                smsCode = input.smsCode,
                smsChallengeId = input.smsChallengeId,
                username = input.username,
                password = input.password,
                locale = input.locale,
            ),
        )
    }

    override suspend fun login(username: String, password: String): ApiResult<UserProfile> = authenticate {
        api.login(LoginRequestDto(username, password))
    }

    override suspend fun restore(): ApiResult<UserProfile?> {
        if (sessions.current() == null) return ApiResult.Success(null)
        return when (val result = safeApiCall { api.me().toModel() }) {
            is ApiResult.Success -> result
            is ApiResult.Failure -> {
                if (result.kind != FailureKind.UNAUTHORIZED) return result
                when (val refreshResult = refresh()) {
                    is ApiResult.Failure -> {
                        clearLocalSession()
                        refreshResult
                    }
                    is ApiResult.Success -> safeApiCall { api.me().toModel() }
                }
            }
        }
    }

    override suspend fun refresh(): ApiResult<SessionCredentials> = refreshMutex.withLock {
        val current = sessions.current() ?: return@withLock ApiResult.Failure(
            FailureKind.UNAUTHORIZED,
            retryable = false,
        )
        when (val result = safeApiCall { api.refresh(RefreshRequestDto(current.refreshToken)) }) {
            is ApiResult.Failure -> {
                if (result.kind == FailureKind.UNAUTHORIZED) clearLocalSession()
                result
            }
            is ApiResult.Success -> {
                try {
                    val credentials = result.value.toCredentials(userId = current.userId)
                    sessions.save(credentials)
                    ApiResult.Success(credentials)
                } catch (error: Exception) {
                    clearLocalSession()
                    val kind = if (error is IllegalArgumentException) {
                        FailureKind.INVALID_RESPONSE
                    } else {
                        FailureKind.LOCAL_STORAGE
                    }
                    ApiResult.Failure(kind, retryable = false)
                }
            }
        }
    }

    override suspend fun requestAccountDeletion(
        phone: String,
        challengeId: String,
        code: String,
    ): ApiResult<AccountDeletionReceipt> = when (
        val result = safeApiCall {
            api.requestAccountDeletion(AccountDeletionRequestDto(phone, challengeId, code)).toReceipt()
        }
    ) {
        is ApiResult.Failure -> result
        is ApiResult.Success -> {
            if (clearLocalSession()) result else ApiResult.Failure(FailureKind.LOCAL_STORAGE, retryable = false)
        }
    }

    override suspend fun cancelAccountDeletion(
        phone: String,
        challengeId: String,
        code: String,
    ): ApiResult<AccountDeletionReceipt> = safeApiCall {
        api.cancelAccountDeletion(AccountDeletionRequestDto(phone, challengeId, code)).toReceipt()
    }

    override suspend fun logout(): ApiResult<Unit> {
        val remote = safeApiCall { api.logout() }
        val localCleared = clearLocalSession()
        return if (localCleared) remote else ApiResult.Failure(FailureKind.LOCAL_STORAGE, retryable = false)
    }

    private suspend fun authenticate(request: suspend () -> TokenDto): ApiResult<UserProfile> {
        return when (val tokenResult = safeApiCall { request() }) {
            is ApiResult.Failure -> tokenResult
            is ApiResult.Success -> {
                val credentials = runCatching { tokenResult.value.toCredentials() }.getOrElse {
                    return ApiResult.Failure(FailureKind.INVALID_RESPONSE, retryable = false)
                }
                try {
                    sessions.save(credentials)
                } catch (_: Exception) {
                    runCatching { sessions.clear() }
                    return ApiResult.Failure(FailureKind.LOCAL_STORAGE, retryable = false)
                }
                when (val userResult = safeApiCall { api.me().toModel() }) {
                    is ApiResult.Failure -> {
                        runCatching { sessions.clear() }
                        userResult
                    }
                    is ApiResult.Success -> {
                        try {
                            sessions.save(credentials.copy(userId = userResult.value.id))
                            userResult
                        } catch (_: Exception) {
                            runCatching { sessions.clear() }
                            ApiResult.Failure(FailureKind.LOCAL_STORAGE, retryable = false)
                        }
                    }
                }
            }
        }
    }

    private suspend fun clearLocalSession(): Boolean {
        val userId = sessions.current()?.userId
        val sessionCleared = runCatching { sessions.clear() }.isSuccess
        val cacheCleared = userId == null || runCatching { cache.clearUser(userId) }.isSuccess
        return sessionCleared && cacheCleared
    }
}

private fun com.smartscan.core.network.AccountDeletionDto.toReceipt() = AccountDeletionReceipt(
    id = id,
    status = status,
    requestedAt = requestedAt,
    executeAfter = executeAfter,
)

private fun TokenDto.toCredentials(userId: String? = null): SessionCredentials {
    require(tokenType.equals("bearer", ignoreCase = true)) { "token_type_invalid" }
    return SessionCredentials(
        accessToken = accessToken,
        accessExpiresAt = expiresAt,
        refreshToken = requireNotNull(refreshToken) { "refresh_token_missing" },
        refreshExpiresAt = requireNotNull(refreshExpiresAt) { "refresh_expiry_missing" },
        sessionId = requireNotNull(sessionId) { "session_id_missing" },
        deviceId = requireNotNull(deviceId) { "device_id_missing" },
        userId = userId,
    )
}

private fun UserDto.toModel() = UserProfile(
    id = id,
    username = username,
    phoneMasked = phoneMasked,
    role = role,
    status = status,
    locale = locale,
    mustChangePassword = mustChangePassword,
    createdAt = createdAt,
)
