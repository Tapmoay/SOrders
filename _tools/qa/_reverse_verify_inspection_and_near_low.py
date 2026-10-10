#!/usr/bin/env python3
"""FEAT-0022 判据的**反向验证**：每条注入都必须让判据变红。

判据（_check_inspection_and_near_low.py）证明的是"现在这两件事是对的"；这个脚本证明的是
"**它们错的时候判据真的会红**"。少了这一步，一条恒真的检查也能自称全绿 ——
本仓库在这上面栽过（清单为空 ⇒ 检查恒真；GBK 下 UnicodeEncodeError 崩掉，看着像跑过了）。

八条注入对应八条用户口径 / 八种真实错法（每条在判据里都有一句专门的失败文案）：

| 注入 | 它模拟的真实错误 | 判据必须红在哪一句 |
| --- | --- | --- |
| ① 百分比常量改成 0 | 「偏低」那一档永远不发（用户要的宽松档没了） | NEAR_LOW_RATIO_PERCENT = 20 必须只有一处 |
| ② 低于阈值改成 `<=` | 「恰好等于阈值」被算成 danger（用户口径反了） | 库存不足的边界不是 stock < alert |
| ③ 两格都空也凑一个起点 | 系统自己编一个到期日来提醒用户 | next_due_date 没有「两格都空 ⇒ None」那一支 |
| ④ 逾期降成 warn | 年检过期上路要罚款扣车，界面却按"待办"显示 | vehicle.inspection_overdue 的档位不是 danger |
| ⑤ 幂等键去掉到期日 | 同一次年检每天刷一条（或第二年的提醒永远发不出来） | 年检的幂等键不是「类型:车辆:到期日」 |
| ⑥ NOT_PRODUCED 里留着已做的类 | 下一单以为它还缺字段，再"补"一遍 | NOT_PRODUCED 里还有 |
| ⑦ 算不出到期日照发 | 没录日期的车被硬报一条年检提醒 | 没有「算不出到期日 ⇒ 一个字都不发」那一支 |
| ⑧ 提前提醒天数改成 0 | 只剩到期当天才提醒（年检要预约，来不及） | inspection_due 的提前提醒天数不是 30 天 |

口径（与 _reverse_verify_message_producers.py / _reverse_verify_notification_severity.py 同）：
  1. **先跑未注入的基线** —— 判据自己就红的话直接退出（否则后面每条都会红，什么都没验证到）；
  2. 每条注入后判据必须**非零退出**，而且输出里要出现**这一条预期的那句**文案
     （"红了，但红的是别的东西"不算验证到）；
  3. 每条注入后立刻还原；末尾用 sha256 逐文件比对，**逐字节一致**才算通过；
  4. ⚠️ 锚点必须与文件的实际行尾一致（有的文件是 CRLF）—— 本脚本按文件自动适配行尾。

用法：
    python _tools/qa/_reverse_verify_inspection_and_near_low.py
"""
import hashlib
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_inspection_and_near_low.py"

PRODUCERS = ROOT / "backend/app/services/message_producers.py"
CENTER = ROOT / "backend/app/services/message_center.py"
SERVICE = ROOT / "backend/app/services/inspection_due.py"

FILES = [PRODUCERS, CENTER, SERVICE]
ORIG: dict[Path, bytes] = {p: p.read_bytes() for p in FILES}

#: (文件, 名字, 旧串, 新串, 期望在判据输出里出现的那句失败文案)
MUTATIONS: list[tuple[Path, str, str, str, str]] = [
    (PRODUCERS, "① 百分比常量改成 0（偏低那一档永远不发）",
     "NEAR_LOW_RATIO_PERCENT = 20\n",
     "NEAR_LOW_RATIO_PERCENT = 0\n",
     "NEAR_LOW_RATIO_PERCENT = 20 必须**只有一处**"),
    (PRODUCERS, "② 低于阈值改成 <=（恰好等于阈值被算成 danger）",
     '    if stock < alert:\n        return "stock.low"\n',
     '    if stock <= alert:\n        return "stock.low"\n',
     "库存不足的边界不是 stock < alert"),
    (SERVICE, "③ 两格都空也凑一个起点（系统自己编到期日）",
     "    if base is None:\n        return None\n",
     "    base = base or date(2000, 1, 1)\n",
     "next_due_date 没有「两格都空 ⇒ None」那一支"),
    (CENTER, "④ 逾期降成 warn（罚款扣车显示成待办）",
     '"vehicle.inspection_overdue": SEVERITY_DANGER,',
     '"vehicle.inspection_overdue": SEVERITY_WARN,',
     "vehicle.inspection_overdue 的档位不是 danger"),
    (PRODUCERS, "⑤ 幂等键去掉到期日（同一次年检每天刷屏）",
     '        idem_key=kind + ":" + str(int(vehicle.id)) + ":" + due.isoformat(),\n',
     '        idem_key=kind + ":" + str(int(vehicle.id)),\n',
     "年检的幂等键不是「类型:车辆:到期日」"),
    (PRODUCERS, "⑥ NOT_PRODUCED 里留着一个已经做了的类",
     "NOT_PRODUCED: dict[str, str] = {}\n",
     'NOT_PRODUCED: dict[str, str] = {\n    "stock.near_low": "「建议水位」字段全库不存在。",\n}\n',
     "NOT_PRODUCED 里还有"),
    (PRODUCERS, "⑦ 算不出到期日也照发（没录日期的车被硬报一条）",
     "    if due is None:\n        return 0\n",
     "    if due is None:\n        due = day\n",
     "notify_inspection 没有「算不出到期日 ⇒ 一个字都不发」那一支"),
    (SERVICE, "⑧ 提前提醒天数改成 0（只剩到期当天才提醒）",
     "INSPECTION_DUE_SOON_DAYS = 30\n",
     "INSPECTION_DUE_SOON_DAYS = 0\n",
     "inspection_due 的提前提醒天数不是 30 天"),
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
    print("== FEAT-0022 判据的反向验证通过：八条注入全部被抓，树已逐字节还原。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        restore()
