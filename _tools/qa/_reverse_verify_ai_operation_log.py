"""AI 操作流水（CHG-0082）判据的反向验证：逐条注入「看起来没问题」的坏改法，确认判据真的会红。

## 为什么必须有这一份
`_check_ai_operation_log.py` 有 96 项，全部是静态形状判据（读源码、比对字符串）。静态判据最危险
的失效方式不是「写错」，而是**空转**：正则写宽了、扫描窗口挪了、文件改名了 —— 判据照样打印 [OK]，
而它其实什么都没查。唯一能证伪「空转」的办法就是**故意做出它要抓的那种错，看它会不会红**。

## 为什么「跳过」也算失败
每条注入都要求它的原文在该文件里**恰好出现一次**（`count(old) == 1`）：多于一次说明锚点不唯一
（可能改错地方），零次说明源码已经变了、这条注入**根本没生效**。后者若静默放过，就会出现
「判据没红、但也没人改过代码」的假绿 —— 所以两种都记 `[SKIP]` 并计入失败。

## 为什么不用 CREATIONS / DELETIONS
本脚本覆盖的判据全都钉在**显式文件路径**上（没有一处清单是 glob 出来的），挪走文件不会让判据变红，
只会让检查脚本自己读不到文件而崩 —— 崩了就没有 [FAIL] 行，而本脚本的判据恰恰是「期望的检查名出现在
[FAIL] 行里」，所以那种注入证明不了任何事。清单类守卫（`.kt` 计数、关键文件齐不齐）在检查脚本第 9 节，
它们的价值是「目录被搬走时先报错」，不在本脚本的射程内。

用法：
    python _tools/qa/_reverse_verify_ai_operation_log.py
    python _tools/qa/_reverse_verify_ai_operation_log.py --dry   # 只验锚点还在不在，一个字节都不改
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_ai_operation_log.py"

# (说明, 相对路径, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    # ① 挂载顺序：把 AI 流水挂到 RequestId 外面（收尾时读不到 request_id / origin / action）
    (
        "把 AiOperation 挂到 RequestId 外面",
        "backend/app/main.py",
        """    application.add_middleware(AiOperationMiddleware)

    # 请求追踪 id：挂在 AI 流水外面的那个（异常也要能带上 id）+ 回写 X-Request-ID（见 core/request_id.py）
    application.add_middleware(RequestIdMiddleware)""",
        """    # 请求追踪 id：挂在 AI 流水外面的那个（异常也要能带上 id）+ 回写 X-Request-ID（见 core/request_id.py）
    application.add_middleware(RequestIdMiddleware)

    application.add_middleware(AiOperationMiddleware)""",
        "先挂 AiOperation",
    ),
    # ② 审计行与业务共用请求会话：业务回滚会把审计行一起 rollback 掉
    (
        "审计写入复用请求会话",
        "backend/app/core/ai_operation.py",
        "    db = SessionLocal()",
        "    db = SessionLocal  # 省一次调用",
        "用独立的 SessionLocal",
    ),
    # ③ 失败也记成成功 —— 这一页的整条价值就在这一列上
    (
        "ok 恒为真",
        "backend/app/core/ai_operation.py",
        "                ok=int(status_code) < 400,",
        "                ok=True,",
        "ok = status_code < 400",
    ),
    # ④ 路径不按列宽截断：长 query 串会让整行写入失败（而失败是被吞掉的，于是静默丢审计）
    (
        "路径不截断",
        "backend/app/core/ai_operation.py",
        "                path=path[:MAX_PATH_LEN],",
        "                path=path,",
        "路径按列宽截断",
    ),
    # ⑤ 写库异常不再吞掉：审计失败反过来把业务请求打成 500（本末倒置）
    (
        "审计写库异常不再吞掉",
        "backend/app/core/ai_operation.py",
        """        db.rollback()
        logger.warning("AI 操作流水写入失败：%s", exc)""",
        "        raise",
        "写库异常全吞掉",
    ),
    # ⑥ 取消被当成普通异常吞掉：客户端断开时审计行会丢（而断开正是最需要留痕的时候）
    (
        "CancelledError 不再原样抛出",
        "backend/app/core/ai_operation.py",
        """            except asyncio.CancelledError:
                raise""",
        """            except asyncio.CancelledError:
                return""",
        "取消原样抛出",
    ),
    # ⑦ 回到「读上下文变量」的老写法：中间件比 RequestId 靠外，那时上下文还是空的 = 一条都不记
    (
        "改读 get_origin()（中间件层读不到）",
        "backend/app/core/ai_operation.py",
        """    raw = headers.get(ORIGIN_HEADER.lower().encode(), b"").decode("latin-1")
    return normalize_origin(raw) == AI""",
        """    raw = headers.get(ORIGIN_HEADER.lower().encode(), b"").decode("latin-1")
    if get_origin() == AI:
        return True
    return normalize_origin(raw) == AI""",
        "不读 get_origin()",
    ),
    # ⑧ 成功的响应也攒 body：大导出/大列表被整份读进内存（审计把服务拖垮）
    (
        "成功响应也攒 body",
        "backend/app/core/ai_operation.py",
        '            elif message["type"] == "http.response.body" and state["status"] >= 400:',
        '            elif message["type"] == "http.response.body":',
        "只有失败才攒响应体",
    ),
    # ⑨ 不多取一行：最后一页永远说「还有更早的」，翻到底也停不下来
    (
        "不多取一行判截断",
        "backend/app/api/v1/ai_operations.py",
        "        .limit(limit + 1)",
        "        .limit(limit)",
        "多取一行判截断",
    ),
    # ⑩ 正序返回：用户看到的是最老的几十条，最新的 AI 动作反而要翻到最后
    (
        "按 id 正序返回",
        "backend/app/api/v1/ai_operations.py",
        "        .order_by(AiOperationLog.id.desc())",
        "        .order_by(AiOperationLog.id)",
        "按 id 倒序",
    ),
    # ⑪ 只要求「登录」不要求权限：货主也能读到全公司的 AI 动作（这一页是管理端的）
    (
        "端点降级为只要求登录",
        "backend/app/api/v1/ai_operations.py",
        "    _: User = Depends(require_permission(Permission.OPERATION_LOG_READ)),",
        "    _: User = Depends(get_current_user),",
        "权限沿用 OPERATION_LOG_READ",
    ),
    # ⑫ 直接返回 rows：截断信息（X-Truncated / X-Result-Limit）全丢，界面永远说「到底了」
    (
        "截断不走响应头",
        "backend/app/api/v1/ai_operations.py",
        "    return finish_page(rows, limit, response)",
        "    return rows",
        "截断通过响应头说出来",
    ),
    # ⑬ 建表代码挪进 bootstrap：线上多一条没人测过的 DDL 路径（迁移 029 才是唯一入口）
    (
        "把这张表写进 schema_bootstrap",
        "backend/app/core/schema_bootstrap.py",
        "from sqlalchemy import inspect, text",
        """from sqlalchemy import inspect, text

