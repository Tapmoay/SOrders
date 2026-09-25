#!/usr/bin/env python3
"""反向验证 _tools/fuzz/_fuzz_invariants.py（库内不变式审计）**真的会报缺陷**。

## 为什么这条最要紧
报告 §19 的原话是：**Domain + Database invariants 才是真正的业务真相**。而这份审计是本项目唯一
「直接查库、把两张表摆一起看对不对得上」的工具。它自己的文件头就记着一类事故：5 条订单状态判据
写成小写，**永远扫描 0 行、永远报绿** —— 改对大小写之后立刻命中真缺陷（订单 581 账本重复行）。
换句话说：**它不报缺陷有两种可能** —— ① 真的没问题；② 那条判据死了。工具自己分不开这两者，
所以由**外部**来分：把故意写坏的行塞进一个**副本库**，逐条断言「这一条必须报出来」。

## 做法（全程不碰本机开发库）
1. 把本机开发库**复制**到临时目录（工具自己也是 mode=ro 打开的，这里连原库都不碰）；
2. 每条破坏**重新复制一份**，只改坏一处（对应一条不变式）；
3. 用 SORDERS_DB=副本 跑审计，断言输出里出现**那一条**判据的缺陷行（✗ 标题）。

没有开发库时**响亮跳过**（与 _fuzz_invariants 同一口径：本机没有就说明，不假装通过）。

用法：python _tools/fuzz/_reverse_verify_invariants.py
      python _tools/fuzz/_reverse_verify_invariants.py --list
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
INV = ROOT / "_tools" / "fuzz" / "_fuzz_invariants.py"
DEV_DB = Path(os.environ.get("SORDERS_DB", str(ROOT / "backend" / "sorders.db")))

#: (说明, 把副本库改坏的 SQL, 期望出现在缺陷行里的标题片段)
CASES: list[tuple[str, str, str]] = [
    (
        "① 已送达的单没了送达时间",
        "update orders set delivered_at = null where id = (select id from orders"
        " where status = 'DELIVERED' and delivered_at is not null limit 1)",
        "已送达但没有送达时间",
    ),
    (
        "② 派单中/已接单的单没有司机",
        "update orders set driver_id = null where id = (select id from orders"
        " where status in ('DISPATCHED', 'ACCEPTED') and driver_id is not null limit 1)",
        "派单中/已接单但没有司机",
    ),
    (
        "③ 商品行金额出现负数（修复线之后建的）",
        "update order_products set line_total = -1 where id = (select id from order_products"
        " where created_at >= '2026-09-18' limit 1)",
        "order_products.line_total",
    ),
    (
        "④ 账本流水指向一张不存在的订单（孤儿行）",
        "update ledgers set order_id = 99999999 where id = (select id from ledgers limit 1)",
        "ledgers.order_id",
    ),
]


def _run_audit(db: Path) -> tuple[int, str]:
    env = {**os.environ, "SORDERS_DB": str(db)}
    p = subprocess.run([sys.executable, str(INV), "--check"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, cwd=str(ROOT), timeout=900)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _corrupt(db: Path, sql: str) -> int:
    c = sqlite3.connect(db)
    try:
        cur = c.execute(sql)
        n = int(cur.rowcount or 0)
        c.commit()
        return n
    finally:
        c.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, _sql, want) in enumerate(CASES, 1):
            print(str(i) + ". " + name + "   ← 期望缺陷行里出现「" + want + "」")
        return 0

    if not DEV_DB.is_file():
        print("⚠️  跳过：找不到本机开发库 " + str(DEV_DB) + "（不进 git；这条要连库，CI 上不跑）")
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="sorders_inv_rv_"))
    bad = 0
    lock_reverse_verify()
    try:
        copy = tmp / "clean.db"
        shutil.copy(DEV_DB, copy)
        code, out = _run_audit(copy)
        if code != 0:
            print("❌ 前提不成立：**干净的副本库**上审计就报了缺陷（说明本机库本来就不干净）：")
            print(out[-1500:])
            return 1
        tail = [ln.strip() for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：干净副本上审计是绿的 —— " + tail)

        for i, (name, sql, want) in enumerate(CASES, 1):
            db = tmp / ("case" + str(i) + ".db")
            shutil.copy(DEV_DB, db)
            n = _corrupt(db, sql)
            if n == 0:
                print("  [SKIP] " + name + " —— 本机库里没有可改坏的行（副本上 0 行受影响）")
                bad += 1
                continue
            code, out = _run_audit(db)
            hit = code != 0 and ("✗ " + want) in out
            if hit:
                print("  [OK] " + name + " → 审计报出缺陷并命中「" + want + "」")
            else:
                bad += 1
                why = "审计居然还是绿的" if code == 0 else "退出了，但失败清单里没有「" + want + "」"
                print("  [MISS] " + name + " → " + why)
                for ln in [x.strip() for x in out.splitlines()
                           if x.strip().startswith(("✗", "?"))][:5]:
                    print("       审计实际报的：" + ln)

        # ---- 第 ⑤ 条：把**工具自己**的状态字面量写错 → 自检必须当场拦下 ----
        # 这就是 2026-09-25 抓到 ACKED 的那条路（OrderStatus 里没有这个值）：
        # 状态字面量写错时判据不会报错，只会**永远为假**，所以必须由自检来拦。
        orig = INV.read_bytes()
        text = orig.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        # ⚠️ 锚点要选**真的会被执行**的那一处：`'CANCELLED'` 在文件里第一次出现是**文档字符串里**
        #    的举例（第 125 行那句「原来写错了」），替换到那儿等于没改 —— 第一次就是这么 MISS 的。
        injured = text.replace("upper(status)='CANCELLED'", "upper(status)='CANCELED'", 1)
        if injured == text:
            print("  [SKIP] ⑤ 状态字面量写错 → 自检必须拦下 —— 锚点没命中（本文件变了？）")
            bad += 1
        else:
            try:
                INV.write_bytes(injured.encode("utf-8"))
                code, out = _run_audit(tmp / "clean.db")
            finally:
                INV.write_bytes(orig)
            hit = code != 0 and "自检失败" in out
            if hit:
                print("  [OK] ⑤ 状态字面量写错 → 自检当场拦下（不是一个永远为假的分支）")
            else:
                bad += 1
                print("  [MISS] ⑤ 状态字面量写错 → " + ("自检居然放过了" if code == 0 else "没有自检失败"))
    finally:
        unlock_reverse_verify()
        shutil.rmtree(tmp, ignore_errors=True)

    total = len(CASES) + 2
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立")
        return 1
    print(f"✅ {total}/{total} 全部成立：库内不变式审计**真的会报缺陷**（不是永远绿）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())