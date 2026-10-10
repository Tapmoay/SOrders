#!/usr/bin/env python3
"""FEAT-0021 消息生产者判据的**反向验证**：每条注入都必须让判据变红。

判据（_check_message_producers.py）证明的是"生产者现在是对的"；这个脚本证明的是
"**生产者错的时候它真的会红**"。少了这一步，一条恒真的检查也能自称全绿 ——
本仓库在这上面栽过（清单为空 ⇒ 检查恒真；GBK 下 UnicodeEncodeError 崩掉，看着像跑过了）。

八条注入对应八条用户口径 / 八种真实错法（每条在判据里都有一句专门的失败文案）：

| 注入 | 它模拟的真实错误 | 判据必须红在哪一句 |
| --- | --- | --- |
| ① 不再走公共的幂等键 | 去重被拿掉 → 每日扫描变成每天刷屏 | create_message 没有走公共的 idem_key_for |
| ② 档位对调（stock.low danger→warn） | 危险程度反着告诉用户（最坏的一种错） | stock.low 的档位不是 SEVERITY_DANGER |
| ③ emphasis 换成整句 | 整句上色（用户明确否掉："全是重点就是没有重点"） | 重点词片段太长 |
| ④ 丢掉深链键 product_id | 卡片点进去跳不到那个商品（§五：缺键就别给） | 库存不足 的消息没有给深链键 product_id |
| ⑤ 每日兜底扫描不挂 lifespan | 钩子被绕过的漏发再也没人补 | 兜底扫描没有挂进 lifespan |
| ⑥ 摘掉新设备登录钩子 | 账号被盗登录，本人永远收不到提醒 | 新设备登录 的钩子不在写路径上 |
| ⑦ 钩子挪到 db.commit() 之后 | 业务回滚了消息还在（对不上账） | 发票开具 的钩子不在写路径上 |
| ⑧ 收件人绕过 active_dispatchers | 收件人判定散成第二处（含离职/停用账号） | 收件人没有走 active_dispatchers |

口径（与 _reverse_verify_notification_severity.py / _reverse_verify_account_device_binding.py 同）：
  1. **先跑未注入的基线** —— 判据自己就红的话直接退出（否则后面每条都会红，什么都没验证到）；
  2. 每条注入后判据必须**非零退出**，而且输出里要出现**这一条预期的那句**文案
     （"红了，但红的是别的东西"不算验证到）；
  3. 每条注入后立刻还原；末尾用 sha256 逐文件比对，**逐字节一致**才算通过；
  4. ⚠️ 锚点必须与文件的实际行尾一致（有的文件是 CRLF）—— 本脚本按文件自动适配行尾。

用法：
    python _tools/qa/_reverse_verify_message_producers.py
"""
import hashlib
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_message_producers.py"

PRODUCERS = ROOT / "backend/app/services/message_producers.py"
CENTER = ROOT / "backend/app/services/message_center.py"
DEVICE = ROOT / "backend/app/services/device_service.py"
TAX = ROOT / "backend/app/services/tax_service.py"
MAIN = ROOT / "backend/app/main.py"

FILES = [PRODUCERS, CENTER, DEVICE, TAX, MAIN]
ORIG: dict[Path, bytes] = {p: p.read_bytes() for p in FILES}

#: (文件, 名字, 旧串, 新串, 期望在判据输出里出现的那句失败文案)
MUTATIONS: list[tuple[Path, str, str, str, str]] = [
    (CENTER, "① 去掉去重（不再走公共的幂等键）",
     "    key = idem_key_for(idem_key, recipient_id)\n",
     "    key = None\n",
     "create_message 没有走公共的 idem_key_for"),
    (CENTER, "② 档位对调（stock.low 从 danger 降成 warn）",
     '"stock.low": SEVERITY_DANGER,',
     '"stock.low": SEVERITY_WARN,',
     "stock.low 的档位不是 SEVERITY_DANGER"),
    (PRODUCERS, "③ emphasis 换成整句（整句上色）",
     'emphasis=(str(int(stock)) + " " + unit, str(alert) + " " + unit),',
     'emphasis=("商品库存已经低于报警阈值，请及时补货并通知仓库管理员",),',
     "重点词片段太长"),
    (PRODUCERS, "④ 丢掉深链键 product_id",
     '        "product_id": int(product.id),\n',
     "",
     "库存不足 的消息没有给深链键 product_id"),
    (MAIN, "⑤ 删掉每日兜底扫描（不挂 lifespan）",
     "    scan_task = asyncio.create_task(_message_scan_loop())\n",
     "",
     "兜底扫描没有挂进 lifespan"),
    (DEVICE, "⑥ 摘掉新设备登录钩子",
     "    message_producers.notify_new_device_login(db, user=user, binding=mine, source=source)\n",
     "",
     "新设备登录 的钩子不在写路径上"),
    (TAX, "⑦ 钩子挪到 db.commit() 之后（业务回滚消息还在）",
     "    message_producers.notify_invoice_issued(db, invoice=invoice, operator_id=operator_id)\n"
     "    db.commit()\n",
     "    db.commit()\n"
     "    message_producers.notify_invoice_issued(db, invoice=invoice, operator_id=operator_id)\n",
     "发票开具 的钩子不在写路径上"),
    (PRODUCERS, "⑧ 收件人改成全体用户（绕过 active_dispatchers）",
     "    for d in active_dispatchers(db):\n",
     "    for d in db.scalars(select(User)).all():\n",
     "收件人没有走 active_dispatchers"),
]


def restore() -> None:
    for p, raw in ORIG.items():
        p.write_bytes(raw)


def newline_of(p: Path) -> str:
    return "\r\n" if b"\r\n" in ORIG[p] else "\n"


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def apply_mutation(path: Path, old: str, new: str) -> str:
    """把注入写进文件；返回错误文案（空串表示成功）。"""
    nl = newline_of(path)
    raw = path.read_bytes().decode("utf-8")
    o = old.replace("\n", nl)
    n = new.replace("\n", nl)
    count = raw.count(o)
    if count != 1:
        return "锚点出现 %d 次（必须正好 1 次；行尾=%r）" % (count, nl)
    path.write_bytes(raw.replace(o, n).encode("utf-8"))
    return ""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    baseline_files = {p: sha(p) for p in FILES}
    code, out = run_check()
    print("基线（未注入）：exit=%d" % code)
    if code != 0:
        print(out[-2000:])
        print("⛔ 判据在**未注入**的树上就是红的 —— 先把它修绿，否则下面每条注入都会红，什么都验证不到。")
        return 1

    red = 0
    for path, name, old, new, expect in MUTATIONS:
        try:
            err = apply_mutation(path, old, new)
            if err:
                print("  ✗ %s：%s" % (name, err))
                continue
            code, out = run_check()
            if code == 0:
                print("  ✗ %s：注入之后判据**没有变红**（这条判据是恒真的）" % name)
                continue
            if expect not in out:
                print("  ✗ %s：判据红了，但红的是别的东西（期望文案没出现：%s）" % (name, expect))
                continue
            print("  ✓ %s → 判据变红：%s" % (name, expect))
            red += 1
        finally:
            restore()

    same = all(sha(p) == baseline_files[p] for p in FILES)
    print("")
    print("注入 %d 条，变红 %d 条；还原后逐字节一致：%s" % (len(MUTATIONS), red, "是" if same else "否"))
    if red != len(MUTATIONS) or not same:
        print("⛔ 反向验证没过：要么有注入没被抓住，要么还原不干净。")
        return 1
    print("== FEAT-0021 消息生产者判据的反向验证通过：八条注入全部被抓，树已逐字节还原。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        restore()