AI_OPERATION_TABLES = ("ai_operation_logs",)""",
        "schema_bootstrap 里没有这张表",
    ),
    # ⑭「只看失败」改成本地过滤：滤掉成功的行之后「还有更早的」这个判断跟着失真
    (
        "「只看失败」改成本地过滤",
        "android/app/src/main/java/com/tapmoay/sorders/data/repo/AppRepository.kt",
        "            ok = if (onlyFailed) false else null,",
        "            ok = null,",
        "「只看失败」走服务端",
    ),
    # ⑮ 翻页不去重：翻页期间来了新行 ⇒ 同一 id 出现两次 ⇒ LazyColumn key 撞车直接崩
    (
        "翻页追加前不去重",
        "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiOperationsViewModel.kt",
        "                rows = rows + page.rows.filter { it.id !in seen }",
        "                rows = rows + page.rows",
        "追加前按 id 去重",
    ),
    # ⑯ 认不出的动作名现编一个中文名 —— 审计页上最坏的一种撒谎（用户据此判断「它没干过那件事」）
    (
        "动作名认不出时现编一个",
        "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiOperationRows.kt",
        '        return if (title == id) id else title + "（" + id + "）"',
        '        return "第 " + id + " 次动作"',
        "动作名认得出",
    ),
    # ⑰ 函数名撞回属性 setter：Kotlin 编译不过（Platform declaration clash）—— 这条守的是「别人后来改名」
    (
        "切换筛选函数改回 setOnlyFailed",
        "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiOperationsViewModel.kt",
        "    fun applyOnlyFailed(value: Boolean) {",
        "    fun setOnlyFailed(value: Boolean) {",
        "不叫 setOnlyFailed",
    ),
    # ⑱ 无条件提示截断：全都取回来之后还说「只有最近 N 条」，用户会以为还有没取到的
    (
        "无条件显示截断提示",
        "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiOperationsScreen.kt",
        "                        if (vm.canLoadMore) {",
        "                        if (true) {",
        "只有后面还有时才提示截断",
    ),
    # ⑲ 入口对所有人渲染：货主/司机会点进一个必然 403 的页面
    (
        "入口不再按角色渲染",
        "android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiSettingsScreen.kt",
        "            if (ai.currentActor?.role == AiRole.DISPATCHER) {",
        "            if (true) {",
        "入口只在派单员",
    ),
    # ⑳ 没有 AI 上下文也硬加 origin 头：**所有**请求都被记成 AI 干的（人工操作全被算到 AI 头上）
    (
        "所有请求都带上 origin 头",
        "android/app/src/main/java/com/tapmoay/sorders/core/ApiClient.kt",
        "        val origin = ClientOrigin.current() ?: return delegate.newCall(request)",
        '        val origin = ClientOrigin.current() ?: "human"',
        "只有 ClientOrigin 说是 AI 时才加头",
    ),
    # ㉑ 预览也包进 asAi：没发生的动作也被后端记成「AI 干过」
    (
        "预览也被标成 AI 写入",
        "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteService.kt",
        '            ClientOrigin.asAi(p.actionId) { handler.commit(p.payload, "ai-" + token) }',
        """            ClientOrigin.asAi(p.actionId) { handler.commit(p.payload, "ai-" + token) }\n            ClientOrigin.asAi(p.actionId) { }""",
        "ClientOrigin.asAi( 只有 1 处",
    ),
]


def read_src(rel: str) -> tuple[str, bool]:
    """读成 LF 文本 + 记住原来是不是 CRLF（写回时要一模一样）。"""
    raw = (ROOT / rel).read_bytes()
    crlf = b"\r\n" in raw
    return raw.decode("utf-8").replace("\r\n", "\n"), crlf


def write_src(rel: str, text: str, crlf: bool) -> bytes:
    out = text.replace("\n", "\r\n") if crlf else text
    data = out.encode("utf-8")
    (ROOT / rel).write_bytes(data)
    return data


def restore_src(rel: str, text: str, crlf: bool, expect: bytes) -> None:
    """写回后**重新读回逐字节比**：还原不干净就必须立刻停，绝不能让后面的注入跑在脏源码上。"""
    write_src(rel, text, crlf)
    back = (ROOT / rel).read_bytes()
    if back != expect:
        print("  [FATAL] 还原后字节不一致：{}".format(rel))
        raise SystemExit(2)


def run_check() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def fails_of(out: str) -> list[str]:
    return [ln.strip() for ln in out.splitlines() if ln.strip().startswith("[FAIL]")]


def verdict(expect: str, proc: subprocess.CompletedProcess[str]) -> tuple[bool, str]:
    fails = fails_of((proc.stdout or "") + (proc.stderr or ""))
    hit = next((ln for ln in fails if expect in ln), None)
    if proc.returncode != 0 and hit is not None:
        return True, hit
    if proc.returncode == 0:
        return False, "判据**没红**（退出码 0）—— 这条检查是空转的"
    return False, "红了但不是这条（实际红 {} 条）：{}".format(len(fails), " / ".join(fails[:4]))


def dry_run() -> int:
    """只验锚点：每条注入的原文是否在该文件里恰好出现一次（一个字节都不改）。"""
    print("\n== 锚点体检（--dry，不改任何文件） ==")
    bad = 0
    for label, rel, old, _new, expect in MUTATIONS:
        text, _crlf = read_src(rel)
        n = text.count(old)
        if n == 1:
            print("  [OK]   {:<28} {}".format(label, rel))
        else:
            bad += 1
            print("  [BAD]  {:<28} {} —— 原文出现 {} 次（期望 1 次）；期望判据：{}".format(label, rel, n, expect))
    print("\n" + "=" * 60)
    if bad:
        print("❌ {} 条锚点对不上，先修锚点再跑正式注入。".format(bad))
        return 1
    print("✅ {} 条锚点全部唯一命中。".format(len(MUTATIONS)))
    return 0


def main() -> int:
    if "--dry" in sys.argv:
        return dry_run()

    total = len(MUTATIONS) + 1  # +1 = 末尾「还原后判据重新全绿」
    bad = 0

    print("\n== 0. 前提：源码完好时判据必须全绿 ==")
    proc = run_check()
    if proc.returncode != 0:
        print("  [FATAL] 源码当前状态判据就是红的，先修好再来做反向验证：")
        for ln in fails_of((proc.stdout or "") + (proc.stderr or ""))[:10]:
            print("    " + ln)
        return 2
    last = [ln for ln in (proc.stdout or "").splitlines() if "全部" in ln and "通过" in ln]
    print("  [OK]   " + (last[-1].strip() if last else "判据退出码 0"))

    print("\n== 1. 逐条注入（每条跑完立刻还原） ==")
    for i, (label, rel, old, new, expect) in enumerate(MUTATIONS, start=1):
        text, crlf = read_src(rel)
        n = text.count(old)
        if n != 1:
            bad += 1
            print("  [SKIP] {}/{} {} —— 原文出现 {} 次（期望 1 次）：{}".format(i, len(MUTATIONS), label, n, rel))
            continue
        before = (ROOT / rel).read_bytes()
        try:
            write_src(rel, text.replace(old, new, 1), crlf)
            got = run_check()
            ok, detail = verdict(expect, got)
        finally:
            restore_src(rel, text, crlf, before)
        if ok:
            print("  [OK]   {}/{} {} —— {}".format(i, len(MUTATIONS), label, detail))
        else:
            bad += 1
            print("  [MISS] {}/{} {} —— {}".format(i, len(MUTATIONS), label, detail))

    print("\n== 2. 收尾：全部还原之后判据必须重新全绿 ==")
    proc = run_check()
    if proc.returncode == 0:
        last = [ln for ln in (proc.stdout or "").splitlines() if "全部" in ln and "通过" in ln]
        print("  [OK]   " + (last[-1].strip() if last else "判据退出码 0（还原干净）"))
    else:
        bad += 1
        print("  [MISS] 还原之后判据仍然是红的 —— 有文件没还原干净：")
        for ln in fails_of((proc.stdout or "") + (proc.stderr or ""))[:10]:
            print("    " + ln)

    print("\n" + "=" * 60)
    if bad:
        print("❌ {}/{} 条不成立（注入没让判据变红，或锚点对不上）。".format(bad, total))
        return 1
    print("✅ {}/{} 全部成立：{} 条注入各自让对应判据变红，还原后判据重新全绿。".format(total, total, len(MUTATIONS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

