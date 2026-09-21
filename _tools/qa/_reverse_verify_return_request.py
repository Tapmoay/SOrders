"""反向验证 `_check_return_request.py` 的那批判据**真的会红**（不是一张写着漂亮话的清单）。

## 为什么这块必须配反向验证
退货申请这一整块坏掉的方式全都**不报错、不崩、界面上看不出来**：

| 破坏 | 静默后果 |
|---|---|
| `submit()` 里多一行 `return_order(...)` | "申请即退货"复活：货主按一下改了自己的应收与公司库存，派单员根本不知道 |
| `fulfill()` 自己写红冲、不调唯一入口 | 钱有两处实现，两边迟早不一致，而**谁都不报错** |
| 办理端点多一个 `quantity` 参数 | "申请 5 件、办成 3 件"，两边各说各话（数量锁死当场作废） |
| 货主矩阵里删掉申请权／加上执行权 | 货主申请不了；或者货主能直接改自己的应收（申请制变成装饰） |
| 直连退货里**删掉** `close_by_direct_return(...)` | 申请书停在 pending → 再点「办理」时余量够、校验全过 → 同一批货**被退两遍** |
| 把 `close_by_direct_return(...)` 挪到 `db.commit()` **之后** | 提交那一刻申请还是 pending（并发点「办理」就穿过去了）；关申请自己抛错时货已落库、申请永远关不掉 |
| AI 动作的 `roles` 写反／`forRole` 只过滤一边 | 助手弹一张必然 403 的卡，用户以为退成功了 |
| 审计动作码缺中文名 | 审计页直接印 `ORDER_RETURN_REQUEST_WITHDRAW` 原始码，用户看不懂 |

这些**只有机器判据能拦住**；而"判据本身是不是在看这些地方"只能靠注入法证明。
所以这里逐条注入破坏 → 跑红线 → 要求它**恰好点出那一条**。

## 注入点选在哪儿（为什么要避开旧检查看的地方）
`_tools/qa/_check_order_return.py`（退货**本身**的红线）已经盯着
`order_return.py` / `orders.py::return_order_endpoint` / `rbac.py` 的权限矩阵。
本脚本的注入点刻意落在**它不看的地方**：
`services/order_return_request.py`（新服务）、`api/v1/return_requests.py`（6 个新端点）、
`services/message_center.py` + `push_events.py`（消息链路）、
`AiWriteReturnRequest.kt` / `AiWrite.kt::forRole` / `ReportCenter.kt`（AI 与审计页）。
**只有一条例外**（把 `ORDER_RETURN` 加进货主矩阵）旧检查也看 ——
它列在这里是为了证明新判据里那条 `ORDER_RETURN\\b` 的两半都活着（见下面该条的注释）。
⚠️ ⑥ / ⑥b 落在 `orders.py::return_order_endpoint`（那份旧检查也读这个函数）——
这是**故意的**：直连退货的规则在 2026-09-21 换过方向，新的判据必须证明自己对
上面那几种破坏有反应，哪怕注入点与旧检查重叠。

## 现场保护（**复用公共机制，不另造一套**）
· `_airepo.refuse_if_injecting` —— 别人的反向验证正在跑时拒绝出结论；
· `_airepo.lock_reverse_verify` —— 上锁期间并发的**检查**会拒绝出结论（源码是故意脏的）；
· `_airepo.take_snapshot` / `restore_snapshot` —— 被杀在半路时的整目录兜底；
· 每个文件另做**逐字节**还原（`read_bytes` → 注入 → `finally: write_bytes(原始字节)`），
  跑完自检 sha256：一个字节都不能变（换行风格 CRLF/LF 也原样带回去）。

⚠️ 跑它的时候**不要改源码**：`restore_snapshot` 是按开跑前的快照写回的，
并发做的修改会被一起抹掉（`_airepo.py` 头部记着那次实测：抹掉过 15 个文件）。
本脚本对此加了一道自保：如果快照里**别的文件**在跑的过程中变了（＝有人在并发改），
它**不做**整目录还原，只打警告列出来，绝不去动别人的文件。

⚠️ 跑完之后 `_tools/qa/_check_backend_fresh.py` 会**红**（"本机后端跑的是旧代码"）：
注入再还原会把那 6 个后端文件的 mtime 刷新一遍，而**内容一个字节都没变**
（本脚本末尾的 sha256 自检就是证明）。这不是本脚本特有的问题 ——
仓库里每一份 `_reverse_verify_*.py` 跑完都是这样，那条检查自己的输出里也写了这一点，
它的修法是"重启本机开发后端"。**这里刻意不去改文件的 mtime 来把那条红按掉**：
"跑完反向验证就重启后端"是仓库明确选择保留的提醒，按掉它等于替别人做决定。

用法：python _tools/qa/_reverse_verify_return_request.py    # 全部报红 → 退出码 0
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
CHECK = HERE / "_check_return_request.py"

SERVICE = ROOT / "backend/app/services/order_return_request.py"
API_FILE = ROOT / "backend/app/api/v1/return_requests.py"
ORDERS_API = ROOT / "backend/app/api/v1/orders.py"
RBAC = ROOT / "backend/app/core/rbac.py"
PUSH = ROOT / "backend/app/services/push_events.py"
MSG = ROOT / "backend/app/services/message_center.py"
AI_RR = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteReturnRequest.kt"
AI_WRITE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt"
REPORT = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt"
#: 两端「退货申请」的列表内核：消费点之一 + 唯一实现（2026-09-21 收口）
DISPATCH_RR_VM = (
    ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherReturnRequestsViewModel.kt"
)
RETURNS_VM_CORE = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/common/ReturnRequestsViewModel.kt"
#: 两端「退货申请」的页面（2026-09-21 第二轮收口：档位标签 / 定位说明 / 行首都收进 common）
DISPATCH_RR_SCREEN = (
    ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DispatcherReturnRequestsScreen.kt"
)
SHIPPER_RR_SCREEN = (
    ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/ShipperReturnRequestsScreen.kt"
)

# 每一条都要**真的替换到**（原文出现次数 != 1 就报 SKIP，绝不当成通过）。
# 元组 = (说明, 文件, 原文, 替换成, 期望被点出来的判据关键字)
MUTATIONS: list[tuple[str, Path, str, str, str]] = [
    # ① 申请即退货（用户原话直接反了）。旧检查不看这个函数。
    (
        "① submit() 里加一行 return_order(...)（「申请即退货」复活）",
        SERVICE,
        "    _validate_lines(order, items)\n",
        "    _validate_lines(order, items)\n"
        "    return_order(db, order, items, note=note, operator_id=shipper_id)\n",
        "submit() 里没有 return_order",
    ),
    # ② 执行自己写一份（钱的实现变成两处）。旧检查不看 fulfill。
    (
        "② fulfill() 自己写红冲、不调唯一入口（钱有两处实现）",
        SERVICE,
        "    returned = return_order(db, order, items, note=note, operator_id=dispatcher_id)\n",
        # ⚠️ 注入的代码**不要求能跑**（判据是扫源码，不 import 后端）：
        #    这里只求"形状对"—— 一个自己写 Ledger 的 fulfill。
        "    db.add(Ledger(order_id=order.id, quantity=-1, total=-1))\n"
        "    returned = ReturnResult(order_no=order.order_no)\n",
        "fulfill() 真的调了 order_return.return_order",
    ),
    # ③ 数量锁死被破（端点签名多了数量）。旧检查完全不看这 6 个端点。
    (
        "③ fulfil 端点签名多一个 quantity 参数（数量锁死作废）",
        API_FILE,
        "def fulfill_return_request(\n    request_id: int,\n",
        "def fulfill_return_request(\n    request_id: int,\n    quantity: int = Query(0),\n",
        "端点的函数签名里没有数量参数 quantity",
    ),
    # ④ 货主申请权被删（"所有货主都能申请"没落地）。旧检查**不看**这条（它只钉执行权）。
    (
        "④ 把 ORDER_RETURN_REQUEST 从货主的 frozenset 里删掉",
        RBAC,
        "            Permission.ORDER_RETURN_REQUEST,\n",
        "",
        "货主矩阵里有 ORDER_RETURN_REQUEST",
    ),
    # ⑤ 货主拿到执行权（申请制变成装饰）。
    #    ⚠️ 这一条**旧检查也看**（`_check_order_return.py` 里同一条 `ORDER_RETURN\b`）——
    #    列在这里是为了证明**新**判据的这一半也活着：那一半靠 `\b` 把
    #    `ORDER_RETURN_REQUEST`（正确）与 `ORDER_RETURN`（错误）分开，
    #    `\b` 一旦被谁"顺手去掉"，货主那条**正确**的申请权就会被判成越权。
    (
        "⑤ 把 ORDER_RETURN 加进货主的 frozenset（货主能自己改应收）",
        RBAC,
        "            Permission.ORDER_RETURN_REQUEST,\n",
        "            Permission.ORDER_RETURN,\n            Permission.ORDER_RETURN_REQUEST,\n",
        "货主矩阵里没有 ORDER_RETURN",
    ),
    # ⑥ 直连退货**不再自动关闭那张申请**（同一批货被退两遍）。
    #
    # ⚠️ 这一条**换过一次方向**（2026-09-21 用户拍板：规则从「直连退货必须被 400 挡住」
    #    改成「允许直连 + 自动取消申请」）。旧注入是"把 400 那一段删掉"，现在那样删
    #    反而是**符合新规则**的，注入必须跟着改成"把自动关闭这一次调用删掉"：
    #    漏掉它 → 申请书停在 pending → 再点「办理」时余量够、校验全过 → 退第二遍。
    (
        "⑥ 删掉 orders.py 里 close_by_direct_return(...) 这一次调用（申请不会被自动关闭）",
        ORDERS_API,
        "        closed = None\n"
        "        closed_note = \"\"\n"
        "        if pending_req is not None:\n"
        "            closed = return_request_svc.close_by_direct_return(\n"
        "                db,\n"
        "                order,\n"
        "                dispatcher_id=current.id,\n"
        "                items=[ReturnItem(order_product_id=i.order_product_id, quantity=i.quantity) for i in body.items],\n"
        "            )\n"
        "            if closed is not None:\n"
        "                closed_note = closed[1]\n"
        "                closed = closed[0]\n",
        "        closed = None\n"
        "        closed_note = \"\"\n",
        "真的调了 close_by_direct_return",
    ),
    # ⑥b 顺序反了：先 `db.commit()` 再关申请。
    #     ⚠️ 这条与⑥**必须分开注入**：只钉"调了没有"是不够的 —— 挪到 commit 之后，
    #     "那一次调用还在"照样成立，而提交那一刻申请仍是 pending（并发点「办理」就穿过去了），
    #     关申请自己抛错时货也已经落库、申请永远关不掉。顺序判据靠这一条证明它真的在看顺序。
    (
        "⑥b 把 close_by_direct_return(...) 挪到 db.commit() 之后（顺序反了）",
        ORDERS_API,
        "        closed = None\n"
        "        closed_note = \"\"\n"
        "        if pending_req is not None:\n"
        "            closed = return_request_svc.close_by_direct_return(\n",
        "        closed = None\n"
        "        closed_note = \"\"\n"
        "        db.commit()\n"
        "        if pending_req is not None:\n"
        "            closed = return_request_svc.close_by_direct_return(\n",
        "关申请发生在 db.commit() **之前**",
    ),
    # ⑦ AI 动作的角色写反（货主多出一个必然 403 的卡）。旧检查不看 Kotlin 动作表。
    (
        "⑦ AiWriteReturnRequest.kt 里 apply 的 roles 改成 DISPATCHER",
        AI_RR,
        "            roles = setOf(AiRole.SHIPPER),\n        ),\n"
        "        AiWriteAction(\n            id = AiWrites.RETURN_REQUEST_WITHDRAW,\n",
        "            roles = setOf(AiRole.DISPATCHER),\n        ),\n"
        "        AiWriteAction(\n            id = AiWrites.RETURN_REQUEST_WITHDRAW,\n",
        "只给货主",
    ),
    # ⑧ 审计页中文名被删（卡片上直接印原始码）。
    (
        "⑧ ReportCenter.kt 里删掉一条动作码的中文名",
        REPORT,
        '    "ORDER_RETURN_REQUEST_WITHDRAW" -> "撤回退货申请"\n',
        "",
        "有中文名",
    ),
    # ⑨ 审计留痕被抽掉（"这是谁决定的"事后无法回答）。
    (
        "⑨ withdraw() 的 write_log 被改名（撤回不再留痕）",
        SERVICE,
        "    req.status = ReturnRequestStatus.WITHDRAWN.value\n    write_log(\n",
        "    req.status = ReturnRequestStatus.WITHDRAWN.value\n    _write_log(\n",
        "写了 ORDER_RETURN_REQUEST_WITHDRAW 审计",
    ),
    # ⑩ 消息发错人（货主永远不知道办没办成）。旧检查不看消息中心。
    (
        "⑩ 办理完成的消息不再发给货主（收件人被改成 0）",
        MSG,
        "        recipient_id=req.shipper_id,\n"
        '        category="order",\n'
        '        type="order.return_request.done",\n',
        "        recipient_id=0,\n"
        '        category="order",\n'
        '        type="order.return_request.done",\n',
        "发给**货主**",
    ),
    # ⑪ 第 2 跳断掉（发布者不再被调用＝消息不落库）。旧检查不看 push_events。
    (
        "⑪ push_events 里 push_return_request_done 不再调发布者（第 2 跳断了）",
        PUSH,
        "        await message_center.publish_return_request_done(\n"
        "            db,\n"
        "            request_id,\n"
        "            returned_amount=returned_amount,\n"
        "            refund_amount=refund_amount,\n"
        "            fully_returned=fully_returned,\n"
        "        )\n",
        "        pass\n",
        "第 2 跳：push_return_request_done",
    ),
    # ⑫ forRole 只过滤一个方向（声明对了、门没关）。旧检查不看 forRole。
    (
        "⑫ forRole 的派单员那一支不再按 roles 过滤（roles 对派单员形同虚设）",
        AI_WRITE,
        "            AiRole.DISPATCHER -> ALL.filter {\n"
        "                (it.roles == null || role in it.roles) && !it.memberOnly\n"
        "            }\n",
        "            AiRole.DISPATCHER -> ALL.filter {\n"
        "                !it.memberOnly\n"
        "            }\n",
        "都按 roles 过滤",
    ),
    # ⑬ 客户端：两端共用一个列表内核（2026-09-21 收口）。
    #    两条注入各打一条判据：① 子类自己又排一次定位；② 内核不再切到「全部」档。
    (
        "⑬ 派单员端又自己排一次定位（两端各一份实现，迟早分叉）",
        DISPATCH_RR_VM,
        "    /** 派单员看待办（`status=` 就是当前档位的 key）。 */",
        "    private fun dupFocus(id: Long) = focusReturnRequestFirst(items, id)\n\n"
        "    /** 派单员看待办（`status=` 就是当前档位的 key）。 */",
        "定位规则只有内核在调",
    ),
    (
        "⑬ 带定位进来不再切到「全部」档（已办完的那条必然找不到，界面却说\"没找到那条申请\"）",
        RETURNS_VM_CORE,
        "        if (initialFocusRequestId > 0L) tab = tabAllIndex",
        "        if (false) tab = tabAllIndex",
        "带定位进来先用「全部」档拉",
    ),
    # ⑭ 页面上的三小块（2026-09-21 第二轮收口）
    (
        "⑭ 派单端又把定位徽章抄回页面里（两端各说各的）",
        DISPATCH_RR_SCREEN,
        "        ReturnRequestsHeading(req = req, focused = focused)",
        "        if (focused) { Text(\"消息里点进来的这一条\") }\n"
        "        ReturnRequestsHeading(req = req, focused = focused)",
        "定位徽章的文案只许在一个文件里",
    ),
    (
        "⑭ 货主端又自己按下标算档位标签（两页顺序相反 → 张数挂到另一档上）",
        SHIPPER_RR_SCREEN,
        "                labels = returnTabLabels(SHIPPER_RETURN_TABS, vm.pendingCount),",
        "                labels = SHIPPER_RETURN_TABS.mapIndexed { i, t ->\n"
        "                    if (i == 0 && vm.pendingCount > 0) t.label + \" \" + vm.pendingCount else t.label\n"
        "                },",
        "两端页面不许自己算档位标签",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def read_src(p: Path) -> tuple[str, bool]:
    """返回 (换行风格归一成 \\n 的文本, 原文是不是 CRLF)。"""
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    """按**原文的换行风格**写回（混着写会让 `git diff` 整文件变红，别人没法 review）。"""
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_check() -> tuple[int, str]:
    env = os.environ.copy()
    # 让子进程知道"源码是**故意**脏的"（见 `_airepo.is_rv_child`）：
    # 不传这一条的话，检查会走 `refuse_if_injecting` 拒绝出结论 —— 注入就永远"抓不到"。
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
    """现场与快照不一致的文件（只看 `_airepo.SNAPSHOT_DIRS` 那几个目录）。"""
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
    if refuse_if_injecting("退货申请反向验证"):
        return 1
    if not CHECK.exists():
        print(f"❌ 找不到 {CHECK}（红线被改名/搬走了？）")
        return 1

    touched = sorted({m[1] for m in MUTATIONS})
    missing = [str(p) for p in touched if not p.exists()]
    if missing:
        print(f"❌ 注入点文件不存在：{missing}")
        return 1
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

        for label, path, old, new, expect in MUTATIONS:
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
            fails = [ln.strip() for ln in out.splitlines() if "[FAIL]" in ln]
            got = next((ln for ln in fails if expect in ln), None)
            hit = code != 0 and got is not None
            print(f"  [{'OK' if hit else 'MISS'}] 注入：{label}")
            print(f"         抓它的判据：{got[7:].strip() if got else '（没有任何判据承认这条注入）'}")
            print(f"         本次共红 {len(fails)} 条、退出码 {code}")
            if not hit:
                print(f"         ⚠️ 期望关键字 {expect!r} 没出现在失败清单里")
                for f in fails[:4]:
                    print(f"            · {f}")
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
        others = [d for d in snapshot_diffs() if d not in {str(p.relative_to(ROOT)).replace("\\", "/") for p in touched}]
        if others:
            # ⚠️ 有人在跑的过程中改了**别的**文件：绝不能整目录写回（那会把他的改动一起抹掉，
            #    `_airepo.py` 头部记着实测抹掉过 15 个文件）。只删快照 + 把文件列给他。
            shutil.rmtree(snapshot_dir(), ignore_errors=True)
            print("\n⚠️ 快照期间**别的文件**也变了（有人在并发改源码），为了不抹掉别人的改动，"
                  "本次不做整目录还原：")
            for d in others:
                print("     - " + d)
        else:
            fixed = restore_snapshot()
            print(f"\n✅ 整目录快照还原：写回 {len(fixed)} 个文件"
                  f"（正常应为 0 —— 逐字节还原已经把现场复原了）")
            for f in fixed:
                print("     · " + f)

    changed = [str(p.relative_to(ROOT)) for p in touched if sha(p) != before[p]]
    print(f"✅ 逐字节还原自检：{len(touched) - len(changed)}/{len(touched)} 个注入点文件与跑之前**完全一致**")
    for c in changed:
        print("     ❌ 没还回去：" + c)
    if changed:
        bad += 1
    stat_after = git_numstat(touched)
    same = stat_after == stat_before
    print(f"{'✅' if same else '❌'} git 自检：这些文件的 `git diff --numstat` 跑前跑后一致"
          f"（{'没有多出/少掉任何改动' if same else '有差异，见下'}）")
    if not same:
        print("     跑前：" + repr(stat_before[:400]))
        print("     跑后：" + repr(stat_after[:400]))
        bad += 1

    print()
    if bad:
        print(f"❌ {bad} 条不成立（红线对它们不敏感，或者现场没还干净）")
        return 1
    print(f"✅ 全部 {len(MUTATIONS)} 种注入都被抓到 + 源码已还原"
          f"（逐字节 sha256 一致、git numstat 一致）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
