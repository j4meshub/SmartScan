package com.smartscan.data.local

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.smartscan.core.model.ScanProject
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class RoomUserScopedCacheTest {
    private lateinit var database: SmartScanDatabase
    private lateinit var cache: RoomUserScopedCache

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        database = Room.inMemoryDatabaseBuilder(context, SmartScanDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        cache = RoomUserScopedCache(database.cachedProjects())
    }

    @After
    fun tearDown() = database.close()

    @Test
    fun `same project id remains isolated between users`() = runTest {
        cache.replaceProjects("user-a", listOf(project("shared", "用户 A")))
        cache.replaceProjects("user-b", listOf(project("shared", "用户 B")))

        assertEquals("用户 A", cache.listProjects("user-a").single().title)
        assertEquals("用户 B", cache.listProjects("user-b").single().title)
    }

    @Test
    fun `clearing one user leaves another user cache intact`() = runTest {
        cache.replaceProjects("user-a", listOf(project("p1", "用户 A")))
        cache.replaceProjects("user-b", listOf(project("p2", "用户 B")))

        cache.clearUser("user-a")

        assertEquals(emptyList<ScanProject>(), cache.listProjects("user-a"))
        assertEquals("用户 B", cache.listProjects("user-b").single().title)
    }

    @Test(expected = IllegalArgumentException::class)
    fun `blank user id is rejected before cache access`() = runTest {
        cache.listProjects("")
    }

    private fun project(id: String, title: String) = ScanProject(
        id = id,
        title = title,
        suggestedName = null,
        mode = "document",
        readingOrder = "ltr",
        createdAt = "2026-10-20T00:00:00Z",
        updatedAt = "2026-10-20T00:00:00Z",
    )
}
