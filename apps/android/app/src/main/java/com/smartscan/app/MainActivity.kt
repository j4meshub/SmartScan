package com.smartscan.app

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.core.content.FileProvider
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.smartscan.core.model.DownloadedArtifact
import com.smartscan.core.model.UserProfile
import com.smartscan.data.repository.ApiResult
import com.smartscan.data.repository.AuthenticationRepository
import com.smartscan.data.repository.ProjectRepository
import com.smartscan.data.repository.RegistrationInput
import com.smartscan.feature.capture.CaptureMode
import com.smartscan.feature.capture.CaptureScreen
import com.smartscan.feature.sync.UploadQueueCoordinator
import com.smartscan.feature.update.AndroidUpdateManager
import com.smartscan.feature.update.InstallLaunchResult
import com.smartscan.feature.update.UpdateCheckResult
import com.smartscan.feature.update.UpdateDownloadResult
import com.smartscan.feature.workspace.ProjectWorkspaceScreen
import java.io.File
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import java.util.Locale

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val container = (application as SmartScanApplication).container
        setContent {
            SmartScanApp(
                authenticationRepository = container.authenticationRepository,
                projectRepository = container.projectRepository,
                uploadQueueCoordinator = container.uploadQueueCoordinator,
                updateManager = container.updateManager,
                onShare = ::shareArtifact,
                onInstallUpdate = { ready ->
                    container.updateManager?.launchInstaller(this, ready) ?: InstallLaunchResult.REJECTED
                },
            )
        }
    }

    private fun shareArtifact(download: DownloadedArtifact) {
        val exportRoot = File(cacheDir, "exports").canonicalFile
        val file = runCatching { File(download.filePath).canonicalFile }.getOrNull() ?: return
        if (!file.isFile || file.parentFile != exportRoot) return
        val uri = FileProvider.getUriForFile(this, "$packageName.files", file)
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = download.mimeType
            putExtra(Intent.EXTRA_STREAM, uri)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        startActivity(Intent.createChooser(intent, getString(R.string.share_export_title)))
    }
}

private val Ink = Color(0xFF111827)
private val Paper = Color(0xFFF4F1EB)
private val Mint = Color(0xFFB7F7D4)

