# -*- coding: utf-8 -*-
"""_reverse_verify_return_request_editable.py —— CHG-0130「退货申请可以直接改」的注入式反向验证。

## 这份脚本要证明什么
_tools/qa/_check_return_request_editable.py 的每一条判据都是**扫结构 / 扫次数 / 扫收件人**算出来的。
扫结构的红线有一个共同的病：源码被改坏时它可能**照样全绿**（那条 ok(...) 根本没人喂它，
或者断言写成了永远为真的形状）。所以这里逐条把源码改坏，看那条红线**是不是真的会红**：
红不出来 = 那条判据是空转的 —— 那就等于让用户替我们发现。

## 七条注入都是「静默」的（编译通过、界面照画、既有检查一条都不红）
| 破坏 | 静默后果 |
| --- | --- |
| ① 已在申请里的行从「就地改数量」换成删行重建 | 明细看起来一模一样，但那行是凭证的一部分：审计指向的行断了 |
| ② 状态门从既有的 _check_pending(req, "改") 换成自己写的一句 | 「谁能改、什么时候能改」分叉出第二份真相，话术也跟着走偏 |
| ③ 通知收件人从这张申请的货主换成 actor_id | 用户说的「只会重新发个信息」变成发给自己，两方谁都没收到 |
| ④ 幂等键丢掉 event_id | 同一张申请第二次改动被 idem_key 吞掉：改了，但没人收到通知 |
| ⑤ 在 main.py 那一支里塞长注释（撑破 500 字符解析窗） | 派发表看起来登记了处理器，_check_return_request.py 第 1 跳却解析不到 |
| ⑥ 派单端入口闸换成 if (true) | 已办理 / 已驳回的单也露出「改明细」，用户填完才被后端拒 |
| ⑦ 货主那一支路由指到派单端页面 | 通知点下去落到别人的页面上，用户以为「这单改了」，其实没定位到那张单 |

⛔ 一条都不许「改到编译不过」：编译不过的反验**什么都没证明**（红线不是靠编译器红的）。
③ 那一处真跑起来会是 NameError —— 但注入是**静态**的：判据必须在没人运行它的时候就抓住它，
等它真跑起来才炸，等于让用户替我们发现问题。

## 现场保护（复用 _airepo，不另造一套）
· refuse_if_injecting —— 上一次注入没还原干净时**先拒绝**（不在脏源码上再叠一层）；
· lock_reverse_verify / unlock_reverse_verify —— 同一时刻只允许一份反向验证在动源码；
· take_snapshot / restore_snapshot —— 被杀在半路时的整目录兜底；
· anchor_preflight —— 动手**之前**先确认每个锚点在目标文件里唯一、且期望标签还在判据脚本里；
  预检不过 ⇒ EXIT 2 且**一个字节都不改**（改到一半才发现锚点没了，源码就停在半路上）；
· 每个文件先 read_bytes() 留底，注入后 finally 里 write_bytes(raw) **逐字节**还原，
  再读回比对 + sha256 自证；收尾用 git diff --numstat 证明跑前跑后一致。

⚠️ 跑完 _check_backend_fresh.py 会红（注入再还原会刷新 mtime，内容一字节没变）：那条红是**预期**的，
   修法是重启本机后端让 source_hash 对上；⛔ 刻意不去改 mtime 把那条红按掉。

用法：python _tools/qa/_reverse_verify_return_request_editable.py          # 全部报红 → 退出码 0
      python _tools/qa/_reverse_verify_return_request_editable.py --list   # 只预检锚点并列出注入
"""

from __future__ import annotations

import filecmp
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import (  # noqa: E402
    SNAPSHOT_DIRS,
    lock_reverse_verify,
    refuse_if_injecting,
    repo_root,
    restore_snapshot,
    snapshot_dir,
    take_snapshot,
    unlock_reverse_verify,
)

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_return_request_editable.py"

