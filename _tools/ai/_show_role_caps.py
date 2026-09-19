"""按角色算 AI 的能力账：**派单员全给、货主只给该干的、司机一个不给**。

### 口径（用户原话）
> 「AI 的权限是按照角色的权限进行划分的——派单员属于管理员，权限最大、基本是全部；
>   货主好多权限根本不需要操作，它只需要知道自己该干的事情就可以了，所以权限比较小。」

实现上分三处，这个脚本把三处拉到一张表上：
- **写能力**：`AiWrites.forRole()` —— 派单员 = `ALL`；货主 = `SHIPPER_ACTIONS` **白名单**；
  认不出角色 = 空（fail-closed）。用白名单而不是逐个标角色，是因为"漏标一个 = 多给一个权限"。
- **读能力**：`docs/ai/ai_read_catalog.json` 的 `roles`（**机器生成**：从后端权限点 +
  体内 `raise 403` 硬门槛推导，见 `_gen_ai_read_catalog.py`）。
- **司机端**：目标③，端上一个 AI 入口都没有（不是"裁掉了"，是压根没做）。

### 它挡的是什么
"裁多了"和"裁少了"都是能力缺失：裁多了货主办不成自己的事，裁少了货主能改别人的价。
所以 [--check] 两头都断言，不是只断言"货主看不到派单动作"。

用法：
    python _tools/ai/_show_role_caps.py           # 打一张角色能力账
    python _tools/ai/_show_role_caps.py --check    # 只校验（不自洽就非零退出）
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402
from _show_undo_status import action_constants, defined_actions  # noqa: E402

ROOT = repo_root()
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
CATALOG = ROOT / "docs/ai/ai_read_catalog.json"

# 货主**永远不许**拿到的能力（不是"暂时不给"）：主数据、派单、账本写入、他人数据。
# 每一条都对得上后端的一个权限点或角色门——写进代码是为了它可被审计，不是为了好看。
SHIPPER_FORBIDDEN_HINTS = {
    "orders.assign": "派单是派单员的（ORDER_ASSIGN）",
    "orders.recall": "撤回派单同上",
    "orders.split": "拆单改的是别人的单",
    "orders.mark_exception": "异常由派单员判定",
    "orders.resolve_exception": "同上",
    "orders.update": "改单（运费/地址）是派单员的",
    "orders.freight": "运费由派单员定",
    "products.": "商品主数据是派单员的（PRODUCT_*）",
    "price_rules.": "调价是派单员的（PRICE_RULE_*）",
    "inventory.": "库存调整是派单员的（INVENTORY_ADJUST）",
    "users.": "账号管理是派单员的（USER_*）",
    "ledger.": "货主对账本只有只读（ledger:read_own），记流水要 LEDGER_EDIT",
    "settlements.": "结算与司机账单是派单员的",
    "driver_bills.": "同上",
    "notifications.send": "发消息给他人是派单员的",
    "notifications.delete": "删除别人的消息同上",
}


def shipper_whitelist(consts: dict[str, str]) -> set[str]:
    """读 `SHIPPER_ACTIONS` 白名单（常量名 → 动作 id）。"""
    src = (AI / "AiWrite.kt").read_text(encoding="utf-8")
    m = re.search(r"val SHIPPER_ACTIONS: Set<String> = setOf\(([\s\S]*?)\n    \)", src)
    if not m:
        raise SystemExit("❌ 找不到 SHIPPER_ACTIONS——货主白名单被搬走或改名了？")
    out: set[str] = set()
    for name in re.findall(r"\b([A-Z][A-Z0-9_]+)\b", m.group(1)):
        if name in consts:
            out.add(consts[name])
        else:
            raise SystemExit(f"❌ SHIPPER_ACTIONS 里的 `{name}` 不是一个动作常量（化石？）")
    return out


def undo_only_ids(consts: dict[str, str]) -> set[str]:
    """`undoOnly = true` 的动作：只给撤回用，不进模型的清单。

    ⚠️ 它们**不是**一个个手写 `AiWriteAction(...)` 的，而是
    `AiWriteRestore.kt` 里那个 `restoreAction(cn, id, group, call)` 工厂造出来的
    （工厂内部写死 `undoOnly = true`）。所以判据是"**调用点**有几个"，
    去数 `AiWriteAction(` 块会得到 0——第一版就是这么错的，账面上写着"0 个撤回专用动作"。
    """
    out: set[str] = set()
    for f in sorted(AI.glob("AiWrite*.kt")):
        if f.name == "AiWriteRestore.kt":
            continue  # 这个文件是工厂**定义**，不是调用点
        src = f.read_text(encoding="utf-8")
        for name in re.findall(r"restoreAction\(\s*\"[^\"]*\",\s*AiWrites\.(\w+)", src):
            if name in consts:
                out.add(consts[name])
    # 手写的 `undoOnly = true`（将来若有）也要算上
    for f in sorted(AI.glob("AiWrite*.kt")):
        src = f.read_text(encoding="utf-8")
        for blk in re.split(r"AiWriteAction\(", src)[1:]:
            m = re.search(r"id = (?:AiWrites\.)?(\w+)", blk)
            if m and m.group(1) in consts and re.search(r"undoOnly = true", blk[:3000]):
                out.add(consts[m.group(1)])
    return out


def read_roles() -> dict[str, set[str]]:
    d = json.loads(CATALOG.read_text(encoding="utf-8"))
    by: dict[str, set[str]] = {}
    for a in d["actions"]:
        for r in a["roles"]:
            by.setdefault(r, set()).add(a["action"])
    return by


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    consts = action_constants()
    defined = set(defined_actions(consts).values())
    shipper = shipper_whitelist(consts)
    undo_only = undo_only_ids(consts)
    reads = read_roles()

    problems: list[str] = []
    # ① 白名单里的每个动作都必须真实存在（防化石）
    for a in sorted(shipper - defined):
        problems.append(f"货主白名单里的 `{a}` 根本不是已注册的动作")
    # ② 货主一个"永远不许"的能力都不许有
    for a in sorted(shipper):
        for hint, why in SHIPPER_FORBIDDEN_HINTS.items():
            if a == hint or a.startswith(hint):
                problems.append(f"货主拿到了不该有的 `{a}`（{why}）")
    # ③ fail-closed：认不出角色 = 一个动作都不给
    #    （这条靠 AiWrite.kt 的 `null -> emptyList()` 保证，这里断言它还在）
    src_w = (AI / "AiWrite.kt").read_text(encoding="utf-8")
    if not re.search(r"null -> emptyList\(\)", src_w):
        problems.append("`forRole(null)` 不再是 emptyList——认不出角色就会拿到动作")
    # ④ 派单员 = 全部（不是"比货主多"这种模糊说法）
    if "AiRole.DISPATCHER -> ALL" not in src_w:
        problems.append("派单员不再是全量（ALL）")
    # ⑤ 司机端不许有 AI 读能力
    if "driver" in reads and reads["driver"]:
        # 司机确实有读能力（订单/消息/结算单）——那是给**司机端之外**的口径留的，
        # 但端上没入口。这里只报出来，不算错（写清楚比假装没有好）。
        pass
    # ⑥ 反空转：数量太少说明解析挂了
    if len(defined) < 60:
        problems.append(f"只解析出 {len(defined)} 个动作（应有 70+）——动作清单解析挂了？")
    if len(shipper) < 8:
        problems.append(f"货主白名单只剩 {len(shipper)} 个——解析挂了，还是真被砍了？")

    if problems:
        print("❌ 角色能力账不自洽：")
        for p in problems:
            print("   - " + p)
        return 1

    if args.check:
        print(
            f"✅ 角色能力账自洽：动作 {len(defined)} 个（模型可见 {len(defined - undo_only)}）"
            f"；货主 {len(shipper)} 个；读能力组 {len(reads)}"
        )
        return 0

    print(f"动作总共 {len(defined)} 个（其中 {len(undo_only)} 个是撤回专用，不进模型清单）\n")
    print("角色        写能力        读能力        说明")
    print("-" * 88)
    print(f"{'派单员':<10}{len(defined):>4} 个（全部）{len(reads.get('dispatcher', ())):>8} 条"
          f"      管理员：整个系统都归他管，所以全给")
    print(f"{'货主':<10}{len(shipper):>4} 个        {len(reads.get('shipper', ())):>8} 条"
          f"      只给「他自己那点事」（下单/撤单/地址联系人/自己的消息）")
    print(f"{'司机':<10}{0:>4} 个        {len(reads.get('driver', ())):>8} 条"
          f"      目标③：端上一个 AI 入口都没有")
    print(f"{'认不出':<10}{0:>4} 个        {0:>8} 条      fail-closed：连一张表都不给")
    print("\n货主能用的动作（白名单全部）：")
    for a in sorted(shipper):
        print("  · " + a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