@Composable
fun SmartScanApp(
    authenticationRepository: AuthenticationRepository,
    projectRepository: ProjectRepository,
    uploadQueueCoordinator: UploadQueueCoordinator,
    updateManager: AndroidUpdateManager?,
    onShare: (DownloadedArtifact) -> Unit,
    onInstallUpdate: (UpdateDownloadResult.Ready) -> InstallLaunchResult,
) {
    val authState = remember { MutableStateFlow<AuthUiState>(AuthUiState.Loading) }
    val state by authState.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var registrationChallengeId by remember { mutableStateOf<String?>(null) }
    var cancellationChallengeId by remember { mutableStateOf<String?>(null) }
    var messageResource by remember { mutableStateOf<Int?>(null) }
    var startupUpdateResult by remember { mutableStateOf<UpdateCheckResult?>(null) }

    LaunchedEffect(authenticationRepository) {
        authState.value = authenticationRepository.restore().toUiState()
    }
    LaunchedEffect(updateManager) {
        if (updateManager != null) startupUpdateResult = updateManager.check()
    }
    LaunchedEffect(state) {
        if (state is AuthUiState.SignedIn) uploadQueueCoordinator.resumeCurrentUser()
    }

    when (val current = state) {
        AuthUiState.Loading -> LoadingScreen()
        AuthUiState.SignedOut -> AuthenticationScreen(
            messageResource = messageResource,
            registrationChallengeReady = registrationChallengeId != null,
            cancellationChallengeReady = cancellationChallengeId != null,
            onRequestRegistrationCode = { phone ->
                scope.launch {
                    messageResource = null
                    when (val result = authenticationRepository.requestRegistrationChallenge(phone)) {
                        is ApiResult.Success -> {
                            registrationChallengeId = result.value.id
                            messageResource = R.string.auth_code_sent
                        }
                        is ApiResult.Failure -> messageResource = R.string.auth_request_failed
                    }
                }
            },
            onRequestCancellationCode = { phone ->
                scope.launch {
                    messageResource = null
                    when (val result = authenticationRepository.requestAccountDeletionCancellationChallenge(phone)) {
                        is ApiResult.Success -> {
                            cancellationChallengeId = result.value.id
                            messageResource = R.string.auth_code_sent
                        }
                        is ApiResult.Failure -> messageResource = R.string.auth_request_failed
                    }
                }
            },
            onLogin = { username, password ->
                authState.value = AuthUiState.Loading
                scope.launch {
                    authState.value = authenticationRepository.login(username, password).toUiState()
                    if (authState.value == AuthUiState.SignedOut) messageResource = R.string.auth_login_failed
                }
            },
            onRegister = { phone, code, username, password ->
                val currentChallenge = registrationChallengeId
                if (currentChallenge == null) {
                    messageResource = R.string.auth_code_required
                } else {
                    authState.value = AuthUiState.Loading
                    scope.launch {
                        val locale = if (Locale.getDefault().language == "zh") "zh-CN" else "en"
                        authState.value = authenticationRepository.register(
                            RegistrationInput(phone, code, currentChallenge, username, password, locale),
                        ).toUiState()
                        if (authState.value == AuthUiState.SignedOut) messageResource = R.string.auth_register_failed
                    }
                }
            },
            onCancelDeletion = { phone, code ->
                val currentChallenge = cancellationChallengeId
                if (currentChallenge == null) {
                    messageResource = R.string.auth_code_required
                } else {
                    scope.launch {
                        when (authenticationRepository.cancelAccountDeletion(phone, currentChallenge, code)) {
                            is ApiResult.Success -> {
                                cancellationChallengeId = null
                                messageResource = R.string.account_deletion_canceled
                            }
                            is ApiResult.Failure -> messageResource = R.string.account_deletion_cancel_failed
                        }
                    }
                }
            },
        )
        is AuthUiState.SignedIn -> AuthenticatedApp(
            user = current.user,
            authenticationRepository = authenticationRepository,
            projectRepository = projectRepository,
            uploadQueueCoordinator = uploadQueueCoordinator,
            updateManager = updateManager,
            initialUpdateResult = startupUpdateResult,
            onShare = onShare,
            onInstallUpdate = onInstallUpdate,
            onAccountDeletionScheduled = { localCleanupComplete ->
                registrationChallengeId = null
                cancellationChallengeId = null
                messageResource = if (localCleanupComplete) {
                    R.string.account_deletion_scheduled
                } else {
                    R.string.account_deletion_scheduled_cleanup_failed
                }
                authState.value = AuthUiState.SignedOut
            },
            onLogout = {
                authState.value = AuthUiState.Loading
                scope.launch {
                    authenticationRepository.logout()
                    registrationChallengeId = null
                    cancellationChallengeId = null
                    messageResource = null
                    authState.value = AuthUiState.SignedOut
                }
            },
        )
    }
}

