"""反向验证：`_tools/qa/_check_list_order.py` 那些判据**真的抓得住**吗（2026-09-22）。

手法与 `_reverse_verify_hints.py` 同一套：**按字节备份 → 注入 → 跑红线（期望非零退出且命中指定判据）
→ 按字节还原 → 校验 sha256**。⛔ 全程不碰 `git checkout --`。

用法：
    python _tools/qa/_reverse_verify_list_order.py          # 全部跑
    python _tools/qa/_reverse_verify_list_order.py --list   # 只列注入点
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_list_order.py"
API = "backend/app/api/v1/"
SVC = "backend/app/services/usage_service.py"
SCHEMA = "backend/app/schemas/order.py"
DTS = "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateViewModel.kt"

INJECTIONS: list[tuple[str, str, str, str, str]] = [
    ("① 一个列表退回「新的在前」（用户定的第二键是「先创建的在前」）",
     API + "shipper.py",
     "with_popularity(stmt, ShipperContact, usage_service.KIND_CONTACT, current)",
     "order_by(ShipperContact.id.desc())",
     "shipper.py 的「常用联系人」走了共用排序入口"),

    ("② kind 定义了却没人按它排（记了也不往前，静默失效）",
     SVC,
     'KIND_CONTACT = "contact"',
     'KIND_CONTACT = "contact"\nKIND_NOBODY = "nobody"',
     "每个 kind 都有一个列表接上它"),

    ("③ 顺手给**订单列表**也套上常用度（翻账要往下翻几万行）",
     API + "orders.py",
     "    q = select(Order).options(selectinload(Order.order_products)).order_by(Order.id.desc())",
     "    q = select(Order).options(selectinload(Order.order_products)).order_by(Order.id.desc())\n"
     "    q = usage_service.with_popularity(q, Order, usage_service.KIND_USER, current)",
     "orders.py 仍然是时间/编号倒序"),

    ("④ 漏掉 coalesce（没用过的行因为 NULL 沉到最后，正好反了）",
     SVC,
     "func.coalesce(uc.use_count, 0).desc()",
     "uc.use_count.desc()",
     "必备 coalesce"),

    ("⑤ 第二键改成 id 降序（变成「新建的在最前」）",
     SVC,
     "desc(), model.id.asc()",
     "desc(), model.id.desc()",
     "第二键是 id 升序"),

    ("⑥ 计数改成读改写（两部手机同时点会丢一次）",
     SVC,
     "values(use_count=func.coalesce(UsageCounter.use_count, 0) + 1, last_used_at=stamp)",
     "values(use_count=row.use_count + 1, last_used_at=stamp)",
     "计数由数据库自增"),

    ("⑦ 端点自己写一份排序（绕开那唯一入口）",
     API + "shipper.py",
     "with_popularity(stmt, ShipperAddress, usage_service.KIND_ADDRESS, current)",
     "order_by(func.coalesce(UsageCounter.use_count, 0).desc())",
     "端点文件里没有自己写的常用度排序"),

    ("⑧ App 下单不再传 id（真机上一次都不计分，且不报错）",
     VM,
     "                            addressId = pickedAddressId,\n"
     "                            locationId = pickedLocationId,\n",
     "",
     "下单时把 id 一起提交"),

    ("⑨ 地图自己选点时不清 id（把上一次的线路记到这一单头上）",
     VM,
     "        pickedAddressId = null\n        pickedLocationId = null\n",
     "",
     "地图自己选点时**清掉** id"),

    ("⑩ 后端不再收 contact_id（App 传了也白传）",
     SCHEMA,
     "    contact_id: int | None = Field(",
     "    contact_id_removed: int | None = Field(",
     "后端 OrderCreate 收 contact_id"),

    ("⑪ 重置计数改成清**全表**（把所有人的常用度一起抹掉）",
     "backend/app/api/v1/usage.py",
     "delete(UsageCounter).where(UsageCounter.user_id == current.id)",
     "delete(UsageCounter)",
     "⛔ 后端**只清自己的行**"),

    ("⑫ 重置那一格不再弹确认框（误碰一下就清光，且没法还原）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/profile/BasicSettingsScreen.kt",
     "onClick = { showResetConfirm = true },",
     "onClick = { },",
     "点它**先弹确认框**"),

    ("⑬ 重置那一格被删掉（用户要的入口没了）",
     "android/app/src/main/java/com/tapmoay/sorders/ui/profile/BasicSettingsScreen.kt",
     'title = "重置计数",',
     'title = "重置",',
     "「基础设置」里有「重置计数」那一格"),
]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def run_check() -> tuple[int, str]:
    r = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    print("先确认干净状态下是绿的：", end=" ")
    rc, _ = run_check()
    if rc != 0:
        print("❌ 现在就是红的，先修好再跑反向验证")
        return 1
    print("✅ 绿")

    caught = 0
    problems: list[str] = []
    for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
        path = ROOT / rel
        if not path.exists():
            problems.append(f"{name}：找不到 {rel}")
            print(f"\n[{i}] {name}\n  ❌ 找不到 {rel}")
            continue
        orig = path.read_bytes()
        orig_sha = sha(orig)
        text = orig.decode("utf-8")
        eol = "\r\n" if "\r\n" in text else "\n"
        if eol != "\n":
            old = old.replace("\n", eol)
            new = new.replace("\n", eol)
        pat = old[3:] if old.startswith("re:") else re.escape(old)
        injected, n = re.subn(pat, new, text, count=1)
        if n != 1:
            problems.append(f"{name}：锚点没命中（{rel} 里的 {old[:40]!r}）")
            print(f"\n[{i}] {name}\n  ❌ 锚点没命中，跳过（注入点腐烂了）")
            continue
        inj_bytes = injected.encode("utf-8")
        path.write_bytes(inj_bytes)
        try:
            rc, out = run_check()
        finally:
            now = path.read_bytes()
            if now != inj_bytes:
                print(f"\n[{i}] {name}\n  🛑 有别的东西改了 {rel} —— **拒绝还原**，请人工处理！")
                return 2
            path.write_bytes(orig)
        if sha(path.read_bytes()) != orig_sha:
            print(f"\n[{i}] {name}\n  🛑 {rel} 还原后哈希对不上，停手")
            return 2

        hit = f"[!!]   {want}" in out
        if rc != 0 and hit:
            caught += 1
            print(f"\n[{i}] {name}\n  ✅ 被抓到（红线非零退出，命中「{want}」）")
        else:
            why = "红线居然还是绿的" if rc == 0 else f"退出了，但输出里没有「[!!]   {want}」"
            problems.append(f"{name}：{why}")
            print(f"\n[{i}] {name}\n  ❌ {why}")

    print("\n" + "=" * 60)
    print(f"{caught}/{len(INJECTIONS)} 种破坏方式被抓住")
    if problems:
        print("❌ 有漏网的：")
        for p in problems:
            print("   -", p)
        return 1
    print("✅ 全部注入都被抓住，且每个文件都按字节还原")
    return 0


if __name__ == "__main__":
    sys.exit(main())
