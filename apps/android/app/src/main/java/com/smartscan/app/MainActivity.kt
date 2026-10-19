package com.smartscan.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { SmartScanHome() }
    }
}

private val Ink = Color(0xFF111827)
private val Paper = Color(0xFFF4F1EB)
private val Mint = Color(0xFFB7F7D4)

@Composable
fun SmartScanHome() {
    MaterialTheme(colorScheme = lightColorScheme(primary = Ink, background = Paper)) {
        Column(Modifier.fillMaxSize().background(Paper).padding(horizontal = 20.dp, vertical = 30.dp)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text("⌗  SmartScan", fontWeight = FontWeight.Black, fontSize = 20.sp)
                Surface(shape = RoundedCornerShape(50), color = Color.White) { Text("●  READY", Modifier.padding(12.dp, 7.dp), color = Color(0xFF24794A), fontSize = 11.sp) }
            }
            Spacer(Modifier.height(62.dp))
            Text(stringResource(R.string.headline), fontWeight = FontWeight.Black, fontSize = 46.sp, lineHeight = 48.sp, letterSpacing = (-1.6).sp)
            Spacer(Modifier.height(36.dp))
            ScanModeCard(stringResource(R.string.smart_scan), "Auto crop · Enhance · Rotate", Ink, Color.White)
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Box(Modifier.weight(1f)) { ScanModeCard(stringResource(R.string.exam_clean), "✦", Color.White, Ink) }
                Box(Modifier.weight(1f)) { ScanModeCard(stringResource(R.string.book_scan), "◫", Color.White, Ink) }
            }
        }
    }
}

@Composable
private fun ScanModeCard(title: String, subtitle: String, background: Color, foreground: Color) {
    Surface(onClick = { /* CameraX capture flow is wired in the next milestone. */ }, color = background, shape = RoundedCornerShape(24.dp), modifier = Modifier.fillMaxWidth().height(150.dp)) {
        Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.SpaceBetween) {
            Surface(color = Mint, shape = RoundedCornerShape(14.dp)) { Text("⌗", Modifier.padding(12.dp), color = Ink, fontSize = 22.sp) }
            Column { Text(title, color = foreground, fontWeight = FontWeight.Bold, fontSize = 20.sp); Text(subtitle, color = if (foreground == Color.White) Color(0xFFB8C0CC) else Color(0xFF747B86), fontSize = 12.sp) }
        }
    }
}

