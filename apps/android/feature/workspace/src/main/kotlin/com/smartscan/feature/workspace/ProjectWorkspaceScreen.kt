package com.smartscan.feature.workspace

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.weight
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.smartscan.core.model.DownloadedArtifact
import com.smartscan.core.model.ProjectExport
import com.smartscan.core.model.ScanPage
import com.smartscan.core.model.ScanProject
import com.smartscan.data.repository.ApiResult
import com.smartscan.data.repository.ProjectRepository
import java.io.File
import kotlinx.coroutines.launch

private val DefaultCorners = listOf(0f to 0f, 1f to 0f, 1f to 1f, 0f to 1f)

@Composable
fun ProjectWorkspaceScreen(
    repository: ProjectRepository,
    previewDirectory: File,
    exportDirectory: File,
    onShare: (DownloadedArtifact) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var projects by remember { mutableStateOf<List<ScanProject>>(emptyList()) }
    var selectedProject by remember { mutableStateOf<ScanProject?>(null) }
    var pages by remember { mutableStateOf<List<ScanPage>>(emptyList()) }
    var selectedPage by remember { mutableStateOf<ScanPage?>(null) }
    var currentExport by remember { mutableStateOf<ProjectExport?>(null) }
    var loading by remember { mutableStateOf(true) }
    var failed by remember { mutableStateOf(false) }

    fun loadProjects() {
        scope.launch {
            loading = true
            failed = false
            when (val result = repository.listProjects()) {
                is ApiResult.Success -> projects = result.value
                is ApiResult.Failure -> failed = true
            }
            loading = false
        }
    }

    fun loadPages(project: ScanProject) {
        scope.launch {
            loading = true
            failed = false
            when (val result = repository.listPages(project.id)) {
                is ApiResult.Success -> pages = result.value
                is ApiResult.Failure -> failed = true
            }
            loading = false
        }
    }

    LaunchedEffect(Unit) { loadProjects() }

    when {
        loading && selectedProject == null -> LoadingPanel()
        selectedProject == null -> ProjectList(
            projects = projects,
            failed = failed,
            onRefresh = ::loadProjects,
            onSelect = {
                selectedProject = it
                selectedPage = null
                currentExport = null
                loadPages(it)
            },
        )
        else -> ProjectDetail(
            project = requireNotNull(selectedProject),
            pages = pages,
            selectedPage = selectedPage,
            currentExport = currentExport,
            previewDirectory = previewDirectory,
            busy = loading,
            failed = failed,
            onBack = {
                selectedProject = null
                selectedPage = null
                currentExport = null
            },
            onRefresh = { loadPages(requireNotNull(selectedProject)) },
            onSelectPage = { selectedPage = it },
            onMove = { page, delta ->
                val ids = movePage(pages.map { it.id }, pages.indexOfFirst { it.id == page.id }, delta)
                if (ids != null) scope.launch {
                    loading = true
                    when (val result = repository.reorderPages(requireNotNull(selectedProject).id, ids)) {
                        is ApiResult.Success -> pages = result.value
                        is ApiResult.Failure -> failed = true
                    }
                    loading = false
                }
            },
            onPageUpdated = { updated ->
                pages = pages.map { if (it.id == updated.id) updated else it }.sortedBy { it.pageNumber }
                selectedPage = updated
            },
            onCreateExport = { format, quality, includeOcr ->
                scope.launch {
                    loading = true
                    when (val result = repository.createExport(requireNotNull(selectedProject).id, format, quality, includeOcr)) {
                        is ApiResult.Success -> currentExport = result.value
                        is ApiResult.Failure -> failed = true
                    }
                    loading = false
                }
            },
            onShareArtifact = { artifact ->
                scope.launch {
                    loading = true
                    when (val result = repository.downloadExportArtifact(artifact, exportDirectory)) {
                        is ApiResult.Success -> onShare(result.value)
                        is ApiResult.Failure -> failed = true
                    }
                    loading = false
                }
            },
            repository = repository,
        )
    }
}

@Composable
private fun LoadingPanel() {
    Column(Modifier.fillMaxSize(), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
        CircularProgressIndicator()
        Spacer(Modifier.height(12.dp))
        Text(stringResource(R.string.workspace_busy))
    }
}

