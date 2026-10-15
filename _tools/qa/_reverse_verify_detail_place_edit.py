"""反向验证：`_tools/qa/_check_detail_place_edit.py` 那些判据**真的抓得住**吗（2026-10-15）。

手法与仓库里其它 `_reverse_verify_*.py` 同一套：**按字节备份 → 注入 → 跑红线（期望非零退出且命中
指定判据）→ 按字节还原 → 校验 sha256**。⛔ 全程不碰 `git checkout --`（那会在真有改动时抹掉工作）。

遵守注入锁的规矩（`_tools/ai/_airepo.py`）：`lock_reverse_verify` / `refuse_if_injecting`。

⚠️ 每个注入点都挑**真会有人这么改**的那条路（十条都编译得过、界面照跑，出事时却看不出来）：
   ① 定位回流绕过全仓唯一那份坐标闸（高德失败时回调的 (0,0) 直接落进这一单，导航指到几内亚湾）；
   ② 回流不认「是不是我发起的那一次」（地图弹层一打开就自己定位 → 静默改掉这一单的地址）；
   ③ 兜底超时被删（拿不到回调就永远停在「正在定位…」，用户只能杀进程）；
   ④ 详情页那处调用加参数（绕过 `OrderEditHost`，也把内联编辑那条红线一起踩了）；
   ⑤ 改地址时不再铺坐标草稿（坐标从进入编辑态那一刻就丢了）；
   ⑥ fail-closed 闸被「简化」掉（文字改了、坐标没了，界面照样说「已经改好」）；
   ⑦ 坐标不再随这一单报上去（后端缺席语义＝「不给就不改」→ 这一单的落点原地不动）；
   ⑧ 抽屉标题写回下单页那句（这一页的语义变成「重新选收货地址」，与「改」不是一回事）；
   ⑨ 共享库管理入口改成无条件打开（货主也能改别人的地点；后端是 DispatcherOnly，用户只看到 403）；
   ⑩ 坐标落草稿不归一（Double 的浮点尾巴"23.021498000000005"回到屏上、也随着这一单报进库）。

用法：
    python _tools/qa/_reverse_verify_detail_place_edit.py          # 全部跑
    python _tools/qa/_reverse_verify_detail_place_edit.py --list   # 只列注入点
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import (  # noqa: E402
    lock_reverse_verify,
    refuse_if_injecting,
    unlock_reverse_verify,
)

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_detail_place_edit.py"
INLINE = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderEditInline.kt"
DETAIL_VM = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailViewModel.kt"
DETAIL = "android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt"

#: (说明, 文件, 原文, 替换成, 期望出现在失败清单里的关键字)
INJECTIONS: list[tuple[str, str, str, str, str]] = [
    (
        "① 定位回流绕过全仓唯一那份坐标闸（高德失败时给的 (0,0) 会直接落进这一单）",
        INLINE,
        """            when (val r = hereResultOf(pt.lat, pt.lng, pt.address)) {
                is HereResult.Fill -> {
                    locateHereError = null
                    edit.applyPickedCoord(r.lat, r.lng, r.address)
                }
                is HereResult.Say -> locateHereError = r.message
            }""",
        "            edit.applyPickedCoord(pt.lat, pt.lng, pt.address.orEmpty())",
        "回流走全仓唯一那份 hereResultOf",
    ),
    (
        "② 回流不认「是不是我发起的那一次」（地图弹层一开就自己定位 → 静默改地址）",
        INLINE,
        "            if (!locatingHere) return@collect",
        "            // 简化：把每一次回调都当成自己发起的那次",
        "回流只认自己发起的那一次",
    ),
    (
        "③ 兜底超时被删（拿不到回调就永远停在「正在定位…」）",
        INLINE,
        """    LaunchedEffect(locatingHere) {
        if (!locatingHere) return@LaunchedEffect
        delay(DETAIL_HERE_TIMEOUT_MS)
        if (locatingHere) {
            locatingHere = false
            locateHereError = "定位超时，没拿到当前位置：请重试，或改用「在地图上选点」。"
        }
    }""",
        "    // 兜底删掉：等不到回调就一直等",
        "超时也收尾，并给出另一条出路",
    ),
    (
        "④ 详情页那处调用加参数（绕过 OrderEditHost，也踩了内联编辑那条红线）",
        DETAIL,
        "                    AddressEditBlock(edit)",
        "                    AddressEditBlock(edit, modifier = Modifier)",
        "详情页那处调用逐字 AddressEditBlock(edit)",
    ),
    (
        "⑤ 改地址时不再铺坐标草稿（坐标从进入编辑态那一刻就丢了）",
        DETAIL_VM,
        "        editDrafts[OrderEditField.ADDRESS_LAT] = o.addressLat.orEmpty()",
        "        // 坐标不铺了（草稿里只剩地址文字）",
        "改地址时坐标与文字",
    ),
    (
        "⑥ fail-closed 闸被「简化」掉（文字改了、坐标没了，界面照样说「已经改好」）",
        DETAIL_VM,
        "        if (!o.addressLat.isNullOrBlank() && (latDraft.isBlank() || lngDraft.isBlank())) {",
        "        if (false) {",
        "fail-closed：这一单本来带着坐标",
    ),
    (
        "⑦ 坐标不再随这一单报上去（后端缺席语义＝「不给就不改」→ 落点原地不动）",
        DETAIL_VM,
        "                        addressLat = latDraft.ifBlank { null },",
        "                        // 坐标不报了",
        "两个坐标字段随这一单一起报",
    ),
    (
        "⑧ 抽屉标题写回下单页那句（这一页的语义变成「重新选收货地址」）",
        DETAIL,
        '            title = "改收货地址",',
        '            title = "选择收货地址",',
        "抽屉标题是「改收货地址」",
    ),
    (
        "⑨ 共享库管理入口改成无条件打开（货主也能改别人的地点；后端只给派单员）",
        DETAIL,
        "            canManagePlaces = vm.canManageSharedPlaces,",
        "            canManagePlaces = true,",
        "共享库管理入口喂的是角色门",
    ),
    (
        "⑩ 坐标落草稿不归一（Double.toString() 把 23.021498 印成 23.021498000000005，屏上与报上去都带着浮点尾巴）",
        DETAIL_VM,
        "        setDraft(OrderEditField.ADDRESS_LAT, coordDraft(lat))",
        "        setDraft(OrderEditField.ADDRESS_LAT, lat.toString())",
        "坐标落草稿前先归一成 6 位小数",
    ),
]


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_check() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(CHECK)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(INJECTIONS, 1):
            print(f"{i:>2}. {name}")
            print(f"      {rel}   ← 期望被「{want}」抓到")
        return 0

    if refuse_if_injecting("改地点（地点库 / 地图 / 我就在这里）反向验证"):
        return 1

    print("先确认干净状态下是绿的：", end=" ")
    rc, _ = run_check()
    if rc != 0:
        print("❌ 现在就是红的，先修好再跑反向验证")
        return 1
    print("✅ 绿")

    lock_reverse_verify()
    caught = 0
    problems: list[str] = []
    try:
        for i, (name, rel, old, new, want) in enumerate(INJECTIONS, 1):
            path = ROOT / rel
            if not path.exists():
                problems.append(f"{name}：找不到 {rel}")
                print()
                print(f"[{i}] {name}")
                print(f"  ❌ 找不到 {rel}")
                continue
            orig = path.read_bytes()
            orig_sha = sha(path)
            text = orig.decode("utf-8")
            eol = "\r\n" if "\r\n" in text else "\n"
            if eol != "\n":
                old = old.replace("\n", eol)
                new = new.replace("\n", eol)
            pat = old[3:] if old.startswith("re:") else re.escape(old)
            injected, n = re.subn(pat, new, text, count=1)
            if n != 1:
                problems.append(f"{name}：锚点没命中（{rel} 里的 {old[:40]!r}）")
                print()
                print(f"[{i}] {name}")
                print("  ❌ 锚点没命中，跳过（注入点腐烂了）")
                continue
            inj_bytes = injected.encode("utf-8")
            path.write_bytes(inj_bytes)
            try:
                rc, out = run_check()
            finally:
                now = path.read_bytes()
                if now != inj_bytes:
                    print()
                    print(f"[{i}] {name}")
                    print(f"  🛑 有别的东西改了 {rel} —— **拒绝还原**，请人工处理！")
                    return 2
                path.write_bytes(orig)
            if sha(path) != orig_sha:
                print()
                print(f"[{i}] {name}")
                print(f"  🛑 {rel} 还原后哈希对不上，停手")
                return 2

            hit = f"[!!]   {want}" in out
            if rc != 0 and hit:
                caught += 1
                print()
                print(f"[{i}] {name}")
                print(f"  ✅ 被抓到（红线非零退出，命中「{want}」）")
            else:
                why = "红线居然还是绿的" if rc == 0 else f"退出了，但输出里没有「[!!]   {want}」"
                problems.append(f"{name}：{why}")
                print()
                print(f"[{i}] {name}")
                print(f"  ❌ {why}")
    finally:
        unlock_reverse_verify()

    print("=" * 60)
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
