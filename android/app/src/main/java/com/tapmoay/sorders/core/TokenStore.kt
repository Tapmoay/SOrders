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

    /**
     * 当前角色（dispatcher/shipper/driver）的**同步**缓存。
     *
     * 为什么需要它：AI 的动作清单和权限判断都是**同步**调用的（在 tools.specs 和
     * writeService.preview 里），而 sessionFlow 是冷流、跑 DataStore IO。
     * 走流的话每帧都要起协程读盘，做不到。
     */
    @Volatile
    private var cachedRole: String? = null

    @Volatile
    private var cachedUserId: Long? = null

    private object Keys {
        val TOKEN = stringPreferencesKey("token")
        val ROLE = stringPreferencesKey("role")
        val USER_ID = longPreferencesKey("user_id")
        val USERNAME = stringPreferencesKey("username")
        val FULL_NAME = stringPreferencesKey("full_name")
    }

    /** 供 OkHttp 拦截器跨线程读取 */
    fun cachedToken(): String? = cachedToken

    /** 供 AI 层同步判断「这个角色能用哪些动作」（见 AiWrites.forRole）。 */
    fun cachedRole(): String? = cachedRole

    /**
     * 当前登录用户 id 的**同步**缓存。
     *
     * AI 的三份本机数据（对话/习惯/记忆）按它分区（见 `AiScope`）——
     * 分区名必须是同步能拿到的，否则每个 store 构造时都要起协程读盘。
     */
    fun cachedUserId(): Long? = cachedUserId

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
        cachedRole = session.role
        cachedUserId = session.userId
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
        cachedRole = null
        cachedUserId = null
        context.sessionDataStore.edit { p -> p.clear() }
    }

    /** 供启动时同步缓存（拦截器需要） */
    fun warmCache() {
        if (cachedToken == null) {
            val s = runBlocking { current() }
            cachedToken = s?.token
            cachedRole = s?.role
            cachedUserId = s?.userId
        }
    }
}
