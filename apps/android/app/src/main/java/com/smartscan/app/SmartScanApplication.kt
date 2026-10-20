package com.smartscan.app

import android.app.Application
import android.provider.Settings
import com.smartscan.core.network.ApiClientConfig
import com.smartscan.core.network.SmartScanApiFactory
import com.smartscan.data.repository.DefaultProjectRepository
import com.smartscan.data.repository.ProjectRepository

class SmartScanApplication : Application() {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        val deviceId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
            ?.takeIf { it.length >= 4 }
            ?.let { "android:$it" }
            ?: "android:unknown-device"
        val api = SmartScanApiFactory.create(
            ApiClientConfig(
                baseUrl = BuildConfig.SMARTSCAN_API_BASE_URL,
                deviceId = deviceId,
                deviceName = "SmartScan Android",
            ),
        )
        container = DefaultAppContainer(DefaultProjectRepository(api))
    }
}

interface AppContainer {
    val projectRepository: ProjectRepository
}

private data class DefaultAppContainer(
    override val projectRepository: ProjectRepository,
) : AppContainer
