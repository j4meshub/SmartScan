package com.smartscan.data.repository

sealed interface ApiResult<out T> {
    data class Success<T>(val value: T) : ApiResult<T>
    data class Failure(
        val kind: FailureKind,
        val statusCode: Int? = null,
        val retryable: Boolean,
    ) : ApiResult<Nothing>
}

enum class FailureKind { UNAUTHORIZED, NOT_FOUND, RATE_LIMITED, SERVER, NETWORK, INVALID_RESPONSE, UNKNOWN }
