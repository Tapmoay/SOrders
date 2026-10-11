package com.tapmoay.sorders.ui.common

import com.tapmoay.sorders.core.AppContainer
import com.tapmoay.sorders.data.remote.dto.ContactDto
import com.tapmoay.sorders.data.remote.dto.UserDto
import kotlinx.coroutines.CancellationException

/**
 * 「选择联系人」弹层里那一行**「我自己」**：当前登录人自己也是一个可选的收货联系人。
 *
 * ## 为什么有它（用户 2026-10-11 逐字）
 * > 「还有一个就是线路，他不是要选择联系人吗？**收货联系人**——这个联系人**可以选择派单员本人**啊。」
 *
 * 派单员给自己下的单（顺路带一车货回去），收货人就是他自己 —— 在那之前只能把姓名与号码
 * **手打一遍**，而联系人名册里根本没有"我自己"这一行。
 *
 * ## 这个文件是全 App **唯一一处**
 * - 「把当前登录人拼成一条可选联系人」只有这一处实现（[of]）：三个调用方谁也不许自己拼一个
 *   [ContactDto] —— 三处各拼一遍，改天补一个字段（比如带备注）就会三处不一样，而这种事
 *   在界面上**看不出来**（每一处看起来都是"姓名 + 电话"）。与 `ui/shipper/OrdererPrefill.kt`
 *   同一条理由（那里是全 App 唯一一处"下单人默认值"）。
 * - 「去哪儿要姓名与电话」也只有这一处（[load] / [meOrNull]）：`GET /users/me`。
 *   ⛔ 会话（`core/TokenStore.kt::Session`）里只有 `role / userId / username / fullName`，
 *   **没有 phone**；⛔ 更不许拿 `username` 顶替电话 —— 填一个打不通的号比空着更糟。
 *
 * ## 拿不到就不显示
 * 姓名**或**电话（各自 trim 之后）只要有一个是空的，[of] 就返回 null ⇒ 弹层里**没有这一项**。
 * 宁可不显示，也不要出现一行空的「我自己」：那等于让人挑中一条空姓名 / 空电话的收货人。
 *
 * ## ⛔ 不写任何后端数据
 * [of] 造出来的是一条**内存里的**行，[SELF_ID] 是负数哨兵（联系人主键恒为正，不会撞）。
 * 挑中它只是把姓名与电话回填给调用方 —— 不新建联系人、不改名册。
 * 安全说明（两个消费点都核对过）：`OrderCreateViewModel` 把它记进 `pickedContactId` 之后，
 * 只会拿它去 `contacts` 名册里找同 id 的那一条（查不到就什么都不做）；
 * `AddressViewModel` 只拿它当"有没有选联系人"的那道闸 —— 两者都**不会**把它发给后端。
 */
object SelfContact {

    /** 「我自己」那一行的 id：负数哨兵（真实联系人 id 恒为正，不会撞 `LazyColumn` 的 key）。 */
    const val SELF_ID: Long = -1L

    /** 那一枚小标签的字（样式照「地址与联系人」页卡片上的分类标签）。 */
    const val LABEL: String = "本人"

    /** 当前登录人 → 一条可选联系人；姓名**或**电话（trim 后）为空 ⇒ **null**（＝不显示这一项）。 */
    fun of(name: String?, phone: String?): ContactDto? {
        val n = name?.trim().orEmpty()
        val p = phone?.trim().orEmpty()
        if (n.isEmpty() || p.isEmpty()) return null
        return ContactDto(id = SELF_ID, phone = p, displayName = n)
    }

    /** 同上，直接从 `GET /users/me` 的返回（`UserDto`）造。 */
    fun of(me: UserDto?): ContactDto? = me?.let { of(it.fullName, it.phone) }

    /** 是不是「我自己」那一行（弹层靠它决定画不画那枚「本人」标签）。 */
    fun isSelf(c: ContactDto): Boolean = c.id == SELF_ID

    /**
     * 把「我自己」**固定排在最前**。
     *
     * ⛔ 这里**不去重**：用户自己也存过一条同号联系人时两行都留着 —— 两条的姓名或备注可能
     * 不一样（"我自己" vs "王老板"），悄悄吞掉一条会让人以为名册里那条不见了。
     */
    fun withSelf(contacts: List<ContactDto>, self: ContactDto?): List<ContactDto> =
        if (self == null) contacts else listOf(self) + contacts

    /**
     * 全 App **唯一一处**取「我自己」的入口：拿不到（没网 / 令牌失效 / 后端不给）就是 null。
     *
     * ⛔ 失败**不许**把整页的联系人名册一起拖红：少一行「我自己」是小事，名册打不开才是真故障
     * （两个调用方的 `contactsError` 各自管自己那一条）。
     */
    suspend fun load(container: AppContainer): ContactDto? = of(meOrNull(container))

    /** 同上，只回原始资料（订单详情页那次 `/users/me` 还要 `is_member`，一次请求两用）。 */
    suspend fun meOrNull(container: AppContainer): UserDto? = try {
        container.repo.me()
    } catch (e: CancellationException) {
        // 协程被取消不是"取数失败"：原样抛出去（吞掉它会让调用方的 job 假活着）。
        throw e
    } catch (_: Exception) {
        null
    }
}