SVC = ROOT / "backend/app/services/order_return_request.py"
MSG = ROOT / "backend/app/services/message_center.py"
MAIN = ROOT / "backend/app/main.py"
DISP_SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherReturnRequestsScreen.kt"
NR = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/messages/NoticeRouting.kt"

#: 判据脚本（_check_hints.Checker）打失败行的前缀 —— 认这一串才算「这一条被抓到了」。
#: ⚠️ 同族有些脚本认 "[FAIL]"：照抄错前缀会让每一条注入都判成 MISS（看着像判据全空转）。
FAIL_MARK = "  [!!]   "

#: 塞进 main.py 那一支的长注释：只要把「从这个 if 行到下一个 if event.event_type 行」的
#: 窗口撑过 500 字符，_check_return_request.py 第 1 跳解析那一支时就会够不到结尾。
LONG_COMMENT = (
    "        # 这里本来只该有一行调用。注释本身没有错，错的是**它待的位置**："
    "这一支的正文是从这个 if 行数到下一个 if event.event_type 行的，窗口只有 500 字符；"
    "收件人怎么算、before/after 为什么由服务层带过来、幂等键为什么要 event_id，"
    "这些都该写在 push_events 那个函数自己的 docstring 里，而不是写在这里。"
)

#: 注入表：(说明, 目标文件, 被替换的原文, 替换成, 期望被点出来的判据标签片段)
INJECTIONS: list[tuple[str, Path, str, str, str]] = [
    (
        "① 已在申请里的行改成「删了重建」（那行是凭证的一部分）",
        SVC,
        "            ln.quantity = wanted.pop(ln.order_product_id)",
        "            db.delete(ln)",
        "已在申请里的行就地改数量",
    ),
    (
        "② 状态门自己写一句（不再走既有的 _check_pending）",
        SVC,
        "    _check_pending(req, \"改\")",
        "    if req.status != ReturnRequestStatus.PENDING.value:\n"
        "        return AmendResult(before=\"\", after=\"\")  # 静默不报错",
        "状态门走既有的 _check_pending",
    ),
    (
        "③ 通知发给改的人自己（不是这张申请的货主）",
        MSG,
        "            recipient_id=req.shipper_id,\n            category=\"order\",\n            type=\"order.return_request.amended\",",
        "            recipient_id=actor_id,\n            category=\"order\",\n            type=\"order.return_request.amended\",",
        "收件人是这张申请的货主",
    ),
    (
        "④ 幂等键丢掉 event_id（同一张申请第二次改会被吞掉）",
        MSG,
        "    idem = f\"order.return_request.amended:{request_id}:{event_id}\"",
        "    idem = f\"order.return_request.amended:{request_id}\"",
        "幂等键带 event_id",
    ),
    (
        "⑤ main.py 那一支被长注释撑破 500 字符解析窗",
        MAIN,
        "    if event.event_type == \"returns.amended\":\n        await push_events.push_return_request_amended(",
        "    if event.event_type == \"returns.amended\":\n"
        + LONG_COMMENT
        + "\n"
        "        await push_events.push_return_request_amended(",
        "这一支必须短",
    ),
    (
        "⑥ 派单端入口闸恒真（终态的单也露出「改明细」）",
        DISP_SCREEN,
        "        if (canAmendReturnRequest(req)) {",
        "        if (true) {",
        "派单端：入口闸用 canAmendReturnRequest",
    ),
    (
        "⑦ 货主那一支路由指到派单端页面（能编译、页面照画）",
        NR,
        "        roleKey == Role.SHIPPER.key && type == TYPE_AMENDED ->\n"
        "            Routes.shipperReturnRequests(requestId)",
        "        roleKey == Role.SHIPPER.key && type == TYPE_AMENDED ->\n"
        "            Routes.dispatcherReturnRequests(requestId)",
        "两支路由都带 focus",
    ),
]