@Composable
private fun AuthenticatedApp(
    user: UserProfile,
    authenticationRepository: AuthenticationRepository,
    projectRepository: ProjectRepository,
    uploadQueueCoordinator: UploadQueueCoordinator,
    updateManager: AndroidUpdateManager?,
    initialUpdateResult: UpdateCheckResult?,
    onShare: (DownloadedArtifact) -> Unit,
    onInstallUpdate: (UpdateDownloadResult.Ready) -> InstallLaunchResult,
    onAccountDeletionScheduled: (Boolean) -> Unit,
    onLogout: () -> Unit,
) {
    MaterialTheme(colorScheme = lightColorScheme(primary = Ink, background = Paper)) {
        val navController = rememberNavController()
        val backStackEntry by navController.currentBackStackEntryAsState()
        val currentDestination = backStackEntry?.destination
        val destinations = listOf(
            AppDestination.Home,
            AppDestination.Projects,
            AppDestination.Settings,
        )
        Scaffold(
            bottomBar = {
                if (currentDestination?.route != CaptureRoute) {
                    NavigationBar {
                        destinations.forEach { destination ->
                            NavigationBarItem(
                                selected = currentDestination?.hierarchy?.any { it.route == destination.route } == true,
                                onClick = {
                                    navController.navigate(destination.route) {
                                        popUpTo(navController.graph.findStartDestination().id) { saveState = true }
                                        launchSingleTop = true
                                        restoreState = true
                                    }
                                },
                                icon = { Text(destination.symbol) },
                                label = { Text(stringResource(destination.labelResource)) },
                            )
                        }
                    }
                }
            },
        ) { innerPadding ->
            NavHost(
                navController = navController,
                startDestination = AppDestination.Home.route,
                modifier = Modifier.padding(innerPadding),
            ) {
                composable(AppDestination.Home.route) {
                    SmartScanHome { mode -> navController.navigate("capture/${mode.routeValue}") }
                }
                composable(AppDestination.Projects.route) {
                    val context = androidx.compose.ui.platform.LocalContext.current
                    ProjectWorkspaceScreen(
                        repository = projectRepository,
                        previewDirectory = remember(context) { File(context.cacheDir, "page-previews") },
                        exportDirectory = remember(context) { File(context.cacheDir, "exports") },
                        onShare = onShare,
                    )
                }
                composable(AppDestination.Settings.route) {
                    SettingsScreen(
                        user = user,
                        authenticationRepository = authenticationRepository,
                        uploadQueueCoordinator = uploadQueueCoordinator,
                        updateManager = updateManager,
                        initialUpdateResult = initialUpdateResult,
                        onInstallUpdate = onInstallUpdate,
                        onAccountDeletionScheduled = onAccountDeletionScheduled,
                        onLogout = onLogout,
                    )
                }
                composable(CaptureRoute) { entry ->
                    val mode = CaptureMode.fromRoute(entry.arguments?.getString("mode"))
                    val localProjectId = rememberSaveable { UUID.randomUUID().toString() }
                    val titlePrefix = stringResource(
                        when (mode) {
                            CaptureMode.DOCUMENT -> R.string.upload_project_document
                            CaptureMode.EXAM -> R.string.upload_project_exam
                            CaptureMode.BOOK -> R.string.upload_project_book
                        },
                    )
                    val projectTitle = remember(titlePrefix) {
                        "${titlePrefix}_${LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmm"))}"
                    }
                    CaptureScreen(
                        mode = mode,
                        onBack = { navController.popBackStack() },
                        onOriginalCaptured = { path ->
                            uploadQueueCoordinator.enqueue(
                                localProjectId = localProjectId,
                                title = projectTitle,
                                mode = mode.routeValue,
                                originalPath = path,
                            )
                        },
                    )
                }
            }
        }
    }
}

private sealed interface AuthUiState {
    data object Loading : AuthUiState
    data object SignedOut : AuthUiState
    data class SignedIn(val user: UserProfile) : AuthUiState
}

private fun ApiResult<UserProfile?>.toUiState(): AuthUiState = when (this) {
    is ApiResult.Success -> value?.let(AuthUiState::SignedIn) ?: AuthUiState.SignedOut
    is ApiResult.Failure -> AuthUiState.SignedOut
}

@Composable
private fun LoadingScreen() {
    MaterialTheme(colorScheme = lightColorScheme(primary = Ink, background = Paper)) {
        Box(Modifier.fillMaxSize().background(Paper), contentAlignment = Alignment.Center) {
            CircularProgressIndicator()
        }
    }
}

private enum class AuthScreenMode { LOGIN, REGISTER, CANCEL_DELETION }

