package com.smartscan.app

data class AuthFormValidation(val valid: Boolean)

private val E164_PHONE = Regex("^\\+[1-9][0-9]{7,14}$")

fun isValidE164Phone(phone: String): Boolean = phone.matches(E164_PHONE)

fun validateAuthForm(
    registration: Boolean,
    phone: String,
    code: String,
    username: String,
    password: String,
    challengeReady: Boolean,
): AuthFormValidation {
    val credentialsValid = username.matches(Regex("^[A-Za-z0-9_.-]{3,32}$")) && password.length in 10..128
    if (!registration) return AuthFormValidation(credentialsValid)
    val registrationValid = isValidE164Phone(phone) &&
        code.length in 4..8 &&
        challengeReady
    return AuthFormValidation(credentialsValid && registrationValid)
}

fun validateDeletionForm(
    phone: String,
    code: String,
    confirmedUsername: String,
    expectedUsername: String,
    challengeReady: Boolean,
): AuthFormValidation = AuthFormValidation(
    isValidE164Phone(phone) &&
        code.length in 4..8 &&
        confirmedUsername == expectedUsername &&
        challengeReady,
)

fun validateDeletionCancellation(
    phone: String,
    code: String,
    challengeReady: Boolean,
): AuthFormValidation = AuthFormValidation(
    isValidE164Phone(phone) && code.length in 4..8 && challengeReady,
)
