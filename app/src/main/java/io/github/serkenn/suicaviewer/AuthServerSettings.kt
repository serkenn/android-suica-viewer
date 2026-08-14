package io.github.serkenn.suicaviewer

import android.content.Context

/**
 * Stores the authentication server the app talks to.
 *
 * [DEFAULT_AUTH_SERVER_URL] is the built-in default and is what a fresh install
 * (or a cleared setting) uses; anyone running their own auth server can point
 * the app at it instead, and the choice survives restarts.
 */
object AuthServerSettings {
    private const val PREFS_NAME = "suica_viewer_settings"
    private const val KEY_SERVER_URL = "auth_server_url"

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    /** The server in use: the stored one, or the built-in default. */
    fun load(context: Context): String {
        val stored = prefs(context).getString(KEY_SERVER_URL, null)?.trim()
        return if (stored.isNullOrEmpty()) DEFAULT_AUTH_SERVER_URL else stored
    }

    /**
     * Stores [url], or clears the setting (back to the default) when it is
     * blank. Returns the server that is in use afterwards.
     *
     * @throws FelicaRemoteClientError if [url] is not a usable http(s) URL.
     */
    fun save(context: Context, url: String): String {
        val trimmed = url.trim()
        if (trimmed.isEmpty()) {
            prefs(context).edit().remove(KEY_SERVER_URL).apply()
            return DEFAULT_AUTH_SERVER_URL
        }
        val validated = validateServerUrl(trimmed)
        prefs(context).edit().putString(KEY_SERVER_URL, validated).apply()
        return validated
    }
}