@Composable
private fun ProjectList(
    projects: List<ScanProject>,
    failed: Boolean,
    onRefresh: () -> Unit,
    onSelect: (ScanProject) -> Unit,
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.workspace_title), fontWeight = FontWeight.Black, fontSize = 30.sp)
                OutlinedButton(onClick = onRefresh) { Text(stringResource(R.string.workspace_refresh)) }
            }
            if (failed) Text(stringResource(R.string.workspace_load_failed), color = MaterialTheme.colorScheme.error)
            if (projects.isEmpty() && !failed) Text(stringResource(R.string.workspace_empty))
        }
        items(projects, key = { it.id }) { project ->
            Card(onClick = { onSelect(project) }, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(18.dp)) {
                    Text(project.suggestedName ?: project.title, fontWeight = FontWeight.Bold, fontSize = 18.sp)
                    Text("${project.mode} · ${project.updatedAt}", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

@Composable
private fun ProjectDetail(
    project: ScanProject,
    pages: List<ScanPage>,
    selectedPage: ScanPage?,
    currentExport: ProjectExport?,
    previewDirectory: File,
    busy: Boolean,
    failed: Boolean,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    onSelectPage: (ScanPage) -> Unit,
    onMove: (ScanPage, Int) -> Unit,
    onPageUpdated: (ScanPage) -> Unit,
    onCreateExport: (String, String, Boolean) -> Unit,
    onShareArtifact: (com.smartscan.core.model.ExportArtifact) -> Unit,
    repository: ProjectRepository,
) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            TextButton(onClick = onBack) { Text(stringResource(R.string.workspace_back)) }
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Text(project.suggestedName ?: project.title, fontWeight = FontWeight.Black, fontSize = 26.sp)
                OutlinedButton(onClick = onRefresh, enabled = !busy) { Text(stringResource(R.string.workspace_refresh)) }
            }
            if (busy) Text(stringResource(R.string.workspace_busy))
            if (failed) Text(stringResource(R.string.workspace_action_failed), color = MaterialTheme.colorScheme.error)
            Text(stringResource(R.string.workspace_pages), fontWeight = FontWeight.Bold)
        }
        items(pages, key = { it.id }) { page ->
            Card(onClick = { onSelectPage(page) }, modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(14.dp)) {
                    Text(stringResource(R.string.workspace_page, page.pageNumber), fontWeight = FontWeight.Bold)
                    Text("${page.reviewStatus} · ${page.ocrStatus}", style = MaterialTheme.typography.bodySmall)
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        TextButton(onClick = { onMove(page, -1) }, enabled = page.pageNumber > 1 && !busy) {
                            Text(stringResource(R.string.workspace_move_up))
                        }
                        TextButton(onClick = { onMove(page, 1) }, enabled = page.pageNumber < pages.size && !busy) {
                            Text(stringResource(R.string.workspace_move_down))
                        }
                        TextButton(onClick = { onSelectPage(page) }) { Text(stringResource(R.string.workspace_edit)) }
                    }
                }
            }
        }
        selectedPage?.let { page ->
            item {
                HorizontalDivider()
                PageEditor(page, previewDirectory, repository, busy, onPageUpdated)
            }
        }
        item {
            HorizontalDivider()
            ExportPanel(currentExport, busy, onCreateExport, onShareArtifact)
        }
    }
}

