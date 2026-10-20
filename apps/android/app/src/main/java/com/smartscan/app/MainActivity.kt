package com.smartscan.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { SmartScanApp() }
    }
}

private val Ink = Color(0xFF111827)
private val Paper = Color(0xFFF4F1EB)
private val Mint = Color(0xFFB7F7D4)

@Composable
fun SmartScanApp() {
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
                    PlaceholderScreen(R.string.settings, R.string.settings_description)
                }
            }
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

