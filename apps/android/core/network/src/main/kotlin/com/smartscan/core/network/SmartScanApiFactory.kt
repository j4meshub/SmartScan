package com.smartscan.core.network

import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory
import okhttp3.MediaType.Companion.toMediaType

object SmartScanApiFactory {
    fun create(
        config: ApiClientConfig,
        tokenProvider: AccessTokenProvider = AccessTokenProvider { null },
        clientBuilder: OkHttpClient.Builder = OkHttpClient.Builder(),
    ): SmartScanApi {
        val json = Json { ignoreUnknownKeys = true; explicitNulls = false }
        val client = clientBuilder
            .addInterceptor(SmartScanHeadersInterceptor(config, tokenProvider))
            .build()
        return Retrofit.Builder()
            .baseUrl(config.normalizedBaseUrl)
            .client(client)
            .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
            .build()
            .create(SmartScanApi::class.java)
    }
}