@Composable
private fun PageEditor(
    page: ScanPage,
    previewDirectory: File,
    repository: ProjectRepository,
    busy: Boolean,
    onUpdated: (ScanPage) -> Unit,
) {
    val scope = rememberCoroutineScope()
    var previewPath by remember(page.id) { mutableStateOf<String?>(null) }
    var corners by remember(page.id) { mutableStateOf(DefaultCorners) }
    var filter by remember(page.id) { mutableStateOf("original") }
    var failed by remember(page.id) { mutableStateOf(false) }

    LaunchedEffect(page.id, page.activeResultVersion) {
        when (val result = repository.downloadPagePreview(page.id, previewDirectory)) {
            is ApiResult.Success -> previewPath = result.value.filePath
            is ApiResult.Failure -> failed = true
        }
    }

    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(stringResource(R.string.workspace_page, page.pageNumber), fontWeight = FontWeight.Bold, fontSize = 20.sp)
        previewPath?.let { path ->
            remember(path) { BitmapFactory.decodeFile(path) }?.let { bitmap ->
                Image(
                    bitmap = bitmap.asImageBitmap(),
                    contentDescription = stringResource(R.string.workspace_page, page.pageNumber),
                    modifier = Modifier.fillMaxWidth().height(260.dp),
                    contentScale = ContentScale.Fit,
                )
            }
        } ?: Text(stringResource(R.string.workspace_preview_unavailable))
        if (failed) Text(stringResource(R.string.workspace_action_failed), color = MaterialTheme.colorScheme.error)
        Button(
            onClick = {
                scope.launch {
                    when (val result = repository.rotatePage(page.id, 90)) {
                        is ApiResult.Success -> onUpdated(result.value)
                        is ApiResult.Failure -> failed = true
                    }
                }
            },
            enabled = !busy,
        ) { Text(stringResource(R.string.workspace_rotate)) }
        Text(stringResource(R.string.workspace_filter), fontWeight = FontWeight.Bold)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf(
                "original" to R.string.workspace_filter_original,
                "enhance" to R.string.workspace_filter_enhance,
                "grayscale" to R.string.workspace_filter_grayscale,
                "bw" to R.string.workspace_filter_bw,
            ).forEach { (value, label) ->
                AssistChip(onClick = { filter = value }, label = { Text(stringResource(label)) }, enabled = filter != value)
            }
        }
        Text(stringResource(R.string.workspace_corners), fontWeight = FontWeight.Bold)
        corners.forEachIndexed { index, corner ->
            Text(stringResource(R.string.workspace_corner, index + 1))
            CoordinateSlider(stringResource(R.string.workspace_x), corner.first) { value ->
                corners = corners.toMutableList().also { it[index] = value to it[index].second }
            }
            CoordinateSlider(stringResource(R.string.workspace_y), corner.second) { value ->
                corners = corners.toMutableList().also { it[index] = it[index].first to value }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = {
                    scope.launch {
                        when (val result = repository.editPage(page.id, corners.map { it.first.toDouble() to it.second.toDouble() }, filter)) {
                            is ApiResult.Success -> onUpdated(result.value)
                            is ApiResult.Failure -> failed = true
                        }
                    }
                },
                enabled = !busy,
            ) { Text(stringResource(R.string.workspace_save_edit)) }
            OutlinedButton(
                onClick = {
                    scope.launch {
                        when (val result = repository.reviewPage(page.id, true)) {
                            is ApiResult.Success -> onUpdated(result.value)
                            is ApiResult.Failure -> failed = true
                        }
                    }
                },
                enabled = !busy && page.reviewStatus != "confirmed",
            ) { Text(stringResource(R.string.workspace_confirm_review)) }
        }
    }
}

@Composable
private fun CoordinateSlider(label: String, value: Float, onChange: (Float) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, modifier = Modifier.width(70.dp))
        Slider(value = value, onValueChange = onChange, valueRange = 0f..1f, modifier = Modifier.weight(1f))
        Text("%.2f".format(value), modifier = Modifier.width(44.dp))
    }
}

@Composable
private fun ExportPanel(
    currentExport: ProjectExport?,
    busy: Boolean,
    onCreate: (String, String, Boolean) -> Unit,
    onShare: (com.smartscan.core.model.ExportArtifact) -> Unit,
) {
    var format by remember { mutableStateOf("pdf") }
    var quality by remember { mutableStateOf("balanced") }
    var includeOcr by remember { mutableStateOf(true) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(stringResource(R.string.workspace_export), fontWeight = FontWeight.Bold, fontSize = 20.sp)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            AssistChip(onClick = { format = "pdf" }, label = { Text(stringResource(R.string.workspace_pdf)) }, enabled = format != "pdf")
            AssistChip(onClick = { format = "jpg" }, label = { Text(stringResource(R.string.workspace_jpg)) }, enabled = format != "jpg")
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(
                "clear" to R.string.workspace_clear,
                "balanced" to R.string.workspace_balanced,
                "small" to R.string.workspace_small,
            ).forEach { (value, label) ->
                AssistChip(onClick = { quality = value }, label = { Text(stringResource(label)) }, enabled = quality != value)
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = includeOcr, onCheckedChange = { includeOcr = it }, enabled = format == "pdf")
            Text(stringResource(R.string.workspace_include_ocr))
        }
        Button(onClick = { onCreate(format, quality, includeOcr && format == "pdf") }, enabled = !busy) {
            Text(stringResource(R.string.workspace_create_export))
        }
        currentExport?.artifacts?.forEach { artifact ->
            OutlinedButton(onClick = { onShare(artifact) }, enabled = !busy) {
                Text(stringResource(R.string.workspace_share, artifact.fileName))
            }
        }
    }
}

internal fun movePage(ids: List<String>, index: Int, delta: Int): List<String>? {
    val target = index + delta
    if (index !in ids.indices || target !in ids.indices) return null
    return ids.toMutableList().also { java.util.Collections.swap(it, index, target) }
}
