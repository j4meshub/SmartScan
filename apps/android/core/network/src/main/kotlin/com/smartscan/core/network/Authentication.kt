package com.smartscan.core.network

import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import okhttp3.Interceptor
import okhttp3.Response

fun interface AccessTokenProvider {
    fun accessToken(): String?
}

internal class SmartScanHeadersInterceptor(
    private val config: ApiClientConfig,
    private val tokenProvider: AccessTokenProvider,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val builder = chain.request().newBuilder()
            .header("X-Device-ID", config.deviceId)
            .header(
                "X-Device-Name",
                URLEncoder.encode(config.deviceName, StandardCharsets.UTF_8).replace("+", "%20"),
            )
            .header("X-Device-Platform", "android")
            .header("Accept", "application/json")
        tokenProvider.accessToken()?.takeIf { it.isNotBlank() }?.let { builder.header("Authorization", "Bearer $it") }
        return chain.proceed(builder.build())
    }
}
