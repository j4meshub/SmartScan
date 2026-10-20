package com.smartscan.core.network

import java.net.URI

data class ApiClientConfig(
    val baseUrl: String,
    val deviceId: String,
    val deviceName: String,
    val allowInsecureLoopback: Boolean = false,
) {
    init {
        require(deviceId.matches(Regex("^[A-Za-z0-9_.:-]{4,100}$"))) { "device_id_invalid" }
        require(deviceName.isNotBlank() && deviceName.length <= 100) { "device_name_invalid" }
        validateBaseUrl(baseUrl, allowInsecureLoopback)
    }

    val normalizedBaseUrl: String = baseUrl.trimEnd('/') + "/"
}

internal fun validateBaseUrl(value: String, allowInsecureLoopback: Boolean) {
    val uri = runCatching { URI(value) }.getOrElse { throw IllegalArgumentException("api_base_url_invalid") }
    require(uri.userInfo == null && uri.query == null && uri.fragment == null) { "api_base_url_invalid" }
    require(!uri.host.isNullOrBlank()) { "api_base_url_invalid" }
    val loopback = uri.host.equals("localhost", true) || uri.host == "127.0.0.1" || uri.host == "::1"
    require(uri.scheme.equals("https", true) || (allowInsecureLoopback && loopback && uri.scheme.equals("http", true))) {
        "api_base_url_requires_https"
    }
}