def anchor_preflight(verbose: bool = True) -> int:
    """动手**之前**先做三件事：目标文件在、锚点在文件里恰好出现一次、期望标签还在判据脚本里。

    ⛔ 不过就 EXIT 2 且**一个字节都不改**：改到一半才发现锚点没了，源码就停在半路上，
    下一个人的检查会拿着半截源码报一堆假红（而他大概会先去改判据）。
    ⚠️ 「期望标签还在判据脚本里」这一条是**对账**：判据改了名字而这里没跟着改，
    反验会退化成「每条注入都 MISS」——那和没有反验一样，却看起来像在跑。
    """
    problems: list[str] = []
    check_src = CHECK.read_text(encoding="utf-8") if CHECK.is_file() else ""
    for label, path, old, _new, expect in INJECTIONS:
        if not path.is_file():
            problems.append(f"{label}：目标文件不存在 {path}")
            continue
        text = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        n = text.count(old)
        if n != 1:
            problems.append(f"{label}：锚点在 {path.name} 里出现 {n} 次（必须恰好 1 次）")
        if expect not in check_src:
            problems.append(f"{label}：期望标签 {expect!r} 已不在判据脚本里（判据改名了？）")
    if problems:
        print("❌ 预检不过（一个字节都没改）：")
        for p in problems:
            print("   - " + p)
        return 2
    if verbose:
        print(f"✅ 预检：{len(INJECTIONS)} 条注入的锚点都唯一、期望标签都还在判据脚本里")
    return 0


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_src(p: Path) -> tuple[str, bool]:
    """返回 (换行风格归一成 \\n 的文本, 原文是不是 CRLF)。"""
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    """按**原文的换行风格**写回（混着写会让 git diff 整文件变红，别人没法 review）。"""
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_check() -> tuple[int, str]:
    env = os.environ.copy()
    # 让子进程知道「源码是**故意**脏的」（见 _airepo.is_rv_child）：不传这一条，
    # 检查会走 refuse_if_injecting 拒绝出结论 —— 注入就永远「抓不到」。
    env["DSH_RV_CHILD"] = "1"
    r = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), env=env,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def git_numstat(files: list[Path]) -> str:
    """这几个文件在 git 眼里的改动统计（跑前跑后必须一模一样）。取不到就返回提示串。"""
    try:
        r = subprocess.run(
            ["git", "diff", "--numstat", "--", *[str(f) for f in files]],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(ROOT), timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return "(git 不可用)"
    return (r.stdout or "").strip()


def snapshot_diffs() -> list[str]:
    """现场与快照不一致的文件（只看 _airepo.SNAPSHOT_DIRS 那几个目录）。"""
    src = snapshot_dir()
    if not src.is_dir():
        return []
    out: list[str] = []
    for rel in SNAPSHOT_DIRS:
        base = src / rel
        if not base.is_dir():
            continue
        for snap in base.rglob("*"):
            if not snap.is_file():
                continue
            live = ROOT / rel / snap.relative_to(base)
            if not live.exists() or not filecmp.cmp(snap, live, shallow=False):
                out.append(str(live.relative_to(ROOT)).replace("\\", "/"))
    return sorted(out)


def main() -> int:
    argv = sys.argv[1:]
    if "--list" in argv:
        code = anchor_preflight()
        for label, path, _old, _new, expect in INJECTIONS:
            print(f"  · {label}  →  {path.name} ／ 期望：{expect}")
        return code

    if refuse_if_injecting("退货申请可改明细反向验证"):
        return 1
    if not CHECK.exists():
        print(f"❌ 找不到 {CHECK}（红线被改名/搬走了？）")
        return 1

    pre = anchor_preflight()
    if pre != 0:
        return pre

    touched = sorted({m[1] for m in INJECTIONS})
    missing = [str(p) for p in touched if not p.exists()]
    if missing:
        print(f"❌ 注入点文件不存在：{missing}")
        return 1
    originals = {p: p.read_bytes() for p in touched}
    before = {p: sha(p) for p in touched}
    stat_before = git_numstat(touched)

    bad = 0
    lock_reverse_verify()
    try:
        n_snap = take_snapshot()
        print(f"✅ 已上锁并拍快照（{n_snap} 个文件）：这期间**不要改源码**（并发的检查会自动拒绝出结论）")

        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条红线就没过\n" + out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print(f"✅ 前提：源码完好时红线是绿的 —— {last.strip()}")

        for label, path, old, new, expect in INJECTIONS:
            raw = path.read_bytes()          # 逐字节的原始现场（finally 里原样写回）
            src, crlf = read_src(path)
            if src.count(old) != 1:
                print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换（判据该更新了）")
                bad += 1
                continue
            write_src(path, src.replace(old, new), crlf)
            try:
                code, out = run_check()
            finally:
                path.write_bytes(raw)        # ★ 逐字节还原（含换行风格）
            # ⚠️ 这里**不能 strip()**：FAIL_MARK 自带前导两格，strip 过就再也 split 不开了。
            fails = [ln for ln in out.splitlines() if FAIL_MARK in ln]
            got = next((ln for ln in fails if expect in ln), None)
            hit = code != 0 and got is not None
            print(f"  [{'OK' if hit else 'MISS'}] 注入：{label}")
            print("         抓它的判据：" + (got.split(FAIL_MARK, 1)[1].strip() if got else "（没有任何判据承认这条注入）"))
            print(f"         本次共红 {len(fails)} 条、退出码 {code}")
            if not hit:
                print(f"         ⚠️ 期望关键字 {expect!r} 没出现在失败清单里")
                for f in fails[:4]:
                    print("            · " + f.strip())
                bad += 1

        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复（现场没还干净）")
        if not ok:
            print(out[-800:])
            bad += 1
    finally:
        unlock_reverse_verify()
        # ---- 现场还原自检（两层：逐字节 + 整目录快照）----
        others = [d for d in snapshot_diffs()
                  if d not in {str(p.relative_to(ROOT)).replace("\\", "/") for p in touched}]
        if others:
            # ⚠️ 有人在跑的过程中改了**别的**文件：绝不能整目录写回（那会把他的改动一起抹掉）。
            #    只删快照 + 把文件列给他。
            shutil.rmtree(snapshot_dir(), ignore_errors=True)
            print("\n⚠️ 快照期间**别的文件**也变了（有人在并发改源码），为了不抹掉别人的改动，"
                  "本次不做整目录还原：")
            for d in others:
                print("     - " + d)
        else:
            fixed = restore_snapshot()
            print(f"\n✅ 整目录快照还原：写回 {len(fixed)} 个文件"
                  "（正常应为 0 —— 逐字节还原已经把现场复原了）")
            for f in fixed:
                print("     · " + f)

    changed = [str(p.relative_to(ROOT)) for p in touched if p.read_bytes() != originals[p]]
    print(f"✅ 逐字节还原自检：{len(touched) - len(changed)}/{len(touched)} 个注入点文件与跑之前**完全一致**")
    for c in changed:
        print("     ❌ 没还回去：" + c)
    if changed:
        bad += 1
    stat_after = git_numstat(touched)
    same = stat_after == stat_before
    print(f"{'✅' if same else '❌'} git 自检：这些文件的 git diff --numstat 跑前跑后一致"
          f"（{'没有多出/少掉任何改动' if same else '有差异，见下'}）")
    if not same:
        print("     跑前：" + repr(stat_before[:400]))
        print("     跑后：" + repr(stat_after[:400]))
        bad += 1

    print()
    if bad:
        print(f"❌ {bad} 条不成立（红线对它们不敏感，或者现场没还干净）")
        return 1
    print(f"✅ 全部 {len(INJECTIONS)} 种注入都被抓到 + 源码已还原"
          "（逐字节 sha256 一致、git numstat 一致）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