@Composable
private fun AuthenticationScreen(
    messageResource: Int?,
    registrationChallengeReady: Boolean,
    cancellationChallengeReady: Boolean,
    onRequestRegistrationCode: (String) -> Unit,
    onRequestCancellationCode: (String) -> Unit,
    onLogin: (String, String) -> Unit,
    onRegister: (String, String, String, String) -> Unit,
    onCancelDeletion: (String, String) -> Unit,
) {
    var mode by remember { mutableStateOf(AuthScreenMode.LOGIN) }
    var phone by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    val registration = mode == AuthScreenMode.REGISTER
    val cancellation = mode == AuthScreenMode.CANCEL_DELETION
    val validation = if (cancellation) {
        validateDeletionCancellation(phone, code, cancellationChallengeReady)
    } else {
        validateAuthForm(registration, phone, code, username, password, registrationChallengeReady)
    }

    MaterialTheme(colorScheme = lightColorScheme(primary = Ink, background = Paper)) {
        Column(
            modifier = Modifier.fillMaxSize().background(Paper).padding(24.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            Text("SmartScan", fontWeight = FontWeight.Black, fontSize = 34.sp)
            Spacer(Modifier.height(8.dp))
            Text(
                stringResource(
                    when (mode) {
                        AuthScreenMode.LOGIN -> R.string.auth_login_title
                        AuthScreenMode.REGISTER -> R.string.auth_register_title
                        AuthScreenMode.CANCEL_DELETION -> R.string.account_deletion_cancel_title
                    },
                ),
            )
            Spacer(Modifier.height(24.dp))
            if (registration || cancellation) {
                OutlinedTextField(
                    value = phone,
                    onValueChange = { phone = it.trim() },
                    label = { Text(stringResource(R.string.auth_phone)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = code,
                        onValueChange = { code = it.trim() },
                        label = { Text(stringResource(R.string.auth_sms_code)) },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    Button(
                        onClick = {
                            if (cancellation) onRequestCancellationCode(phone) else onRequestRegistrationCode(phone)
                        },
                        enabled = isValidE164Phone(phone),
                    ) {
                        Text(stringResource(R.string.auth_request_code))
                    }
                }
                Spacer(Modifier.height(8.dp))
            }
            if (!cancellation) {
                OutlinedTextField(
                    value = username,
                    onValueChange = { username = it.trim() },
                    label = { Text(stringResource(R.string.auth_username)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    label = { Text(stringResource(R.string.auth_password)) },
                    visualTransformation = PasswordVisualTransformation(),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            messageResource?.let {
                Spacer(Modifier.height(8.dp))
                Text(stringResource(it), color = MaterialTheme.colorScheme.error)
            }
            Spacer(Modifier.height(16.dp))
            Button(
                onClick = {
                    when (mode) {
                        AuthScreenMode.LOGIN -> onLogin(username, password)
                        AuthScreenMode.REGISTER -> onRegister(phone, code, username, password)
                        AuthScreenMode.CANCEL_DELETION -> onCancelDeletion(phone, code)
                    }
                },
                enabled = validation.valid,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    stringResource(
                        when (mode) {
                            AuthScreenMode.LOGIN -> R.string.auth_login_action
                            AuthScreenMode.REGISTER -> R.string.auth_register_action
                            AuthScreenMode.CANCEL_DELETION -> R.string.account_deletion_cancel_action
                        },
                    ),
                )
            }
            TextButton(onClick = {
                mode = if (mode == AuthScreenMode.LOGIN) AuthScreenMode.REGISTER else AuthScreenMode.LOGIN
                password = ""
            }) {
                Text(stringResource(if (mode == AuthScreenMode.LOGIN) R.string.auth_show_register else R.string.auth_show_login))
            }
            if (mode == AuthScreenMode.LOGIN) {
                TextButton(onClick = { mode = AuthScreenMode.CANCEL_DELETION }) {
                    Text(stringResource(R.string.account_deletion_cancel_entry))
                }
            }
        }
    }
}

@Composable
private fun SettingsScreen(
    user: UserProfile,
    authenticationRepository: AuthenticationRepository,
    uploadQueueCoordinator: UploadQueueCoordinator,
    updateManager: AndroidUpdateManager?,
    initialUpdateResult: UpdateCheckResult?,
    onInstallUpdate: (UpdateDownloadResult.Ready) -> InstallLaunchResult,
    onAccountDeletionScheduled: (Boolean) -> Unit,
    onLogout: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var phone by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var confirmUsername by remember { mutableStateOf("") }
    var challengeId by remember { mutableStateOf<String?>(null) }
    var messageResource by remember { mutableStateOf<Int?>(null) }
    var updateResult by remember { mutableStateOf(initialUpdateResult) }
    var updateDownload by remember { mutableStateOf<UpdateDownloadResult.Ready?>(null) }
    var updateBusy by remember { mutableStateOf(false) }
    var updateMessageResource by remember { mutableStateOf<Int?>(null) }
    LaunchedEffect(initialUpdateResult) {
        if (initialUpdateResult != null) updateResult = initialUpdateResult
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize().background(Paper).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Text(stringResource(R.string.settings), fontWeight = FontWeight.Black, fontSize = 32.sp)
            Text(user.username)
            Text(user.phoneMasked, color = Color(0xFF4B5563))
            Spacer(Modifier.height(16.dp))
            Button(onClick = onLogout) { Text(stringResource(R.string.auth_logout)) }
            HorizontalDivider(Modifier.padding(vertical = 20.dp))
            Text(stringResource(R.string.update_title), fontWeight = FontWeight.Bold, fontSize = 20.sp)
            if (updateManager == null) {
                Text(stringResource(R.string.update_unconfigured))
            } else {
                when (val result = updateResult) {
                    null, UpdateCheckResult.NotDue -> Text(stringResource(R.string.update_not_checked))
                    UpdateCheckResult.Current -> Text(stringResource(R.string.update_current))
                    is UpdateCheckResult.Available -> Text(
                        stringResource(
                            if (result.update.mandatory) R.string.update_available_required else R.string.update_available,
                            result.update.manifest.versionName,
                        ),
                    )
                    is UpdateCheckResult.Failed -> Text(stringResource(R.string.update_check_failed), color = MaterialTheme.colorScheme.error)
                }
                Button(
                    onClick = {
                        scope.launch {
                            updateBusy = true
                            updateDownload = null
                            updateMessageResource = null
                            updateResult = updateManager.check(force = true)
                            updateBusy = false
                        }
                    },
                    enabled = !updateBusy,
                ) { Text(stringResource(R.string.update_check_action)) }
                val available = updateResult as? UpdateCheckResult.Available
                if (available != null) {
                    Button(
                        onClick = {
                            scope.launch {
                                updateBusy = true
                                when (val result = updateManager.download(available.update)) {
                                    is UpdateDownloadResult.Ready -> {
                                        updateDownload = result
                                        updateMessageResource = null
                                    }
                                    is UpdateDownloadResult.Failed -> updateMessageResource = R.string.update_download_failed
                                }
                                updateBusy = false
                            }
                        },
                        enabled = !updateBusy,
                    ) { Text(stringResource(R.string.update_download_action)) }
                }
                updateDownload?.let { ready ->
                    Button(
                        onClick = {
                            updateMessageResource = when (onInstallUpdate(ready)) {
                                InstallLaunchResult.INSTALLER_OPENED -> R.string.update_installer_opened
                                InstallLaunchResult.PERMISSION_OPENED -> R.string.update_permission_required
                                InstallLaunchResult.REJECTED -> R.string.update_install_rejected
                            }
                        },
                        enabled = !updateBusy,
                    ) { Text(stringResource(R.string.update_install_action)) }
                }
                updateMessageResource?.let { Text(stringResource(it), color = MaterialTheme.colorScheme.error) }
            }
            HorizontalDivider(Modifier.padding(vertical = 20.dp))
            Text(stringResource(R.string.account_deletion_title), fontWeight = FontWeight.Bold, fontSize = 20.sp)
            Text(stringResource(R.string.account_deletion_warning), color = MaterialTheme.colorScheme.error)
        }
        item {
            OutlinedTextField(
                value = phone,
                onValueChange = { phone = it.trim() },
                label = { Text(stringResource(R.string.auth_phone)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = code,
                    onValueChange = { code = it.trim() },
                    label = { Text(stringResource(R.string.auth_sms_code)) },
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                )
                Button(
                    onClick = {
                        scope.launch {
                            when (val result = authenticationRepository.requestAccountDeletionChallenge(phone)) {
                                is ApiResult.Success -> {
                                    challengeId = result.value.id
                                    messageResource = R.string.auth_code_sent
                                }
                                is ApiResult.Failure -> messageResource = R.string.auth_request_failed
                            }
                        }
                    },
                    enabled = isValidE164Phone(phone),
                ) { Text(stringResource(R.string.auth_request_code)) }
            }
            OutlinedTextField(
                value = confirmUsername,
                onValueChange = { confirmUsername = it.trim() },
                label = { Text(stringResource(R.string.account_deletion_confirm_username)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            messageResource?.let { Text(stringResource(it), color = MaterialTheme.colorScheme.error) }
            Button(
                onClick = {
                    val currentChallenge = challengeId ?: return@Button
                    scope.launch {
                        when (val result = authenticationRepository.requestAccountDeletion(phone, currentChallenge, code)) {
                            is ApiResult.Success -> {
                                val localCleanupComplete = uploadQueueCoordinator.clearUserData(user.id)
                                onAccountDeletionScheduled(localCleanupComplete)
                            }
                            is ApiResult.Failure -> {
                                if (result.kind == com.smartscan.data.repository.FailureKind.LOCAL_STORAGE) {
                                    val localCleanupComplete = uploadQueueCoordinator.clearUserData(user.id)
                                    onAccountDeletionScheduled(localCleanupComplete)
                                } else {
                                    messageResource = R.string.account_deletion_failed
                                }
                            }
                        }
                    }
                },
                enabled = validateDeletionForm(
                    phone = phone,
                    code = code,
                    confirmedUsername = confirmUsername,
                    expectedUsername = user.username,
                    challengeReady = challengeId != null,
                ).valid,
            ) { Text(stringResource(R.string.account_deletion_action)) }
        }
    }
}

private sealed class AppDestination(
    val route: String,
    val labelResource: Int,
    val symbol: String,
) {
    data object Home : AppDestination("home", R.string.home, "⌂")
    data object Projects : AppDestination("projects", R.string.projects, "▤")
    data object Settings : AppDestination("settings", R.string.settings, "⚙")
}

private const val CaptureRoute = "capture/{mode}"

@Composable
private fun SmartScanHome(onModeSelected: (CaptureMode) -> Unit) {
    Column(Modifier.fillMaxSize().background(Paper).padding(horizontal = 20.dp, vertical = 30.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text("⌗  SmartScan", fontWeight = FontWeight.Black, fontSize = 20.sp)
            Surface(shape = RoundedCornerShape(50), color = Color.White) {
                Text(stringResource(R.string.ready), Modifier.padding(12.dp, 7.dp), color = Color(0xFF24794A), fontSize = 11.sp)
            }
        }
        Spacer(Modifier.height(62.dp))
        Text(stringResource(R.string.headline), fontWeight = FontWeight.Black, fontSize = 46.sp, lineHeight = 48.sp, letterSpacing = (-1.6).sp)
        Spacer(Modifier.height(36.dp))
        ScanModeCard(
            stringResource(R.string.smart_scan),
            stringResource(R.string.smart_scan_description),
            Ink,
            Color.White,
        ) { onModeSelected(CaptureMode.DOCUMENT) }
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.weight(1f)) {
                ScanModeCard(
                    stringResource(R.string.exam_clean),
                    stringResource(R.string.exam_clean_description),
                    Color.White,
                    Ink,
                ) { onModeSelected(CaptureMode.EXAM) }
            }
            Box(Modifier.weight(1f)) {
                ScanModeCard(
                    stringResource(R.string.book_scan),
                    stringResource(R.string.book_scan_description),
                    Color.White,
                    Ink,
                ) { onModeSelected(CaptureMode.BOOK) }
            }
        }
    }
}

@Composable
private fun PlaceholderScreen(titleResource: Int, descriptionResource: Int) {
    Column(
        modifier = Modifier.fillMaxSize().background(Paper).padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(stringResource(titleResource), fontWeight = FontWeight.Black, fontSize = 32.sp)
        Spacer(Modifier.height(12.dp))
        Text(stringResource(descriptionResource), color = Color(0xFF4B5563))
    }
}

@Composable
private fun ScanModeCard(
    title: String,
    subtitle: String,
    background: Color,
    foreground: Color,
    onClick: () -> Unit,
) {
    Surface(onClick = onClick, color = background, shape = RoundedCornerShape(24.dp), modifier = Modifier.fillMaxWidth().height(150.dp)) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.SpaceBetween) {
            Surface(color = Mint, shape = RoundedCornerShape(14.dp)) { Text("⌗", Modifier.padding(12.dp), color = Ink, fontSize = 22.sp) }
            Column { Text(title, color = foreground, fontWeight = FontWeight.Bold, fontSize = 20.sp); Text(subtitle, color = if (foreground == Color.White) Color(0xFFB8C0CC) else Color(0xFF747B86), fontSize = 12.sp) }
        }
    }
}

