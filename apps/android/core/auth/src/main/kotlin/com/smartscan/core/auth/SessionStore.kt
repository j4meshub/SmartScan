package com.smartscan.core.auth

data class SessionCredentials(
    val accessToken: String,
    val accessExpiresAt: String,
    val refreshToken: String,
    val refreshExpiresAt: String,
    val sessionId: String,
    val deviceId: String,
    val userId: String? = null,
)

interface SessionStore {
    fun current(): SessionCredentials?
    fun save(credentials: SessionCredentials)
    fun clear()
}
