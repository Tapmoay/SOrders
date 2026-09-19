package com.tapmoay.sorders.core

/**
 * 按「人」搜索的**唯一实现**：姓名 或 手机号，子串匹配。
 *
 * 用户 2026-09-19 原话：
 * 「还有其他的比如说，**司机管理**啊**账户管理**啊。这些也要添加搜索键。
 *   然后这个搜索键可以根据他们的**名称**还有**电话号码**以及**电话号码的后 4 位**进行搜索」。
 *
 * ## 为什么单独一个文件
 *
 * 这条规则在本项目里有两类消费点，而且**必须是同一个口径**：
 *
 * | 消费点 | 数据从哪来 | 怎么搜 |
 * |---|---|---|
 * | 账本仪表盘（司机账/货主账/批发商账） | `/ledger/accounts`、`/freight-settlement` **一次回全量**（没有分页） | 本地用 [matches] |
 * | 司机/货主/批发商/账户管理 | `/users` **一页最多 500 条**（`X-Truncated`） | 服务端 `?q=`（同一个判据的后端实现：`app/core/user_search.py`） |
 *
 * 两张表看起来是"两套实现"，其实是**同一条规则按数据是否完整分流**：
 * 名册超过 500 人时本地过滤**必然漏人**（第 501 个在客户端根本不存在，
 * 而"列表里没有"会被读成"这个账号不存在"→ 再建一个 → 撞手机号唯一约束）。
 * 账本那两张接口本来就回全量，做成服务端过滤只是每次打字多打一次后端，没有收益。
 *
 * ⛔ **后 4 位不是额外一条规则**：手机号走子串匹配，`8001` 天然命中 `13800008001`。
 *    所以这里刻意**不写**「取后四位再比」的分支 —— 多一条分支就多一个会跟主规则分叉的地方，
 *    而分叉的表现是"搜得到 / 搜不到"，用户只会觉得系统坏了，不会觉得是两条规则。
 *    单测 `UserSearchTest` 把三种写法都钉住了。
 *
 * ⚠️ 大小写：后端那份用 `func.lower()` 显式对齐（MySQL 的 `like` 默认不分大小写、
 *    SQLite 区分，不写就是"开发库能搜到、生产库搜不到"）。这边用 [ignoreCase]＝true 对齐。
 */
object UserSearch {

    /** 搜索框的提示文案（各页**同源**：改口径只改这里，不许各页抄一份）。 */
    const val HINT: String = "搜姓名 / 手机号（后 4 位也行）"

    /** 搜不到时那句话里的「X」（同样是同源的）。 */
    fun noMatchText(query: String): String = "没有名称或手机号含「" + query.trim() + "」的"

    /**
     * 这一段查询词命不命中这个人。
     *
     * - `query` 空白 → **恒 true**（= 没在搜，条件不生效；不是"搜空串"）
     * - `name` / `phone` 允许 null 或空串（临时货主没有手机号、老数据可能没有姓名）
     */
    fun matches(query: String, name: String?, phone: String?): Boolean {
        val q = query.trim()
        if (q.isEmpty()) return true
        if (name?.contains(q, ignoreCase = true) == true) return true
        if (phone?.contains(q, ignoreCase = true) == true) return true
        return false
    }

    /** 在 [matches] 的基础上过滤一列人（顺序保持不变 —— 服务端已按金额/编号排好了）。 */
    fun <T> filter(items: List<T>, query: String, name: (T) -> String?, phone: (T) -> String?): List<T> {
        val q = query.trim()
        return if (q.isEmpty()) items else items.filter { matches(q, name(it), phone(it)) }
    }
}
