package com.smartscan.app

import android.app.Application
import android.provider.Settings
import com.smartscan.core.auth.SessionStore
import com.smartscan.core.network.ApiClientConfig
import com.smartscan.core.network.SmartScanApiFactory
import com.smartscan.core.security.AndroidKeystoreSessionStore
import com.smartscan.data.local.openLocalStores
import com.smartscan.data.repository.AuthenticationRepository
import com.smartscan.data.repository.ApiResult
import com.smartscan.data.repository.DefaultAuthenticationRepository
import com.smartscan.data.repository.DefaultProjectRepository
import com.smartscan.data.repository.ProjectRepository
import com.smartscan.feature.sync.RetrofitUploadRemote
import com.smartscan.feature.sync.UploadProcessor
import com.smartscan.feature.sync.UploadQueueCoordinator
import com.smartscan.feature.sync.UploadWorkerDependencies
import com.smartscan.feature.update.AndroidUpdateManager

class SmartScanApplication : Application(), UploadWorkerDependencies {
    lateinit var container: AppContainer
        private set
    override lateinit var uploadSessionStore: SessionStore
        private set
    override lateinit var uploadProcessor: UploadProcessor
        private set

    override suspend fun refreshUploadSession(ownerUserId: String): Boolean {
        val result = container.authenticationRepository.restore()
        return result is ApiResult.Success && result.value?.id == ownerUserId
    }

    override fun onCreate() {
        super.onCreate()
        val deviceId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
            ?.takeIf { it.length >= 4 }
            ?.let { "android:$it" }
            ?: "android:unknown-device"
        val sessionStore: SessionStore = AndroidKeystoreSessionStore(this)
        uploadSessionStore = sessionStore
        val api = SmartScanApiFactory.create(
            ApiClientConfig(
                baseUrl = BuildConfig.SMARTSCAN_API_BASE_URL,
                deviceId = deviceId,
                deviceName = "SmartScan Android",
            ),
            tokenProvider = { sessionStore.current()?.accessToken },
        )
        val localStores = openLocalStores(this)
        uploadProcessor = UploadProcessor(RetrofitUploadRemote(api), localStores.uploadQueue)
        container = DefaultAppContainer(
            authenticationRepository = DefaultAuthenticationRepository(
                api = api,
                sessions = sessionStore,
                cache = localStores.userCache,
            ),
            projectRepository = DefaultProjectRepository(
                api = api,
                workspaceApi = api,
                aiApi = api,
                cache = localStores.userCache,
                currentUserId = { sessionStore.current()?.userId },
            ),
            uploadQueueCoordinator = UploadQueueCoordinator(this, localStores.uploadQueue, sessionStore),
            updateManager = AndroidUpdateManager.createOrNull(
                context = this,
                manifestUrl = BuildConfig.SMARTSCAN_UPDATE_MANIFEST_URL,
                signatureUrl = BuildConfig.SMARTSCAN_UPDATE_SIGNATURE_URL,
                publicKeyBase64 = BuildConfig.SMARTSCAN_UPDATE_PUBLIC_KEY,
            ),
        )
    }
}

interface AppContainer {
    val authenticationRepository: AuthenticationRepository
    val projectRepository: ProjectRepository
    val uploadQueueCoordinator: UploadQueueCoordinator
    val updateManager: AndroidUpdateManager?
}

private data class DefaultAppContainer(
    override val authenticationRepository: AuthenticationRepository,
    override val projectRepository: ProjectRepository,
    override val uploadQueueCoordinator: UploadQueueCoordinator,
    override val updateManager: AndroidUpdateManager?,
) : AppContainer
