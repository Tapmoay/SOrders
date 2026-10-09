package com.tapmoay.sorders.ai

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * 导出文件卡上那两颗按钮"什么时候点得动"、以及卡片上那几行字写什么
 * （台账 L-61 / CHG-0095；文字压缩见台账 L-62 / CHG-0097）。
 *
 * ## 为什么要钉
 * 用户 2026-10-09 点名的形态是「左边一个文件图标的框 + 中间文件信息 + 右边**两颗**图标按钮
 * （下载、分享），而且这 2 个按钮不要靠的太近」（ref `m00002`）。两颗按钮一起摆出来之后，
 * 每一档状态都可能做错，而**做错了不报错、不崩、界面上也一眼看不出**：
 * - 文件已经在手机上了，「下载」还是亮的 ⇒ 用户以为还有第二份文件没拿，连点几次；
 * - 正在生成的时候「下载」还亮着 ⇒ 连点开出两个账本任务（CHG-0078 就是为这个把按钮收起来的）；
 * - 手机分享不了（Android 10 以下、没有 `content://`），「分享」却亮着 ⇒ 点下去没反应；
 * - 信息区那行写成「营业纵览 · · 」这种空段 ⇒ 卡片上出现一行谁也看不懂的点。
 * 所以逐档钉死，包括"来源认不出来时宁可什么都不写"。
 *
 * 后来（同一天，ref `m01176`）用户又点名「太长了……不要那么长的信息啊，只表示一保存做个简单的」
 * —— 于是"卡片上那句话"整行收敛进 [exportStatusLine]，连"存好之后不许再出现 `/storage`"
 * 这件事也变成可以直接断言的，而不是靠正则去 Composable 里找字符串。
 */
class AiExportCardTest {

    // ---------------- 两颗按钮：可用性 ----------------

    @Test
    fun `还没点过_下载能点_分享是灰的`() {
        val a = exportCardActions(busy = false, saved = false, shareable = false)
        assertEquals(true, a.downloadEnabled)
        // 手里还没有文件，分享没东西可分享 —— 灰着，不是藏起来
        assertEquals(false, a.shareEnabled)
        assertEquals(false, a.downloaded)
    }

    @Test
    fun `正在生成_两颗都点不动`() {
        // 连点 = 连开任务（账本任务吃用户每天 20 次配额）
        val a = exportCardActions(busy = true, saved = false, shareable = false)
        assertEquals(false, a.downloadEnabled)
        assertEquals(false, a.shareEnabled)
        assertEquals(false, a.downloaded)
    }

    @Test
    fun `存好了_下载退成灰的_分享亮起来`() {
        val a = exportCardActions(busy = false, saved = true, shareable = true)
        assertEquals(false, a.downloadEnabled)
        assertEquals(true, a.shareEnabled)
        assertEquals(true, a.downloaded)
    }

    @Test
    fun `安卓10以下存好了_分享仍然是灰的`() {
        // Q 以下落盘拿不到 content://，系统层面就发不出去（口径 m01865）：
        // 界面在下面用一句话说明原因与文件位置，而不是画一颗点了没反应的按钮
        val a = exportCardActions(busy = false, saved = true, shareable = false)
        assertEquals(false, a.downloadEnabled)
        assertEquals(false, a.shareEnabled)
        // 但"文件已经在手机上"这件事仍然成立，信息区要照写
        assertEquals(true, a.downloaded)
    }

    @Test
    fun `已经存好了又忙起来_两颗都不许亮`() {
        // 重下的时候 VM 只翻 busy、**不清** file（downloadExport 里那句 copy(busy = true)），
        // 所以这一档在真机上真的会出现："文件在手机上，但正在被新的一版覆盖"。
        // 这时候「分享」必须是灰的 —— 否则用户分享出去的可能是上一个版本的那份表。
        val a = exportCardActions(busy = true, saved = true, shareable = true)
        assertEquals(false, a.downloadEnabled)
        assertEquals(false, a.shareEnabled)
        // 但"文件已经在手机上"这件事仍然成立，信息区要照写
        assertEquals(true, a.downloaded)
    }

    // ---------------- 取件中的那句话 ----------------

    @Test
    fun `不忙的时候_没有进度那句话`() {
        assertEquals("", exportProgressNote(busy = false, saved = false, progress = "正在排队…"))
        assertEquals("", exportProgressNote(busy = false, saved = true, progress = ""))
    }

    @Test
    fun `忙的时候_账本报的那句原样用`() {
        // 账本的进度是后端排队的实话（「已等 8 秒」这种），⛔ 不许被界面换成一句笼统的话
        assertEquals("正在排队生成…（已等 8 秒）", exportProgressNote(busy = true, saved = false, progress = "正在排队生成…（已等 8 秒）"))
    }

    @Test
    fun `忙但没话说_要有一句顶上去`() {
        // 报表是现算现返、不报进度 ⇒ 卡片上不许只剩一个转圈、一行字都没有
        assertEquals("正在生成…", exportProgressNote(busy = true, saved = false, progress = ""))
        assertEquals("正在生成…", exportProgressNote(busy = true, saved = false, progress = "   "))
        // 重下已经存过的那个文件：说法要分得出来
        assertEquals("正在准备文件…", exportProgressNote(busy = true, saved = true, progress = ""))
    }

