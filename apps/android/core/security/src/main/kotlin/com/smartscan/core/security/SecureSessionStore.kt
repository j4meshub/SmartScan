package com.smartscan.core.security

import com.smartscan.core.auth.SessionCredentials
import com.smartscan.core.auth.SessionStore
import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

interface EncryptedValueStore {
    fun read(): String?
    fun write(value: String)
    fun clear()
}

class SecureSessionStore(
    private val values: EncryptedValueStore,
    private val json: Json = Json { ignoreUnknownKeys = false },
) : SessionStore {
    @Volatile
    private var cached: SessionCredentials? = restore()

    override fun current(): SessionCredentials? = cached

    @Synchronized
    override fun save(credentials: SessionCredentials) {
        require(credentials.accessToken.isNotBlank()) { "access_token_required" }
        require(credentials.refreshToken.isNotBlank()) { "refresh_token_required" }
        val encoded = json.encodeToString(SessionEnvelope.from(credentials))
        values.write(encoded)
        cached = credentials
    }

    @Synchronized
    override fun clear() {
        cached = null
        values.clear()
    }

    private fun restore(): SessionCredentials? = try {
        values.read()?.let { json.decodeFromString<SessionEnvelope>(it).toCredentials() }
    } catch (_: Exception) {
        runCatching { values.clear() }
        null
    }
}

@Serializable
private data class SessionEnvelope(
    val version: Int = 1,
    val accessToken: String,
    val accessExpiresAt: String,
    val refreshToken: String,
    val refreshExpiresAt: String,
    val sessionId: String,
    val deviceId: String,
    val userId: String? = null,
) {
    fun toCredentials(): SessionCredentials {
        require(version == 1) { "session_version_unsupported" }
        return SessionCredentials(
            accessToken = accessToken,
            accessExpiresAt = accessExpiresAt,
            refreshToken = refreshToken,
            refreshExpiresAt = refreshExpiresAt,
            sessionId = sessionId,
            deviceId = deviceId,
            userId = userId,
        )
    }

    companion object {
        fun from(credentials: SessionCredentials) = SessionEnvelope(
            accessToken = credentials.accessToken,
            accessExpiresAt = credentials.accessExpiresAt,
            refreshToken = credentials.refreshToken,
            refreshExpiresAt = credentials.refreshExpiresAt,
            sessionId = credentials.sessionId,
            deviceId = credentials.deviceId,
            userId = credentials.userId,
        )
    }
}
