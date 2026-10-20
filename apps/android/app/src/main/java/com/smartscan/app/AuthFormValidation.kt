package com.smartscan.app

data class AuthFormValidation(val valid: Boolean)

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
    val registrationValid = phone.startsWith("+") &&
        code.length in 4..8 &&
        challengeReady
    return AuthFormValidation(credentialsValid && registrationValid)
}
