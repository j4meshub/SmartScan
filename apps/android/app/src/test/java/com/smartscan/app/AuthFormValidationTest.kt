package com.smartscan.app

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AuthFormValidationTest {
    @Test
    fun `login requires server-compatible username and password length`() {
        assertTrue(validateAuthForm(false, "", "", "student.1", "long-password", false).valid)
        assertFalse(validateAuthForm(false, "", "", "ab", "long-password", false).valid)
        assertFalse(validateAuthForm(false, "", "", "student", "short", false).valid)
    }

    @Test
    fun `registration additionally requires E164 phone challenge and code`() {
        assertTrue(
            validateAuthForm(true, "+8613800001234", "123456", "student", "long-password", true).valid,
        )
        assertFalse(
            validateAuthForm(true, "13800001234", "123456", "student", "long-password", true).valid,
        )
        assertFalse(
            validateAuthForm(true, "+8613800001234", "123456", "student", "long-password", false).valid,
        )
    }

    @Test
    fun `account deletion requires E164 phone challenge and exact username`() {
        assertTrue(validateDeletionForm("+8613800001234", "123456", "student", "student", true).valid)
        assertFalse(validateDeletionForm("13800001234", "123456", "student", "student", true).valid)
        assertFalse(validateDeletionForm("+8613800001234", "123456", "Student", "student", true).valid)
        assertFalse(validateDeletionForm("+8613800001234", "123456", "student", "student", false).valid)
    }

    @Test
    fun `deletion cancellation requires E164 phone code and challenge`() {
        assertTrue(validateDeletionCancellation("+8613800001234", "123456", true).valid)
        assertFalse(validateDeletionCancellation("13800001234", "123456", true).valid)
        assertFalse(validateDeletionCancellation("+8613800001234", "12", true).valid)
    }
}
