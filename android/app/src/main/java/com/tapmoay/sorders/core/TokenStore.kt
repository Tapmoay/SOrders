package com.tapmoay.sorders.core

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.runBlocking

data class Session(
    val token: String,
    val role: String,
    val userId: Long,
    val username: String,
    val fullName: String,
)

private val Context.sessionDataStore by preferencesDataStore(name = "session")

class TokenStore(private val context: Context) {

    @Volatile
    private var cachedToken: String? = null

    private object Keys {
        val TOKEN = stringPreferencesKey("token")
        val ROLE = stringPreferencesKey("role")
        val USER_ID = longPreferencesKey("user_id")
        val USERNAME = stringPreferencesKey("username")
        val FULL_NAME = stringPreferencesKey("full_name")
    }

    /** 供 OkHttp 拦截器跨线程读取 */
    fun cachedToken(): String? = cachedToken

    val sessionFlow: Flow<Session?> = context.sessionDataStore.data.map { p ->
        val token = p[Keys.TOKEN]
        if (token == null) null
        else Session(
            token = token,
            role = p[Keys.ROLE] ?: "",
            userId = p[Keys.USER_ID] ?: 0L,
            username = p[Keys.USERNAME] ?: "",
            fullName = p[Keys.FULL_NAME] ?: "",
        )
    }

    suspend fun current(): Session? = sessionFlow.first()

    suspend fun save(session: Session) {
        cachedToken = session.token
        context.sessionDataStore.edit { p ->
            p[Keys.TOKEN] = session.token
            p[Keys.ROLE] = session.role
            p[Keys.USER_ID] = session.userId
            p[Keys.USERNAME] = session.username
            p[Keys.FULL_NAME] = session.fullName
        }
    }

    suspend fun clear() {
        cachedToken = null
        context.sessionDataStore.edit { p -> p.clear() }
    }

    /** 供启动时同步缓存（拦截器需要） */
    fun warmCache() {
        if (cachedToken == null) {
            cachedToken = runBlocking { current()?.token }
        }
    }
}
