package com.smartscan.data.local

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import com.smartscan.core.upload.LocalUploadProject
import com.smartscan.core.upload.QueuedUpload
import com.smartscan.core.upload.UploadQueueStatus
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class RoomUploadQueueStoreTest {
    private lateinit var database: SmartScanDatabase
    private lateinit var store: RoomUploadQueueStore

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        database = Room.inMemoryDatabaseBuilder(context, SmartScanDatabase::class.java).allowMainThreadQueries().build()
        store = RoomUploadQueueStore(database.uploadQueue())
    }

    @After
    fun tearDown() {
        database.close()
    }

    @Test
    fun `queue is ordered and isolated by owner`() = runTest {
        store.enqueue(project("user-a", "local-1"), upload("user-a", "first", 1))
        store.enqueue(project("user-a", "local-1"), upload("user-a", "second", 2))
        store.enqueue(project("user-b", "local-1"), upload("user-b", "other", 1))

        assertEquals("first", store.nextPending("user-a", "local-1")?.id)
        assertEquals(listOf("local-1"), store.pendingProjectIds("user-a"))
        assertEquals("other", store.nextPending("user-b", "local-1")?.id)
    }

    @Test
    fun `session progress and completion preserve next page`() = runTest {
        store.enqueue(project("user-a", "local-1"), upload("user-a", "first", 1))
        store.enqueue(project("user-a", "local-1"), upload("user-a", "second", 2))

        store.setServerProjectId("user-a", "local-1", "server-project")
        store.setUploadSession("user-a", "first", "server-upload", "a".repeat(64), 10, UploadQueueStatus.UPLOADING)
        store.updateProgress("user-a", "first", 20)
        store.markCompleted("user-a", "first", "page-1")

        assertEquals("server-project", store.project("user-a", "local-1")?.serverProjectId)
        assertEquals("second", store.nextPending("user-a", "local-1")?.id)
    }

    @Test
    fun `completed project leaves no pending work`() = runTest {
        store.enqueue(project("user-a", "local-1"), upload("user-a", "only", 1))
        store.markCompleted("user-a", "only", "page-1")

        assertNull(store.nextPending("user-a", "local-1"))
        assertEquals(emptyList<String>(), store.pendingProjectIds("user-a"))
    }

    @Test
    fun `clearing one owner removes only that owners queue`() = runTest {
        store.enqueue(project("user-a", "local-1"), upload("user-a", "first", 1))
        store.enqueue(project("user-b", "local-1"), upload("user-b", "other", 1))

        assertEquals(listOf("local-1"), store.allProjectIds("user-a"))
        assertEquals(listOf("/private/first.jpg"), store.localPaths("user-a"))
        store.clearUser("user-a")

        assertEquals(emptyList<String>(), store.allProjectIds("user-a"))
        assertEquals(emptyList<String>(), store.localPaths("user-a"))
        assertEquals("other", store.nextPending("user-b", "local-1")?.id)
    }

    private fun project(owner: String, localId: String) = LocalUploadProject(owner, localId, "扫描", "document", null)

    private fun upload(owner: String, id: String, order: Long) = QueuedUpload(
        ownerUserId = owner,
        id = id,
        localProjectId = "local-1",
        localPath = "/private/$id.jpg",
        fileName = "$id.jpg",
        mimeType = "image/jpeg",
        sizeBytes = 20,
        sha256 = null,
        idempotencyKey = "idem-$owner-$id",
        serverUploadId = null,
        uploadedBytes = 0,
        status = UploadQueueStatus.QUEUED,
        pageId = null,
        errorCode = null,
        createdAtEpochMs = order,
    )
}

@RunWith(RobolectricTestRunner::class)
class UploadQueueMigrationTest {
    @Test
    fun `version one database upgrades with upload queue tables`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val databaseName = "migration-${System.nanoTime()}.db"
        val helper = FrameworkSQLiteOpenHelperFactory().create(
            SupportSQLiteOpenHelper.Configuration.builder(context)
                .name(databaseName)
                .callback(object : SupportSQLiteOpenHelper.Callback(1) {
                    override fun onCreate(db: SupportSQLiteDatabase) {
                        db.execSQL(
                            "CREATE TABLE IF NOT EXISTS cached_projects (" +
                                "owner_user_id TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL, suggestedName TEXT, " +
                                "mode TEXT NOT NULL, readingOrder TEXT NOT NULL, createdAt TEXT NOT NULL, updatedAt TEXT NOT NULL, " +
                                "PRIMARY KEY(owner_user_id, id))",
                        )
                    }

                    override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
                })
                .build(),
        )
        helper.writableDatabase
        helper.close()

        val upgraded = Room.databaseBuilder(context, SmartScanDatabase::class.java, databaseName)
            .addMigrations(MIGRATION_1_2)
            .allowMainThreadQueries()
            .build()
        val db = upgraded.openHelper.writableDatabase
        val cursor = db.query("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'queued_uploads'")
        cursor.use { assertNotNull(if (it.moveToFirst()) it.getString(0) else null) }
        upgraded.close()
        context.deleteDatabase(databaseName)
    }
}
