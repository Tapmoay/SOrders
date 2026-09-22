"""反向验证 `_check_role_parity.py`：**往能力表里注入越权/缺口，它必须变红**。

### 为什么每条红线都要有这一份
本仓库栽过 6 次"永远红的检查没人管"，也栽过"检查写瞎了还显示绿"。前者的反面是这一份要证明的：
一条检查**只有在能被弄红的时候**才有价值。所以下面每种**破坏方式**都要真的注入一次、
跑一次检查、看到非零退出，再按 sha256 逐字节还原。

### 注入点必须选在"旧检查不看的地方"
（本项目的经验：注入在检查本来就覆盖不到的地方，等于什么都没证明。）
所以这里选的是**这一轮新增的那几处判据**：`memberOnly` 标记、`SHIPPER_ACTIONS` 白名单、
`_show_role_caps` 的常量解析。

用法：python _tools/ai/_reverse_verify_role_parity.py
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
ROOT = Path(__file__).resolve().parents[2]
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
WRITE = AI / "AiWrite.kt"
SHIPPER_LEDGER = AI / "AiWriteShipperLedger.kt"
CAPS = ROOT / "_tools/ai/_show_role_caps.py"
SERVICE = AI / "AiWriteService.kt"
TPL_HANDLERS = AI / "AiWriteOrderTemplateHandlers.kt"

#: (名字, 文件, 原串, 换成什么) —— 每个都是**一种真实的破坏方式**。
CASES: list[tuple[str, Path, str, str]] = [
    (
        "批发商专属标记被抹掉（普通货主会看见核销）",
        SHIPPER_LEDGER,
        "            memberOnly = true,\n        ),\n        AiWriteAction(\n            id = AiWrites.MY_LEDGER_REVOKE,",
        "            memberOnly = false,\n        ),\n        AiWriteAction(\n            id = AiWrites.MY_LEDGER_REVOKE,",
    ),
    (
        "撤回用的恢复动作从白名单里删掉（软删撤回路径被自己的门挡掉）",
        WRITE,
        "        ADDRESS_RESTORE,\n",
        "",
    ),
    (
        "白名单里塞进一个派单动作（越权）",
        WRITE,
        "        ORDERS_SOFT_DELETE,\n",
        "        ORDERS_SOFT_DELETE,\n        ORDERS_ASSIGN,\n",
    ),
    (
        "派单员不再被 memberOnly 挡住（能动货主自己那本账）",
        WRITE,
        # ⚠️ 2026-09-21 更新锚点：派单员那一支后来长成
        #    `ALL.filter { (it.roles == null || role in it.roles) && !it.memberOnly }`
        #    （多了一层按动作 `roles` 的白名单）。注入原意不变：**把 memberOnly 那道挡板摘掉**。
        "(it.roles == null || role in it.roles) && !it.memberOnly",
        "(it.roles == null || role in it.roles)",
    ),
    (
        "货主白名单解析被注释干扰（`_show_role_caps` 的剥注释判据）",
        CAPS,
        "    src = strip_comments((AI / \"AiWrite.kt\").read_text(encoding=\"utf-8\"))",
        "    src = (AI / \"AiWrite.kt\").read_text(encoding=\"utf-8\")",
    ),
    # ---- 参数式处理器那条路（2026-09-22 补的第三种写法）----
    # ⚠️ 这两条的注入点必须**旧判据不看的那个位置**，否则证明不了新路真的在起作用：
    #    动作声明块（`id = ORDER_TEMPLATE_CREATE,`）一个字都不动，只动**注册点**与**类体**。
    (
        "参数式处理器的注册点被改名（动作与实现失联 → 检查必须报缺口，而不是静默看不见）",
        SERVICE,
        # ⚠️ 必须**两条一起改**：注册点与类体是"读同一个类"的，只改 CREATE 那一条时
        #    UPDATE 那条注册仍然带着整个类体（体里两个 `ds.` 调用都在），于是
        #    `POST /order-templates` 会被 UPDATE 那个动作顺手覆盖 —— 注入就抓不住了（实测）。
        "            OrderTemplateWriteHandler(AiWrites.ORDER_TEMPLATE_CREATE, ds, store),\n"
        "            OrderTemplateWriteHandler(AiWrites.ORDER_TEMPLATE_UPDATE, ds, store),",
        "            RenamedWriteHandler(AiWrites.ORDER_TEMPLATE_CREATE, ds, store),\n"
        "            RenamedWriteHandler(AiWrites.ORDER_TEMPLATE_UPDATE, ds, store),",
    ),
    (
        "参数式处理器的类体里把 ds 调用摘掉（动作挂着、实现没了）",
        TPL_HANDLERS,
        "ds.createOrderTemplate(payload)",
        "// ds.createOrderTemplate(payload)",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def write_exact(p: Path, text: str, crlf: bool) -> None:
    """按**原来那种换行**写回。

    ⚠️ 两个坑叠在一起，第一版就踩了：
    1. `read_text()` 走**通用换行**（`\\r\\n` → `\\n`），所以内存里的文本已经没有 `\\r` 了；
    2. `write_text()` 默认按 `os.linesep` 翻译（Windows 上把 `\\n` 变 `\\r\\n`）。
    于是"读完再写回"会把 **LF 文件变成 CRLF**、把 CRLF 文件（如果显式 `newline=""`）变成 LF，
    两种都会让 sha256 对不上 —— 而"反向验证跑完把源码改坏了"比不做验证更糟。
    所以：先看原文件是哪种换行，再**显式**按它写。
    """
    with p.open("w", encoding="utf-8", newline="\r\n" if crlf else "\n") as fh:
        fh.write(text)


def run_check() -> int:
    return subprocess.run(
        [sys.executable, str(ROOT / "_tools/ai/_check_role_parity.py"), "--check"],
        cwd=ROOT, capture_output=True,
    ).returncode


def run_caps() -> int:
    return subprocess.run(
        [sys.executable, str(CAPS), "--check"], cwd=ROOT, capture_output=True,
    ).returncode


def main() -> int:
    base = run_check()
    if base != 0:
        print("❌ 基线就是红的：先把 `_check_role_parity.py --check` 弄绿再来做反向验证")
        return 1
    print(f"基线：_check_role_parity --check 通过（{len(CASES)} 种破坏方式待注入）\n")

    fails: list[str] = []
    for name, path, old, new in CASES:
        before = sha(path)
        crlf = b"\r\n" in path.read_bytes()
        src = path.read_text(encoding="utf-8")
        if old not in src:
            print(f"  [SKIP] {name} —— 注入点没命中（源码改过？这条要跟着改）")
            fails.append(f"{name}：注入点没命中")
            continue
        write_exact(path, src.replace(old, new, 1), crlf)
        try:
            code = run_caps() if path == CAPS else run_check()
        finally:
            write_exact(path, src, crlf)
        restored = sha(path) == before
        ok = code != 0 and restored
        print(f"  [{'OK' if ok else 'FAIL'}] {name} —— 退出码 {code}，还原{'一致' if restored else '**不一致**'}")
        if not ok:
            fails.append(f"{name}：退出码 {code}，还原{'一致' if restored else '不一致'}")

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)}/{len(CASES)} 种破坏方式没被抓住：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)}/{len(CASES)} 种破坏方式都被抓住，且文件逐字节还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
