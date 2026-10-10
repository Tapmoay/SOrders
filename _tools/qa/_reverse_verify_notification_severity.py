#!/usr/bin/env python3
"""FEAT-0019 消息分级判据的**反向验证**：每条注入都必须让判据变红。

判据（_check_notification_severity.py）证明的是"代码现在是对的"；这个脚本证明的是
"**代码错的时候它真的会红**"。少了这一步，一条恒真的检查也能自称全绿 —— 本仓库在这上面
栽过（_ai_doc_check.py 红了 12 轮没人知道 / 清单为空 ⇒ 检查恒真）。

七条注入对应七条用户口径（每条都在判据里有一条对应的失败文案）：

| 注入 | 它模拟的真实错误 | 判据必须红在哪一句 |
| --- | --- | --- |
| ① 撤销类改成 info | 「处处置 info」= 分级白做 | order.revoked 的档位必须是 SEVERITY_WARN |
| ② 端点里写死 severity="warn" | 判定散成两处（改一边另一边不动） | 不许在任何调用点写死严重度 |
| ③ warn 与 danger 常量对调 | 红橙互换（最坏的一种错：反着告诉用户） | 模型里的 SEVERITY_WARN 必须是 "warn" |
| ④ 出参里删掉 severity | App 拿不到档，整件事白做 | NotificationOut 里没有 severity 字段 |
| ⑤ 列默认值改成 danger | 所有没登记的消息都变红 | 模型里的 SEVERITY_INFO 必须是 "info" |
| ⑥ 重点词不过滤 | 标了正文里没有的词 / 整行上色 | emphasis_for 少了那道闸 |
| ⑦ 表里漏掉一个 type | 新消息永远是"普通消息" | 那些 type 没在 SEVERITY_BY_TYPE 里登记 |

口径（与 _reverse_verify_account_device_binding.py 同）：
  1. **先跑未注入的基线** —— 判据自己就红的话直接退出（否则后面每条都会红，什么都没验证到）；
  2. 每条注入后判据必须**非零退出**，而且输出里要出现**这一条预期的那句**文案
     （"红了，但红的是别的东西"不算验证到）；
  3. 每条注入后立刻还原；末尾用 sha256 逐文件比对，**逐字节一致**才算通过；
  4. ⚠️ 锚点必须与文件的实际行尾一致（有的文件是 CRLF）—— 本脚本按文件自动适配行尾。

用法：
    python _tools/qa/_reverse_verify_notification_severity.py
"""
import hashlib
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_notification_severity.py"

MODEL = ROOT / "backend/app/models/notification.py"
SCHEMA = ROOT / "backend/app/schemas/notification.py"
CENTER = ROOT / "backend/app/services/message_center.py"
API = ROOT / "backend/app/api/v1/notifications.py"

FILES = [MODEL, SCHEMA, CENTER, API]
ORIG: dict[Path, bytes] = {p: p.read_bytes() for p in FILES}

#: (文件, 名字, 旧串, 新串, 期望在判据输出里出现的那句失败文案)
MUTATIONS: list[tuple[Path, str, str, str, str]] = [
    (CENTER, "① 撤销类改成 info（处处置 info）",
     '"order.revoked": SEVERITY_WARN,',
     '"order.revoked": SEVERITY_INFO,',
     "order.revoked 的档位必须是 SEVERITY_WARN"),
    (API, "② 端点里写死 severity（判定散成两处）",
     '            type="price_change",\n',
     '            type="price_change",\n            severity="warn",\n',
     "不许在任何调用点写死严重度"),
    (MODEL, "③ warn 与 danger 常量对调",
     'SEVERITY_WARN = "warn"\nSEVERITY_DANGER = "danger"',
     'SEVERITY_WARN = "danger"\nSEVERITY_DANGER = "warn"',
     '模型里的 SEVERITY_WARN 必须是 "warn"'),
    (SCHEMA, "④ 出参里删掉 severity",
     '    severity: str = Field(\n        default=SEVERITY_INFO,\n'
     '        description="严重度：" + " | ".join(SEVERITY_VALUES),\n    )\n',
     "",
     "NotificationOut 里没有 severity 字段"),
    (MODEL, "⑤ 列默认值改成 danger",
     'SEVERITY_INFO = "info"',
     'SEVERITY_INFO = "danger"',
     '模型里的 SEVERITY_INFO 必须是 "info"'),
    (CENTER, "⑥ 重点词不过滤（整行上色）",
     "        if word not in text:\n            continue\n",
     "        if word in text:\n            continue\n",
     "emphasis_for 少了『正文/标题里找不到就一个都不标』那道闸"),
    (CENTER, "⑦ 表里漏掉一个 type（order.deleted）",
     '    "order.deleted": SEVERITY_WARN,\n',
     "",
     "这些 type 在代码里出现、却没在 SEVERITY_BY_TYPE 里登记"),
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
    """把注入写进文件；返回错误文案（None 表示成功）。"""
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
    print("== FEAT-0019 消息分级判据的反向验证通过：七条注入全部被抓，树已逐字节还原。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        restore()
