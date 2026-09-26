"""反向验证：把「批发商那本账**同一笔钱不许被记两遍**」逐条弄坏，看判据**真的会红**。

## 为什么这块必须反向验证

这一域坏掉的方式**全都不报错**，而且有两种判据**互相替代不了**：

| 坏法 | 谁抓得住 | 为什么 |
| --- | --- | --- |
| 恢复时不算上限 | **单测**（行为） | 一个人点几下就能造出来（核销→撤销→再核销→恢复） |
| 算「还可核销」时不加锁读 | **单测**（机制：statement 上有没有 `FOR UPDATE`） | 本机 SQLite 会把 `FOR UPDATE` 丢掉，"看最终 SQL"永远看不出来 |
| 写完不再算一次 / 恢复放行后不再复查 | **只有红线**（源码形状） | 这两道只在**真并发**窗口里才生效，串行测试永远走不到 |
| 撤销/恢复改回"读到没有 → 再写" | **单测**（机制：那次改标记是不是一条 Core UPDATE） | 顺序执行时两种写法都会拒第二次，**行为分不出来** |
| 核销顺手写 `cash_flows` / 翻 `paid` | **红线**（这一域存在的全部理由） | 写进去两边都不报错，只有公司账被污染 |
| 库级不变式 / 并发探针 / 文档指针被删 | **红线** | 判据本身没了，下一轮就没人知道要查什么 |

用法：python _tools/qa/_reverse_verify_shipper_settle_ceiling.py    # 全部报红 → 退出码 0
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# ⛔ 2026-09-26 修：本脚本**不 import `_airepo`**（别人靠它顺手把 stdout 设成 UTF-8），自己又没设 ——
#    于是在 GBK 控制台/管道下打第一个 ✅ 就 `UnicodeEncodeError` 崩掉（实测：EXIT=1，4 秒）。
for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_shipper_settle_ceiling.py"

API = ROOT / "backend/app/api/v1/shipper_ledger.py"
SVC = ROOT / "backend/app/services/shipper_settle.py"
TEST = ROOT / "backend/tests/test_shipper_settle_ceiling.py"
OLD_TEST = ROOT / "backend/tests/test_shipper_settlement.py"
INVARIANTS = ROOT / "_tools/fuzz/_fuzz_invariants.py"
PROBE = ROOT / "_tools/perf/_concurrency_probe.py"
LOCATOR = ROOT / "docs/PROJECT_MAP/08_CODE_LOCATOR.md"
FINDINGS = ROOT / "_archive/audit/FINDINGS.md"

#: (说明, 文件, 原文, 换成, 期望红掉的**那条判据**（写在失败信息里）, 判据是 check 还是 pytest)
CASES: list[tuple[str, Path, str, str, str, str]] = [
    # ---------------------------------------------------------------- 行为（单测判）
    (
        "① 恢复时不再重算上限（**整条防线都摘掉** —— 预检与放行后的复查都在 `if order is not None:` "
        "里，把 order 置空就等于回到本轮修之前的样子）",
        API,
        "    order = db.get(Order, s.order_id)\n"
        "    if order is not None:\n"
        "        order = _locked_order(db, order)\n",
        "    order = None\n"
        "    if order is not None:\n"
        "        order = _locked_order(db, order)\n",
        "test_恢复一笔位置已被占用的核销必须被拒",
        "pytest",
    ),
    (
        "② 算「还可核销」的那条查询不加锁（并发下两个请求读到同一份旧快照）",
        SVC,
        "    if lock:\n        stmt = stmt.with_for_update()\n",
        "    if lock:\n        pass\n",
        "test_算还可核销这一步必须能加锁读",
        "pytest",
    ),
    (
        "③ 超收判据把「相等」也算成超（正常收齐会被拒 —— 反向的误伤）",
        SVC,
        "        if got > recv:",
        "        if got >= recv:",
        "test_还有余量时恢复照旧可以",
        "pytest",
    ),
    (
        "④ 撤销改回「读到没有 → 再写」（连点两下会写两条审计日志）",
        API,
        "    changed = db.execute(\n"
        "        update(ShipperSettlement)\n"
        "        .where(\n"
        "            ShipperSettlement.id == settlement_id,\n"
        "            ShipperSettlement.shipper_id == current.id,\n"
        "            ShipperSettlement.is_deleted.is_(False),\n"
        "        )\n"
        "        .values(is_deleted=True, deleted_at=now)\n"
        "    ).rowcount\n"
        "    if changed != 1:\n"
        "        db.rollback()\n"
        '        raise HTTPException(status_code=400, detail="这笔核销已经撤掉了，不用再撤")\n'
        "    db.refresh(s)\n",
        "    if s.is_deleted:\n"
        '        raise HTTPException(status_code=400, detail="这笔核销已经撤掉了，不用再撤")\n'
        "    s.is_deleted = True\n"
        "    s.deleted_at = now\n",
        "test_撤销与恢复连点两下只算一次（撤销那半）",
        "pytest",
    ),
    (
        "⑤ 恢复改回「读到没有 → 再写」",
        API,
        "    changed = db.execute(\n"
        "        update(ShipperSettlement)\n"
        "        .where(\n"
        "            ShipperSettlement.id == settlement_id,\n"
        "            ShipperSettlement.shipper_id == current.id,\n"
        "            ShipperSettlement.is_deleted.is_(True),\n"
        "        )\n"
        "        .values(is_deleted=False, deleted_at=None)\n"
        "    ).rowcount\n"
        "    if changed != 1:\n"
        "        db.rollback()\n"
        '        raise HTTPException(status_code=400, detail="这笔核销没有被撤销，不需要恢复")\n',
        "    s.is_deleted = False\n"
        "    s.deleted_at = None\n",
        "test_撤销与恢复连点两下只算一次（恢复那半）",
        "pytest",
    ),
    # ---------------------------------------------------------------- 形状（红线判）
    (
        "⑥ 核销不再先锁订单行（同一张单的并发核销不再排队）",
        API,
        "    order = _locked_order(db, _own_order(db, current, body.order_id))\n",
        "    order = _own_order(db, current, body.order_id)\n",
        "核销**先锁订单行**再算钱",
        "check",
    ),
    (
        "⑦ 核销时那次读「已核销多少」不加锁（只锁了行、读的还是快照）",
        API,
        "    pairs = lines_of_order(db, order, lock=True)\n",
        "    pairs = lines_of_order(db, order)\n",
        "核销时那次「已核销多少」读的是**加锁**的那一档",
        "check",
    ),
    (
        "⑧ 核销写完不再算一次（防线②没了 —— 只在真并发下才暴露）",
        API,
        "    db.flush()\n"
        "    breaches = over_settled_lines(db, order, lock=True)\n"
        "    if breaches:\n"
        "        db.rollback()\n"
        "        raise HTTPException(status_code=400, detail=_breach_detail(breaches[0]))\n",
        "    db.flush()\n",
        "写完 `flush` 之后**再算一次**",
        "check",
    ),
    (
        "⑨ 恢复放行之后不再复查（两个恢复请求会各放一笔进来）",
        API,
        "        breaches = over_settled_lines(db, order, lock=True)\n"
        "        if breaches:\n"
        "            db.rollback()\n"
        "            raise HTTPException(status_code=400, detail=_restore_breach_detail(breaches[0]))\n",
        "        # 防线②已被去掉\n",
        "恢复放行之后**还要再看一眼**",
        "check",
    ),
    (
        "⑩ 恢复被拒时只说「恢复失败」（用户不知道要先去撤后面那笔）",
        API,
        '        " —— 先撤掉撤销之后又记的那一笔，再恢复"\n',
        '        " —— 恢复失败"\n',
        "恢复被拒时给的是「先撤掉后面又记的那一笔」这种能照着做的话",
        "check",
    ),
    (
        "⑪ 核销顺手写一笔现金流水（公司账上凭空多一笔已收）",
        API,
        "    db.add(s)\n    db.flush()\n",
        "    db.add(s)\n    from app.models import CashFlow  # noqa: E402\n"
        "    db.add(CashFlow(order_id=order.id, amount=total))\n    db.flush()\n",
        "核销**仍然不写**现金流水",
        "check",
    ),
    (
        "⑫ 核销顺手把订单翻成已收（那是派单员向他收钱的标记）",
        API,
        "    # 钱动了必须留痕（与人工操作同形）",
        "    order.paid = True\n    # 钱动了必须留痕（与人工操作同形）",
        "核销**仍然不写** `orders.paid`",
        "check",
    ),
    (
        "⑬ 三个写端点里少一道「只有批发商」的门",
        API,
        "    _require_member(current)\n    order = _locked_order(db, _own_order(db, current, body.order_id))\n",
        "    order = _locked_order(db, _own_order(db, current, body.order_id))\n",
        "三个写端点仍然各自过 `_require_member`",
        "check",
    ),
    (
        "⑭ 角色门从「只有货主」放开成「登录就行」",
        API,
        "    current: ShipperOnly,\n    response: Response,",
        "    current: User,\n    response: Response,",
        "三个写端点仍然只给货主",
        "check",
    ),
    (
        "⑮ 服务层的超额判据不再带「超出多少 / 想记多少」（话术就说不清了）",
        SVC,
        "                    op=op, receivable=recv, settled=got, over=q2(got - recv), wanted=want\n",
        "                    op=op, receivable=recv, settled=got, over=q2(got - recv), wanted=q2(ZERO)\n",
        "超额带着**超出多少**",
        "check",
    ),
    (
        "⑯ 恢复路径不再把「即将放回来的那几笔」算进去（extra 空掉）",
        SVC,
        "    add = extra or {}\n",
        "    add = {}\n",
        "恢复路径靠 `extra`",
        "check",
    ),
    # ---------------------------------------------------------------- 判据自己（红线判）
    (
        "⑰ 单测①那条断言被改回「200 或 400 都行」（判据被削弱）",
        TEST,
        "    assert back.status_code == 400, (\n"
        '        "恢复一笔已经被后面那笔占掉位置的核销必须被拒（实际 "\n'
        '        f"{back.status_code}）—— 否则同一笔钱被记两遍：已收 160、应收 80"\n'
        "    )\n",
        "    assert back.status_code in (200, 400)\n",
        "①那条断言恢复**必须 400**",
        "check",
    ),
    (
        "⑱ 机制那条不再看加锁参数（改成只看源码里有没有那几个字）",
        TEST,
        "    locked = [s for s in seen if getattr(s, \"_for_update_arg\", None) is not None]\n",
        "    locked = [s for s in seen]\n",
        "机制那条看的是 statement 的加锁参数",
        "check",
    ),
    (
        "⑲ 撤销/恢复的机制那条不再看真的发出去的 UPDATE",
        TEST,
        "        return [str(s) for s in seen if isinstance(s, Update)]\n",
        "        return [str(s) for s in seen]\n",
        "撤销/恢复的机制那条看的是**真的发出去的 UPDATE**",
        "check",
    ),
    (
        "⑳ 旧的核销测试被改回「恢复 200 成功 = 已收齐」（缺陷被写成设计）",
        OLD_TEST,
        '    assert back.status_code == 400, "同一笔钱不许被记两遍：恢复必须重算上限"\n',
        "    assert back.status_code == 200\n",
        "旧测试里那条「恢复成功」的断言已经改成「必须被拒」",
        "check",
    ),
    (
        "㉑ 库级不变式被删（库这一层就没有判据了）",
        INVARIANTS,
        '    check_ic(rep, "某一行的核销合计超过了它的货值（同一笔钱被记了两遍）",',
        '    check_ic(rep, "（这条判据被删了）",',
        "库级不变式里有这一条",
        "check",
    ),
    (
        "㉒ 并发探针里那一档被摘掉（CASES 清单）",
        PROBE,
        'CASES: list[str] = ["assign", "ack", "complete", "cancel", "receipt", "stock", "settle"]',
        'CASES: list[str] = ["assign", "ack", "complete", "cancel", "receipt", "stock"]',
        "并发探针里有 `settle` 这一档",
        "check",
    ),
    (
        "㉓ 探针不再看库里的 Σ（只看 HTTP 状态码，锁冲突的环境下等于没判）",
        PROBE,
        "            if settle_over:",
        "            if False:",
        "探针的判据是「库内的 Σ 不超上限」",
        "check",
    ),
    (
        "㉔ 探针不再把「两笔同时成功」算成缺陷",
        PROBE,
        '                f"并发核销：这一单被记了 {same_order} 笔（应当只有一笔能收）—— 上限校验没锁住"',
        '                f"并发核销（信息）：这一单被记了 {same_order} 笔"',
        "探针把「两笔同时成功」算成缺陷",
        "check",
    ),
    (
        "㉕ 定位表里那一条被删（改这一块的人找不到判据）",
        LOCATOR,
        "判据 `_tools/qa/_check_shipper_settle_ceiling.py` + 反向验证 `_reverse_verify_shipper_settle_ceiling.py`",
        "（判据待补）",
        "定位表里指到了本判据",
        "check",
    ),
    # ⚠️ 2026-09-25（CI 第一次真跑）：㉖ 那条注入打的是 `_archive/audit/FINDINGS.md` —— 那是**不进 git** 的本机底稿，
    #    干净检出里根本没有这个文件 → 这条注入在 CI 上永远找不到原文（成了死锚点）。
    #    主体不在仓库里，就做不成红线：**删掉这条注入**；对应判据那边改成"缺底稿时响亮跳过"。
    (
        "㉗ 服务层文件头那段「两道防线」的说明被删（下一个人不知道为什么要锁两次）",
        SVC,
        "两道防线分别在：",
        "（见代码）",
        "服务层文件头写明了「两道防线分别在哪儿」",
        "check",
    ),
]


def run_check() -> int:
    p = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    return p.returncode


def run_pytest() -> tuple[int, str]:
    """这条红线的**行为**那一层：跑本轮新加的那份单测。"""
    p = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_shipper_settle_ceiling.py", "-q",
         "--no-header", "-p", "no:cacheprovider"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT / "backend"),
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    before = {str(c[1]): c[1].read_text(encoding="utf-8") for c in CASES if c[1].exists()}
    if run_check() != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过（先让它变绿）")
        return 1
    code, out = run_pytest()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时单测就没过\n{out[-1500:]}")
        return 1
    print("✅ 前提：源码完好时红线与单测都是绿的")

    fails: list[str] = []
    for label, path, old, new, expect, judge in CASES:
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        if original.count(old) != 1:
            fails.append(f"{label}：替换串出现 {original.count(old)} 次（要唯一），请更新本脚本")
            continue
        try:
            path.write_text(original.replace(old, new), encoding="utf-8", newline="")
            if judge == "pytest":
                _, out = run_pytest()
                caught = bool(re.search(r"\d+ failed", out))
                how = "单测"
            else:
                caught = run_check() != 0
                how = "红线"
        finally:
            path.write_bytes(original_bytes)
        if caught:
            print(f"  [OK]   {label} → 报红（{how}）")
        else:
            print(f"  [MISS] {label} → 没报红（{how}那一层对这条不敏感）")
            fails.append(f"{label}：注入之后 {how} 没红（期望红在「{expect}」）")

    for k, v in before.items():
        if Path(k).read_text(encoding="utf-8") != v:
            fails.append(f"收尾没还原：{k}")
    if run_check() != 0:
        fails.append("还原之后红线仍然红（有文件没被改回来）")

    total = len(CASES) + 1
    print()
    if fails:
        print(f"❌ 反向验证没通过（{len(fails)}/{total} 条）：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {total}/{total} 全部成立：{len(CASES)} 种破坏方式每一种都被对应的那一层抓到，"
          "且源码已还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