    // ---------------- 「下载」那颗上写什么 ----------------

    @Test
    fun `下载那颗的字_错了就写再试一次`() {
        assertEquals("下载", exportDownloadLabel(hasError = false))
        assertEquals("再试一次", exportDownloadLabel(hasError = true))
    }

    // ---------------- 信息区第二行：这张表叫什么 ----------------

    @Test
    fun `报表_表名加统计区间`() {
        // 表名与报表页签、后端 sheet 标题三处逐字相同（AiTools.EXPORT_TITLES）
        val r = StoredExportRecipe(
            source = StoredExportRecipe.SOURCE_REPORT,
            kind = "turnover",
            dateFrom = "2026-09-01",
            dateTo = "2026-09-30",
        )
        assertEquals("营业纵览 · 2026-09-01 ~ 2026-09-30", exportCardSubtitle(r))
    }

    @Test
    fun `报表_只有一天就不写一个假的区间`() {
        val r = StoredExportRecipe(
            source = StoredExportRecipe.SOURCE_REPORT,
            kind = "finance",
            dateFrom = "2026-09-30",
            dateTo = "2026-09-30",
        )
        assertEquals("资金收支 · 2026-09-30", exportCardSubtitle(r))
    }

    @Test
    fun `报表_一个字段都没有_也不许写出一串空点`() {
        // 认不出形状时宁可少一行：⛔ 不是 " · "、也不是一个凭空编的表名
        val r = StoredExportRecipe(source = StoredExportRecipe.SOURCE_REPORT, kind = "", dateFrom = "", dateTo = "")
        assertEquals("", exportCardSubtitle(r))
    }

    @Test
    fun `报表_认不出的表名_原样回而不是猜一个`() {
        val r = StoredExportRecipe(
            source = StoredExportRecipe.SOURCE_REPORT,
            kind = "unknown_sheet",
            dateFrom = "",
            dateTo = "",
        )
        assertEquals("unknown_sheet", exportCardSubtitle(r))
    }

    @Test
    fun `账本_只写货主账本_人名与区间在文件名里`() {
        val r = StoredExportRecipe(
            source = StoredExportRecipe.SOURCE_LEDGER,
            kind = "",
            shipperName = "城东水产",
            fileName = "城东水产-2026-09-01_2026-09-30.xlsx",
        )
        assertEquals("货主账本", exportCardSubtitle(r))
    }

    @Test
    fun `表名只有一处定义_测试与界面读的是同一份`() {
        // 逐字钉住：这份映射漂了（有人抄第二份），报表页签与文件名就跟着对不上
        assertEquals("营业纵览", AiTools.exportTitle("turnover"))
        assertEquals("异常与审计", AiTools.exportTitle("audit"))
    }

    // ---------------- 状态行：卡片对用户说的那句话（CHG-0097，台账 L-62） ----------------

    @Test
    fun `存好之后_卡片上只写已保存_不写路径`() {
        // 用户 2026-10-09 第二次点名（ref m01176）：「不要那么长的信息啊，只表示一保存做个简单的」
        val line = exportStatusLine(error = "", saved = true, busy = false, progress = "")
        assertEquals("已保存", line)
        // ⛔ 这一条是本档的要害：路径一旦漏回来，卡片立刻又被撑成一大块
        // （JUnit 的参数顺序是 message 在前；写反了编译期就会红 —— 别改成 assertFalse(条件, 话)）
        assertFalse("存好之后不该把文件路径摊在卡片上，实际：" + line, line.contains("/storage"))
        assertFalse("存好之后不该把文件路径摊在卡片上，实际：" + line, line.contains("Download"))
    }

    @Test
    fun `失败过_后端那句原话要原样说出来_不能被已保存盖掉`() {
        // 顺序即判据：错误 > 已存好 > 正在忙。「说一句实话」永远压过"看起来一切正常"
        val line = exportStatusLine(error = "账本服务没应答", saved = true, busy = false, progress = "")
        assertEquals("⚠ 账本服务没应答", line)
    }

    @Test
    fun `正在忙_走的是进度那句话`() {
        assertEquals(
            "正在生成…",
            exportStatusLine(error = "", saved = false, busy = true, progress = ""),
        )
        assertEquals(
            "已等 8 秒",
            exportStatusLine(error = "", saved = false, busy = true, progress = "已等 8 秒"),
        )
    }

    @Test
    fun `什么都没发生_状态行是空的_不留一条空行`() {
        assertEquals("", exportStatusLine(error = "", saved = false, busy = false, progress = ""))
    }

    @Test
    fun `存好之后的字数_就是三个字`() {
        // 「已保存」三个字是上限：这类"卡片上的一句话"每多一个字都要有理由
        assertEquals("「已保存」就三个字，实际：" + exportSavedLabel(), 3, exportSavedLabel().length)
    }
}
