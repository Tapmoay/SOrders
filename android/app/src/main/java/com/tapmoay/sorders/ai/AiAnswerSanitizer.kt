package com.tapmoay.sorders.ai

/**
 * 回答净化器：把模型答复里残留的**内部编号**抹掉。
 *
 * ### 为什么在「工具层已经不给 id」之后还需要它
 * [AiTools] 已经从源头剔除了 `id` / `*_id`（那才是主防线）。但主防线**只保住了数据**，
 * 保不住模型的行为：
 * - 多轮对话的历史里可能还留着老版本产生的编号（用户升级 App 前的旧对话）；
 * - 模型可能从「用户自己的提问」里抄一个编号回来（用户说「122 号货主」，它就会回「122 号」）；
 * - 它也可能凭空写一句「（user_id 未知）」之类。
 *
 * 而编号一旦显示在聊天页，用户就会困惑（看不懂），并且**没有任何补救机会**——
 * 所以这里做最后一道兜底。宁可多抹一次，不可漏一个。
 *
 * ### 刻意收窄，避免误伤
 * 只匹配「编号关键词 + 数字」这种**成对出现**的形状。绝不碰：
 * - 订单号（`SOTEST2026091500001`）、金额（`1584.00`）、手机号（`13700001001`）、日期（`2026-09-15`）
 *   —— 它们都不带 `id` 关键词，一个都匹配不上；
 * - 英文单词内部的 `id`（`valid`、`provide` 里的 `id` 前面不是词边界，匹配不上）。
 *
 * 判据是**词边界 + 关键词**，不是「像数字就删」——那种写法一定会把金额和手机号也删掉。
 */
object AiAnswerSanitizer {

    /**
     * `user_id 122` / `shipper_id:5` / `ID=9` / `订单 ID：12` / `user_id 为 122`。
     *
     * 拆解：词边界 → 可选的前缀词 → `_?id` → 可选连接符（`:` `=` `：` `＝` `为` `是`）→ 数字。
     */
    private val ID_PHRASE = Regex(
        "(?i)\\b(?:" +
            "user|shipper|driver|product|order_product|order|customer|entry|" +
            "arrears_unit|settled_doc|doc|party|operator" +
            ")?_?id\\s*(?:[:=：＝]|为|是)?\\s*\\d+",
    )

    /** `货主#122` / `司机 #12` → 只留称呼（编号是数据库内部的东西）。 */
    private val HASH_ID = Regex("(货主|司机|客户|用户|临时货主)\\s*#\\s*\\d+")

    /** 编号被掏走后留下的空括号：「（user_id 122）」→「（）」→ 整块删掉。 */
    private val EMPTY_BRACKET = Regex("[（(]\\s*[)）]")

    /** 掏空后留下的连续空格与「悬挂标点」。 */
    private val DOUBLE_SPACE = Regex("[ \\t]{2,}")
    private val DANGLING_PUNCT = Regex("[ \\t]+([，。；、,.;])")

    /** 行尾多余空格（掏空后常见），但**保留换行结构**。 */
    private val TRAILING_SPACE = Regex("[ \\t]+\\n")

    /**
     * 控制字符（C0 与 C1，**保留 `\t` `\n` `\r`**）。
     *
     * ### 为什么净化器要管它（v3.45，模拟器上实测撞到一次）
     * AI 聊天页在前台时，`uiautomator dump` **连崩两次**，logcat 里是：
     * ```text
     * java.lang.IllegalArgumentException: Illegal character (U+0)
     *   at ...KXmlSerializer.reportInvalidCharacter
     *   at ...AccessibilityNodeInfoDumper.dumpNodeRec
     * ```
     * 也就是界面某个节点的文本里带了一个 **NUL**，整棵无障碍树**序列化不出来**。
     * 对用户的实际后果：读屏（TalkBack 之类）与任何 UI 自动化在这个页面上直接失效，
     * 而肉眼只看得出"有个看不见的字符"（渲染成豆腐块或什么都没有）。
     *
     * ⚠️ 那次的具体节点**没能复现**（force-stop 之后 dump 就正常了、存盘的对话文件里
     * 也搜不到控制字符），所以这一条**不是根因修复，是边界加固**：模型给的文本是
     * 唯一可能把控制字符带进界面的来源（用户输入、后端数据都另有来源），而控制字符
     * 在界面上没有任何合法用途。留在 [clean] 里，和"抹掉编号"是同一道闸。
     */
    private val CONTROL = Regex("[\\u0000-\\u0008\\u000B\\u000C\\u000E-\\u001F\\u007F-\\u009F]")

    /**
     * 只剥控制字符，**不动编号**（[clean] 的第一道）。
     *
     * 给"只要求能安全显示、不该改写内容"的地方用：工具痕迹那两行
     * （`🔧 正在查：…（{…}）` / `✓ … → …`）是给用户看工具用过什么的，
     * 里面的参数是**原样裁剪**出来的，不该被编号规则改写，但同样不许带控制字符
     * （它们和答案一样会进聊天页、进无障碍树、还会被存进对话文件）。
     */
    fun stripControl(text: String): String = CONTROL.replace(text, "")

    /**
     * 净化一段文本。空串原样返回（调用方不必自己判空）。
     * 幂等：对已净化的文本再跑一次结果不变。
     */
    fun clean(text: String): String {
        if (text.isBlank()) return text
        var out = stripControl(text)
        out = ID_PHRASE.replace(out, "")
        out = HASH_ID.replace(out) { it.groupValues[1] }
        out = EMPTY_BRACKET.replace(out, "")
        out = TRAILING_SPACE.replace(out, "\n")
        out = DOUBLE_SPACE.replace(out, " ")
        out = DANGLING_PUNCT.replace(out, "$1")
        return out
    }
}
