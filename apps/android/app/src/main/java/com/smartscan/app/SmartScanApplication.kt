package com.smartscan.app

import android.app.Application
import android.provider.Settings
import com.smartscan.core.auth.SessionStore
import com.smartscan.core.network.ApiClientConfig
import com.smartscan.core.network.SmartScanApiFactory
import com.smartscan.core.security.AndroidKeystoreSessionStore
import com.smartscan.data.local.RoomUserScopedCache
import com.smartscan.data.local.SmartScanDatabase
import com.smartscan.data.repository.AuthenticationRepository
import com.smartscan.data.repository.DefaultAuthenticationRepository
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
        val sessionStore: SessionStore = AndroidKeystoreSessionStore(this)
        val api = SmartScanApiFactory.create(
            ApiClientConfig(
                baseUrl = BuildConfig.SMARTSCAN_API_BASE_URL,
                deviceId = deviceId,
                deviceName = "SmartScan Android",
            ),
            tokenProvider = { sessionStore.current()?.accessToken },
        )
        val database = SmartScanDatabase.open(this)
        val userCache = RoomUserScopedCache(database.cachedProjects())
        container = DefaultAppContainer(
            authenticationRepository = DefaultAuthenticationRepository(
                api = api,
                sessions = sessionStore,
                cache = userCache,
            ),
            projectRepository = DefaultProjectRepository(
                api = api,
                cache = userCache,
                currentUserId = { sessionStore.current()?.userId },
            ),
        )
    }
}

interface AppContainer {
    val authenticationRepository: AuthenticationRepository
    val projectRepository: ProjectRepository
}

private data class DefaultAppContainer(
    override val authenticationRepository: AuthenticationRepository,
    override val projectRepository: ProjectRepository,
) : AppContainer
