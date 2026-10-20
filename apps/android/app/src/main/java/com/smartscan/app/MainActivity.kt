package com.smartscan.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.smartscan.core.model.UserProfile
import com.smartscan.data.repository.ApiResult
import com.smartscan.data.repository.AuthenticationRepository
import com.smartscan.data.repository.RegistrationInput
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import java.util.Locale

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val repository = (application as SmartScanApplication).container.authenticationRepository
        setContent { SmartScanApp(repository) }
    }
}

private val Ink = Color(0xFF111827)
private val Paper = Color(0xFFF4F1EB)
private val Mint = Color(0xFFB7F7D4)

@Composable
fun SmartScanApp(authenticationRepository: AuthenticationRepository) {
    val authState = remember { MutableStateFlow<AuthUiState>(AuthUiState.Loading) }
    val state by authState.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    var challengeId by remember { mutableStateOf<String?>(null) }
    var messageResource by remember { mutableStateOf<Int?>(null) }

    LaunchedEffect(authenticationRepository) {
        authState.value = authenticationRepository.restore().toUiState()
    }

    when (val current = state) {
        AuthUiState.Loading -> LoadingScreen()
        AuthUiState.SignedOut -> AuthenticationScreen(
            messageResource = messageResource,
            challengeReady = challengeId != null,
            onRequestCode = { phone ->
                scope.launch {
                    messageResource = null
                    when (val result = authenticationRepository.requestRegistrationChallenge(phone)) {
                        is ApiResult.Success -> {
                            challengeId = result.value.id
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
                val currentChallenge = challengeId
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
        )
        is AuthUiState.SignedIn -> AuthenticatedApp(
            user = current.user,
            onLogout = {
                authState.value = AuthUiState.Loading
                scope.launch {
                    authenticationRepository.logout()
                    challengeId = null
                    messageResource = null
                    authState.value = AuthUiState.SignedOut
                }
            },
        )
    }
}

@Composable
private fun AuthenticatedApp(user: UserProfile, onLogout: () -> Unit) {
    MaterialTheme(colorScheme = lightColorScheme(primary = Ink, background = Paper)) {
        val navController = rememberNavController()
        val destinations = listOf(
            AppDestination.Home,
            AppDestination.Projects,
            AppDestination.Settings,
        )
        Scaffold(
            bottomBar = {
                NavigationBar {
                    val backStackEntry by navController.currentBackStackEntryAsState()
                    val currentDestination = backStackEntry?.destination
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
            },
        ) { innerPadding ->
            NavHost(
                navController = navController,
                startDestination = AppDestination.Home.route,
                modifier = Modifier.padding(innerPadding),
            ) {
                composable(AppDestination.Home.route) { SmartScanHome() }
                composable(AppDestination.Projects.route) {
                    PlaceholderScreen(R.string.projects, R.string.projects_description)
                }
                composable(AppDestination.Settings.route) {
                    SettingsScreen(user, onLogout)
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

@Composable
private fun AuthenticationScreen(
    messageResource: Int?,
    challengeReady: Boolean,
    onRequestCode: (String) -> Unit,
    onLogin: (String, String) -> Unit,
    onRegister: (String, String, String, String) -> Unit,
) {
    var registration by remember { mutableStateOf(false) }
    var phone by remember { mutableStateOf("") }
    var code by remember { mutableStateOf("") }
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    val validation = validateAuthForm(registration, phone, code, username, password, challengeReady)

    MaterialTheme(colorScheme = lightColorScheme(primary = Ink, background = Paper)) {
        Column(
            modifier = Modifier.fillMaxSize().background(Paper).padding(24.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            Text("SmartScan", fontWeight = FontWeight.Black, fontSize = 34.sp)
            Spacer(Modifier.height(8.dp))
            Text(stringResource(if (registration) R.string.auth_register_title else R.string.auth_login_title))
            Spacer(Modifier.height(24.dp))
            if (registration) {
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
                    Button(onClick = { onRequestCode(phone) }, enabled = phone.isNotBlank()) {
                        Text(stringResource(R.string.auth_request_code))
                    }
                }
                Spacer(Modifier.height(8.dp))
            }
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
            messageResource?.let {
                Spacer(Modifier.height(8.dp))
                Text(stringResource(it), color = MaterialTheme.colorScheme.error)
            }
            Spacer(Modifier.height(16.dp))
            Button(
                onClick = {
                    if (registration) onRegister(phone, code, username, password) else onLogin(username, password)
                },
                enabled = validation.valid,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(stringResource(if (registration) R.string.auth_register_action else R.string.auth_login_action))
            }
            TextButton(onClick = {
                registration = !registration
                password = ""
            }) {
                Text(stringResource(if (registration) R.string.auth_show_login else R.string.auth_show_register))
            }
        }
    }
}

@Composable
private fun SettingsScreen(user: UserProfile, onLogout: () -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().background(Paper).padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text(stringResource(R.string.settings), fontWeight = FontWeight.Black, fontSize = 32.sp)
        Spacer(Modifier.height(12.dp))
        Text(user.username)
        Text(user.phoneMasked, color = Color(0xFF4B5563))
        Spacer(Modifier.height(24.dp))
        Button(onClick = onLogout) { Text(stringResource(R.string.auth_logout)) }
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

@Composable
private fun SmartScanHome() {
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
        ScanModeCard(stringResource(R.string.smart_scan), stringResource(R.string.smart_scan_description), Ink, Color.White)
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.weight(1f)) { ScanModeCard(stringResource(R.string.exam_clean), "✦", Color.White, Ink) }
            Box(Modifier.weight(1f)) { ScanModeCard(stringResource(R.string.book_scan), "◫", Color.White, Ink) }
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
private fun ScanModeCard(title: String, subtitle: String, background: Color, foreground: Color) {
    Surface(onClick = { /* CameraX 拍摄流程由 AND-003 接入。 */ }, color = background, shape = RoundedCornerShape(24.dp), modifier = Modifier.fillMaxWidth().height(150.dp)) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.SpaceBetween) {
            Surface(color = Mint, shape = RoundedCornerShape(14.dp)) { Text("⌗", Modifier.padding(12.dp), color = Ink, fontSize = 22.sp) }
            Column { Text(title, color = foreground, fontWeight = FontWeight.Bold, fontSize = 20.sp); Text(subtitle, color = if (foreground == Color.White) Color(0xFFB8C0CC) else Color(0xFF747B86), fontSize = 12.sp) }
        }
    }
}

