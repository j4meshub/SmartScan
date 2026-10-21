package com.smartscan.feature.workspace

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WorkspaceStateTest {
    @Test
    fun `page can move only inside project bounds`() {
        assertEquals(listOf("b", "a", "c"), movePage(listOf("a", "b", "c"), 0, 1))
        assertEquals(listOf("a", "c", "b"), movePage(listOf("a", "b", "c"), 2, -1))
        assertNull(movePage(listOf("a", "b"), 0, -1))
        assertNull(movePage(listOf("a", "b"), 1, 1))
    }
}
