"""反向验证 CHG-0032（删除一律先问一句：入口搬进编辑抽屉 + 二次确认）那批修复**真的在检查**。

2026-10-04 用户点名：「把地点线路联系人那里的删除键卡片删除键移到编辑界面当中，并且做二次确认，
不要点一下就直接删掉了，防止误触」。修法是「VM 里 askDelete 只举手（不落库）+ confirmDelete 是唯一
落库点 + 两句话是纯函数并有单测 + 界面三个抽屉一行删除 + 页尾 DangerConfirmDialog + 新判据
`_check_delete_confirm.py` 六层」，这份脚本逐条把修复撤回，证明新判据会红。

| 注入 | 应该红的那一项 |
|---|---|
| askDelete 顺手落库（`delete(it)` 写进举手函数） | askDelete 只举手不落库 |
| confirmDelete 不再清 pendingDelete（先执行后清 / 不清） | confirmDelete 先清掉 pendingDelete 再执行 |
| confirmDelete 少一档（地点那支删掉） | 分支恰好是三档 / 三个落库调用都在它体内 |
| askDelete 不再挡认不出的 kind | askDelete 认不出 kind 就直接不举手 |
| deleteKindLabel 的档名与 RecentlyDeleted.label 分叉（两处各改一处） | 一套说法两项 |
| 标题不再处理空名字（`if (name.isBlank())` → `if (false)`） | 标题在名字空着时退成「删除这条 X？」 |
| 正文里「撤销 / 找不回来」那句被删 | 正文说清还能捞回来 |
| 单测不再调那两个纯函数 | 单测真的在调这两个纯函数 |
| 界面绕过确认直接落库（askDelete → deleteContact） | 页面没有绕过确认直接落库 |
| 确认钮不再走 confirmDelete / 界面少一档入口 | 确认钮走 confirmDelete / 三处只调 askDelete |
| 规范 4.2c 里那句「二次确认」被抹掉 | 规范 4.2c 里写了这次的新规矩 |
| 本脚本的注入锁被摘掉 | 反验脚本拿着注入锁 |
| 登记簿里 CHG-0032 那一行被撤 | 登记簿里有 CHG-0032 这一行 |

⚠️ 快照/还原按**字节**做（仓库里有 CRLF 文件），跑完逐字节核对。
⚠️ 跑的时候拿着注入锁（_airepo.lock_reverse_verify）：并发的检查会拒绝出结论。
⚠️ 只动源码、文档与工具，不跑 gradle、不碰 android/app/build —— 跑完不必重启后端。

用法：python _tools/qa/_reverse_verify_delete_confirm.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools/ai"))

from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

JUDGE = ROOT / "_tools/qa/_check_delete_confirm.py"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/AddressViewModel.kt"
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/AddressScreen.kt"
TEST = "android/app/src/test/java/com/tapmoay/sorders/ui/shipper/AddressDeleteConfirmTest.kt"
DESIGN = "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
REGISTRY = "docs/changes/README.md"
SELF = "_tools/qa/_reverse_verify_delete_confirm.py"


def drop_registry_row(s: str, ident: str) -> str:
    """把登记簿里 ident 那一整行撤掉（不是换字样 —— 判据认的是整行）。"""
    return re.sub(r"^\|\s*[\x60]?" + ident + r"[\x60]?\s*\|.*$\n?", "", s, count=1, flags=re.M)


#: (说明, 相对路径, 注入函数, 期望判词)
#: 期望判词写成 "JUDGE:<新判据 [FAIL] 那一行里的关键词>"
CASES: list[tuple[str, str, object, str]] = [
    (
        "① askDelete 顺手落库（举手函数里就调 delete(it)）",
        VM,
        lambda s: s.replace(
            "pendingDelete = PendingDelete(kind",
            "delete(it)\n        pendingDelete = PendingDelete(kind",
            1,
        ),
        "JUDGE:askDelete 只举手不落库",
    ),
    (
        "② confirmDelete 不再先清 pendingDelete（弹层会卡在那一条上）",
        VM,
        lambda s: s.replace("pendingDelete = null\n        when (p.kind)", "when (p.kind)", 1),
        "JUDGE:confirmDelete 先清掉 pendingDelete 再执行",
    ),
    (
        "③ confirmDelete 少一档（地点那条支线删掉）",
        VM,
        lambda s: s.replace(
            '            "place" -> editingLocation?.let { showLocationDialog = false; deleteLocation(it) }\n',
            "",
            1,
        ),
        "JUDGE:确认按 kind 挑 delete*",
    ),
    (
        "③b 落库那一行被挪出 confirmDelete（谁都能直接删）",
        VM,
        lambda s: s.replace(
            '"contact" -> editingContact?.let { showContactDialog = false; deleteContact(it) }',
            '"contact" -> editingContact?.let { showContactDialog = false }',
            1,
        ),
        "JUDGE:三个落库调用都在 confirmDelete 的函数体里",
    ),
    (
        "④ askDelete 不再挡认不出的 kind（不认也举手）",
        VM,
        lambda s: s.replace("deleteKindLabel(kind) ?: return", 'deleteKindLabel(kind) ?: "东西"', 1),
        "JUDGE:askDelete 认不出 kind 就直接不举手",
    ),
    (
        "⑤ deleteKindLabel 里 place 那档改成别的说法",
        VM,
        lambda s: s.replace('    "place" -> "地点"', '    "place" -> "常用地点"', 1),
        "JUDGE:deleteKindLabel 里 place 那档给用户看的是「地点」",
    ),
    (
        "⑥ RecentlyDeleted 记的地点档名与 deleteKindLabel 分叉",
        VM,
        lambda s: s.replace('kind = "place", label = "地点",', 'kind = "place", label = "常用地点",', 1),
        "JUDGE:「地点」这档在 delete* 里记的 label 与 deleteKindLabel 是同一套说法",
    ),
    (
        "⑦ 三处 RecentlyDeleted 的 kind 拼错一个（撤回会挑错接口）",
        VM,
        lambda s: s.replace('kind = "contact", label = "联系人",', 'kind = "ct", label = "联系人",', 1),
        "JUDGE:三处 RecentlyDeleted 记的 kind 恰好是三档",
    ),
    (
        "⑧ 标题不再处理空名字（会出现一对空引号）",
        VM,
        lambda s: s.replace("if (name.isBlank())", "if (false)", 1),
        "JUDGE:标题在名字空着时退成",
    ),
    (
        "⑨ 正文里「撤销 / 找不回来」那句被删（用户按下删除时在赌）",
        VM,
        lambda s: s.replace(
            '"确认后它就从列表里消失，列表顶上会留一行「已删除$what」，点「撤销」可以恢复；"',
            '"确认后它就从列表里消失。"',
            1,
        ),
        "JUDGE:正文说清还能捞回来",
    ),
    (
        "⑩ 单测不再调那两个纯函数（只剩一个壳）",
        TEST,
        lambda s: s.replace("deleteConfirmTitle(", "deleteConfirmTitleX("),
        "JUDGE:单测真的在调这两个纯函数",
    ),
    (
        "⑪ 界面绕过确认直接落库（askDelete → deleteContact）",
        SCREEN,
        lambda s: s.replace('vm.askDelete("contact")', "vm.deleteContact(vm.editingContact!!)", 1),
        "JUDGE:页面没有绕过确认直接落库",
    ),
    (
        "⑫ 确认钮不再走 confirmDelete（弹层点「删除」什么也不发生）",
        SCREEN,
        lambda s: s.replace("onConfirm = { vm.confirmDelete() },", "onConfirm = { },", 1),
        "JUDGE:确认弹层的确认钮走 vm.confirmDelete()",
    ),
    (
        "⑬ 三处删除入口少一档（kind 拼成不存在的值）",
        SCREEN,
        lambda s: s.replace('vm.askDelete("place")', 'vm.askDelete("spot")', 1),
        "JUDGE:界面三处删除入口只调 vm.askDelete",
    ),
    (
        "⑭ 规范 4.2c 里「二次确认」那句被抹掉（纪律失去文字出处）",
        DESIGN,
        lambda s: s.replace("二次确认", "确认一次"),
        "JUDGE:规范 4.2c 里写了这次的新规矩",
    ),
    (
        "⑮ 本脚本的注入锁被摘掉（注入期间别人照样出结论）",
        SELF,
        lambda s: s.replace("lock_reverse_verify", "rv_lock_x"),
        "JUDGE:反验脚本拿着注入锁",
    ),
    (
        "⑯ 登记簿里 CHG-0032 那一行被撤（ID 用掉了没人知道）",
        REGISTRY,
        lambda s: drop_registry_row(s, "CHG-0032"),
        "JUDGE:登记簿里有 CHG-0032 这一行",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> None:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    p.write_bytes(data.encode("utf-8"))


def run_judge() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(JUDGE)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def hit(out: str, want: str) -> bool:
    return any("[FAIL]" in ln and want in ln for ln in out.splitlines())


def run_all() -> int:
    fails: list[str] = []
    code, out = run_judge()
    if code != 0:
        print("❌ 前提不成立：源码完好时新判据就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时新判据 _check_delete_confirm.py 是绿的")

    touched = sorted({rel for _l, rel, _m, _n in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    crlfs = {rel: b"\r\n" in originals[rel] for rel in touched}

    for label, rel, mutate, node in CASES:
        path = ROOT / rel
        plain = originals[rel].decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(label + "：注入没生效（锚点变了，请更新本脚本）")
            print("  [SKIP] " + label)
            continue
        try:
            write_src(path, mutated, crlfs[rel])
            want = node.split(":", 1)[1]
            rcode, rout = run_judge()
            hit_now = rcode != 0 and hit(rout, want)
        finally:
            path.write_bytes(originals[rel])
        if hit_now:
            print("  [OK] " + label + " → 新判据报红")
        else:
            fails.append(label + "：注入之后新判据没红（修复没有被钉住）")
            print("  [MISS] " + label + " → 仍然全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print("✅ 还原检查：" + str(len(touched)) + " 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print("✅ " + str(len(CASES)) + " 条注入都证明 CHG-0032 的修复真的被钉住了。")
    return 0


def main() -> int:
    lock_reverse_verify()
    try:
        return run_all()
    finally:
        unlock_reverse_verify()


if __name__ == "__main__":
    sys.exit(main())
