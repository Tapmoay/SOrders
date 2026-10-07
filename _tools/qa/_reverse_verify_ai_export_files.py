"""反向验证 CHG-0078（AI 出表格与聊天内下载/分享，台账 L-43）那批修复**真的在检查**。

2026-10-06 用户点名（m01850 ②）：聊完天要能拿到表格。这一块最要命的一条口径是
**工具回合不许生成文件** —— 工具只回一张「配方」（StoredExportRecipe），真正的生成/下载
发生在用户点那行「下载」之后。所以这里的红线几乎全是「形状」而不是「数值」：
坏掉之后接口照样 200、聊天里照样有数，只是文件悄悄换了口径 / 悄悄越权 / 悄悄丢失。

| 坏法（本次真的注进去过） | 谁抓得住 | 为什么 |
| --- | --- | --- |
| 工具枚举（AiTools.ALL）里摘掉 export_ledger | 判据① | 常量登记与工具集对不上，AI 那里连这个工具都没有 |
| 默认开启集（AiKeyStore）漏登记 | 判据① | 新装的 App 里它默认不开，用户看不见 |
| 货主那一档也拿到 export_ledger | 判据① | 货主能导**别人的**账 ⇒ 越权（L-43 只给派单员） |
| 标题从「导出账本」改掉 | 判据① | 设置页 / 工具名与真源逐字对不上 |
| schema 不再要求 date_to | 判据① | 只给开始日期也能提交，模型无从知道要闭区间 |
| 账本任务号不写回配方（onJobId 那次回调） | 判据⑤ | 超时/重启之后再点会当新任务重新排队 |
| 轮询次数 60 → 6 | 判据⑤ | 40 秒的任务等不到，直接报「还没生成好」 |
| 下载按钮不再挡重复点击 | 判据⑥ | 点两下排队两个任务（那天配额只有 3 次） |
| 拿到字节不再投递（不落盘） | 判据⑥ | 转圈转到天荒地老，文件永远不出现 |
| 行内那张「凭据」卡片不再渲染 | 判据⑥ | 聊天里只剩一句话，用户找不到下载按钮 |
| 分享不再是「分享到」选择器 | 判据⑥ | 点名微信的话没装就崩（见 ExportUtil 的注释） |
| 月报不闭到月底（下个月 1 号的单漏出去） | 判据④ | 后端区间改了，报表与聊天里的文件名口径对不上 |
| 后端不再占槽位（acquire_export_slot） | 判据⑦ | 同一账号并发导两本账 ⇒ 469MB 峰值 × 2 |
| 「今天已经导出 N 次」那道闸摘掉 | 判据⑦ | 每日配额形同虚设 |

⚠️ 判据必须是绿的才开跑（前提），否则每一条都会「抓到」，这份报告就成了自欺。
⚠️ 快照 / 还原按**字节**做（仓库里有 CRLF 文件），跑完逐字节核对。
⚠️ 跑的时候拿着注入锁（_airepo.lock_reverse_verify）：并发的检查会拒绝出结论。
⚠️ 只动源码，不跑 gradle、不碰 android/app/build —— 跑完不必重启后端。

用法：python _tools/qa/_reverse_verify_ai_export_files.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools/ai"))

from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

JUDGE = ROOT / "_tools/qa/_check_ai_export_files.py"

AI = "android/app/src/main/java/com/tapmoay/sorders/ai/"
UI = "android/app/src/main/java/com/tapmoay/sorders/ui/ai/"
UTIL = "android/app/src/main/java/com/tapmoay/sorders/util/"
BACK = "backend/app/"

#: (说明, 相对路径, 原文, 换成, 期望红掉的那条)
CASES: list[tuple[str, str, str, str, str]] = [
    (
        "工具枚举里摘掉账本（AI 那里连这个工具都没有）",
        AI + "AiTools.kt",
        "            EXPORT_LEDGER,\n",
        "            EXPORT_SHEET,\n",
        "判据①（工具枚举与常量登记逐字对齐）",
    ),
    (
        "默认开启集漏登记（新装的 App 看不见这个工具）",
        AI + "AiKeyStore.kt",
        "            AiTools.EXPORT_LEDGER,\n",
        "            AiTools.REMEMBER,\n",
        "判据①（默认开启集里 export_ledger 恰好一处）",
    ),
    (
        "货主那一档也拿到账本（越权：能导别人的账）",
        AI + "AiTools.kt",
        "            AiRole.SHIPPER to setOf(READ_DATA, REMEMBER, PREVIEW_WRITE),\n",
        "            AiRole.SHIPPER to setOf(READ_DATA, REMEMBER, PREVIEW_WRITE, EXPORT_LEDGER),\n",
        "判据①（货主那一行逐字，其后不许再出现 EXPORT_*）",
    ),
    (
        "标题改名（设置页与真源对不上）",
        AI + "AiTools.kt",
        '            EXPORT_LEDGER to "导出账本",\n',
        '            EXPORT_LEDGER to "导出账",\n',
        "判据①（标题那一条逐字）",
    ),
    (
        "schema 不再要求结束日期（只给开始日期也能提交）",
        AI + "AiTools.kt",
        '                        add(JsonPrimitive("date_to"))\n',
        '                        add(JsonPrimitive("date_from")),\n',
        "判据①（shipper / date_from / date_to 三个都必填）",
    ),
    (
        "账本任务号不写回配方（超时后再点会重新排队）",
        AI + "AiExportService.kt",
        "            onJobId(job.id)\n",
        "            # 注入：任务号不写回配方\n",
        "判据⑤（onJobId(job.id) 那一处回调）",
    ),
    (
        "轮询次数 60 → 6（40 秒的任务等不到）",
        AI + "AiExportService.kt",
        "        const val POLL_TIMES = 60\n",
        "        const val POLL_TIMES = 6\n",
        "判据⑤（2 秒 × 60 次 = 两分钟）",
    ),
    (
        "下载按钮不再挡重复点击（点两下排两个任务）",
        UI + "AiChatViewModel.kt",
        "        if (msg.exportState.busy) return\n",
        "        if (false) return  # 注入：不挡重复点击\n",
        "判据⑥（downloadExport 体内那道 busy 闸）",
    ),
    (
        "拿到字节不再投递（不落盘，文件永远不出现）",
        UI + "AiChatViewModel.kt",
        "                val file = ai.exports.deliver(\n",
        "                val file: ExportedFile? = null  # 注入：不投递\n",
        "判据⑥（ai.exports.deliver( 那一处）",
    ),
    (
        "行内那张凭据卡片不再渲染（用户找不到下载按钮）",
        UI + "AiChatScreen.kt",
        "            val recipe = m.exportRecipe\n",
        "            val recipe: StoredExportRecipe? = null  # 注入：行内不再显示\n",
        "判据⑥（val recipe = m.exportRecipe 恰好一处）",
    ),
    (
        "分享不再是「分享到」选择器",
        UTIL + "ExportUtil.kt",
        '        val chooser = Intent.createChooser(send, "分享到").apply {\n',
        '        val chooser = Intent.createChooser(send, "分享").apply {\n',
        "判据⑥（ACTION_SEND ＋ createChooser ＋「分享到」）",
    ),
    (
        "月报不闭到月底（下个月 1 号的单漏出去）",
        BACK + "services/reports/_common.py",
        "        return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)\n",
        "        return first, d  # 注入：月报不闭到月底\n",
        "判据④（后端区间规则逐字）",
    ),
    (
        "后端不再占槽位（同一账号能并发导两本账）",
        BACK + "api/v1/ledger.py",
        "    slot = acquire_export_slot(current.id)\n",
        "    slot = current.id  # 注入：不占槽位\n",
        "判据⑦（acquire_export_slot 那道闸）",
    ),
    (
        "「今天已经导出 N 次」那道闸摘掉（配额形同虚设）",
        BACK + "api/v1/ledger.py",
        "    if recent_jobs >= EXPORT_DAILY_QUOTA:\n",
        "    if False:\n",
        "判据⑦（每日配额那三道闸）",
    ),
    (
        "产物被清理后不清那个作废的任务号（那颗按钮永远只会重复同一句报错）",
        UI + "AiChatViewModel.kt",
        "                if (api.code == 404) {\n",
        "                if (false) {  // 注入：不清作废的任务号\n",
        "判据⑥（404 清任务号那一处）",
    ),
    (
        "临时货主的拒绝理由被简化掉（用户不知道是账号问题）",
        AI + "AiTools.kt",
        "是临时货主，账本里没有他的正式账号，导不了。",
        "是临时货主，导不了。  # 注入：理由简化",
        "判据②（临时货主如实拒绝那一句）",
    ),
]


def run_judge() -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(JUDGE)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def _first_fail(out: str) -> str:
    """判据报的第一条红（拿去当证据：证明它是**因为这条坏法**红的）。"""
    m = re.search(r"\[FAIL\][^\n]*", out)
    return m.group(0).strip() if m else ""


def run_all() -> int:
    files = sorted({case[1] for case in CASES})
    before = {rel: (ROOT / rel).read_bytes() for rel in files}

    print("== 前提：判据必须是绿的（否则「抓到」不算数）==")
    code, out = run_judge()
    if code != 0:
        print("❌ 前提不成立：_check_ai_export_files.py 本来就是红的，先修好它")
        print(out[-2000:])
        return 1
    print("✅ 判据绿；下面把 " + str(len(CASES)) + " 条坏法逐条注进去，看它红不红")

    fails: list[str] = []
    for i, (label, rel, old, new, expect) in enumerate(CASES, start=1):
        path = ROOT / rel
        text = _read(path)
        hits = text.count(old)
        if hits != 1:
            fails.append(f"{i:02d} {label}：替换串出现 {hits} 次（要唯一）")
            print(f"[MISS] {i:02d} {label} —— 替换串出现 {hits} 次（要唯一）")
            continue
        caught = False
        detail = ""
        try:
            path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="")
            code, out = run_judge()
            caught = code != 0
            if caught:
                detail = _first_fail(out)
        finally:
            path.write_bytes(before[rel])
        if caught:
            print(f"[OK]   {i:02d} {label} —— 抓住了（{expect}）")
            if detail:
                print(f"        {detail}")
        else:
            fails.append(f"{i:02d} {label}：注进去之后判据还是绿的（{expect}）")
            print(f"[MISS] {i:02d} {label} —— 注进去之后判据还是绿的")

    print("== 收尾：每个被碰过的文件都要逐字节还原，且还原之后判据仍然是绿的 ==")
    for rel in files:
        if (ROOT / rel).read_bytes() != before[rel]:
            fails.append("收尾没还原：" + rel)
            (ROOT / rel).write_bytes(before[rel])
            print("❌ 收尾没还原（已强制还原）：" + rel)
    code, out = run_judge()
    if code != 0:
        fails.append("还原之后判据是红的（说明还原不干净）")
        print("❌ 还原之后判据是红的")
        print(_first_fail(out))

    total = len(CASES) + 1
    if fails:
        print("")
        print(f"❌ {total - len(fails)}/{total} 成立：")
        for f in fails:
            print("   - " + f)
        return 1
    print("")
    print(f"✅ {total}/{total} 全部成立（{len(CASES)} 条坏法各自被抓住 ＋ 收尾还原与判据复绿）")
    return 0


def main() -> int:
    lock_reverse_verify()
    try:
        return run_all()
    finally:
        unlock_reverse_verify()


if __name__ == "__main__":
    sys.exit(main())
