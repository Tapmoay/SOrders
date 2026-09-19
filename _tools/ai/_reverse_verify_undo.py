"""反向验证 §20（撤回底线）。

## 为什么这条特别需要反向验证
这一节的每条判据都能**静默失效**，而且失效之后功能"看起来还在"：
- 撤回入口里加一行 `handler.commit(...)` → 撤回变成第二条写入口（绕过角色门/风险档/token），
  但界面上撤回**照样能用**，谁也不会发现；
- 把 `AiRevert.plan(...)` 挪到 `commit` 之后 → 快照永远拿不到（删除类动作那条记录已经没了，
  改类动作的旧值也已经被覆盖），表现是"撤回按钮消失了"，而用户只会以为这个动作本来就不能撤；
- 拿掉暂存区那一行 `undoLineOf` → 卡片上不再回答"误操作了怎么办"，
  用户是点完确认才发现撤不回来；
- **资源表里删掉一行 `delete(...)`** → 那个动作的撤回没了，其余动作照样能撤，
  所以只有"逐个核对每个删除动作都接了线"那条判据能发现它；
- 数据源的 `snapshot` 分支少一个 → 那个资源的撤回全都不给按钮（fail-closed 是好事，
  但"整个资源静默失去撤回"不能没有检查）；
- 后端把 `db.delete(` 加回来 → 撤回按钮还在、点下去报 404。

所以每条都要注入一次，证明检查真的会红。

用法：`python _reverse_verify_undo.py`
"""
from __future__ import annotations

import subprocess
import sys
import re
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
WR = AI / "AiWrite.kt"
WSVC = AI / "AiWriteService.kt"
REVERT = AI / "AiRevert.kt"
RESOURCES = AI / "AiResources.kt"
PRODUCT_PY = ROOT / "backend/app/api/v1/products.py"

CASES: list[tuple[str, Path, object]] = [
    (
        "撤回入口里直接写库（变成第二条写入口）",
        WSVC,
        lambda s: s.replace(
            "        return AiWriteOutcome.NeedConfirm(\n            store.offer(",
            "        handler.commit(plan.payload, \"x\")\n        return AiWriteOutcome.NeedConfirm(\n            store.offer(",
            1,
        ),
    ),
    (
        "撤回快照挪到 commit 之后（写下去之后才抓，抓到的已经是新值）",
        WSVC,
        lambda s: s.replace(
            "            val undo = try {\n                AiRevert.plan(ds, p.actionId, p.payload, p.summary)",
            "            handler.commit(p.payload, \"ai-\" + token)\n            val undo = try {\n                AiRevert.plan(ds, p.actionId, p.payload, p.summary)",
            1,
        ),
    ),
    (
        "卡片不再回答「误操作了怎么办」",
        WR,
        # ⚠️ 锚点跟着实现走（2026-09-19 第十四轮）：这一行现在是"按 isUndo 二选一"，
        #    注入要打在**两种卡共用的那一行**上（只改 undoLineOf 那一支的话，
        #    撤回卡本来就不走它 → 注入等于没做）。
        lambda s: s.replace(
            "                detailLines = detailLines + listOfNotNull(lastLine),",
            "                detailLines = detailLines,",
            1,
        ),
    ),
    (
        "资源表里删掉一个删除动作的接线（那个动作的撤回悄悄没了）",
        RESOURCES,
        lambda s: s.replace("            delete(AiWrites.ADDRESS_DELETE),\n", "", 1),
    ),
    (
        "数据源的 snapshot 少一个分支（那个资源的撤回全都不给按钮）",
        WSVC,
        lambda s: s.replace(
            '            "address" -> AiBefore(id, AiRevertRead.address(repo.addressById(id)))\n',
            "",
            1,
        ),
    ),
    (
        "撤回卡不再写「现值 → 撤回后」（用户没法核对要改成什么）",
        REVERT,
        # ⚠️ 这里**必须**用正则改掉全部出现，不能 `replace(..., 1)`：
        #    `→ 撤回到 ` 在这个文件的头注释里也出现过，只替换第 1 处会打到注释上，
        #    代码没变 → 检查照样绿 → 被判成"注入没生效"。
        #    （而且这一行的代码形态会随卡片文案调整而变，锚在散文串上迟早失效。）
        lambda s: re.sub(r"→ 撤回到 ", " 变成 ", s),
    ),
    (
        "读不到旧值的键被静默丢掉（不再写在卡上）",
        REVERT,
        # 同上：改全部出现，别只改第 1 处——第 1 处可能在注释里，那样代码没变、检查照样绿。
        lambda s: re.sub(r"⚠️ 这一项撤不回来——", "（略）", s),
    ),
    (
        "静默键不再被过滤（地址的经纬度以裸键形式占满卡片）",
        REVERT,
        lambda s: s.replace("                if (k in res.silent) continue\n", "", 1),
    ),
    (
        "警告行改回拼裸键（用户看到 address_lat 而不是「纬度」）",
        REVERT,
        # 同上：改全部出现（这几行的形态一样，都在"警告行"这一族里）。
        lambda s: re.sub(
            r"\$\{cnOf\(res, entry\.id, k\)\}",
            "$k",
            s,
        ),
    ),
    (
        "中文名解析器丢掉「动作声明的字段规格」这一档（payload 专用键又印成裸键）",
        REVERT,
        # 这一条对应真机抓到的那两行（`· change：5 → 撤回到 -5`、「· 「note」不写回」）：
        # 资源表的 labels 只覆盖 readKeys，payload 里的 change/note 不在其中，
        # 所以第二处来源（动作自己的字段规格）一去掉，那两个键就退回英文。
        lambda s: re.sub(
            r"res\.labels\[key\] \?: AiWrites\.byId\(actionId\)\?\.crud\?\.let \{ spec ->"
            r"[\s\S]{0,220}?\} \?: key",
            "res.labels[key] ?: key",
            s,
            count=1,
        ),
    ),
    (
        "「故意不写回旧值」的键连补写都没有（反向流水的原因空着）",
        REVERT,
        lambda s: s.replace(
            "                entry.dropWrite[k]?.let { put(k, it) }\n",
            "",
            1,
        ),
    ),
    (
        "「改类」那句万能免责的写法回来了",
        REVERT,
        lambda s: s.replace(
            "        return \"新建出来的那一条撤不掉，但它可以改、可以停用/下架、也可以删掉——说一句就行\"",
            "        return \"照上面改回去就行\"",
            1,
        ),
    ),
    (
        "后端把物理删除加回来（撤回按钮还在，点下去 404）",
        PRODUCT_PY,
        lambda s: s.replace("    p.is_deleted = True\n", "    db.delete(p)\n    p.is_deleted = True\n", 1),
    ),
]


def strip_comments(src: str) -> str:
    """和红线脚本同一份剥注释规则（用来判"注入有没有真的改到代码"）。"""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"//[^\n]*", "", src)


def run_check() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(HERE / "_check_ai_guardrails.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_status() -> tuple[int, str]:
    """顺带反向验证「撤回状态总览」脚本：它也得会红。"""
    p = subprocess.run(
        [sys.executable, str(HERE / "_show_undo_status.py"), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []

    code, out = run_check()
    if code != 0:
        fails.append(f"前提不成立：源码完好时检查就没过\n{out[-1500:]}")
        print("\n".join(fails))
        return 1
    print("✅ 前提：源码完好时检查是绿的")
    code, out = run_status()
    if code != 0:
        fails.append(f"前提不成立：源码完好时撤回总览没过\n{out[-1500:]}")
        print("\n".join(fails))
        return 1
    print("✅ 前提：源码完好时撤回总览是绿的")

    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（源码里那段已经变了，请更新本脚本的替换串）")
            continue
        # ⚠️ 注入必须**改到代码**：这几个文件的文档注释里大量引用被检查的写法，
        #    只改到注释的话"检查照样绿"——那证明不了判据有效，只证明了这行注入没用。
        #    （这一条是被自己坑出来的：改 `→ 撤回到` 时第一个命中在头注释里。）
        if strip_comments(mutated) == strip_comments(original):
            fails.append(f"{label}：注入只改到了注释，没有改到代码——这条判据没被真正验证")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code, out = run_check()
            code2, out2 = run_status()
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        sec20 = out.split("== 20.")[-1] if "== 20." in out else ""
        red_guard = code != 0 and "❌" in sec20
        red_status = code2 != 0
        if not (red_guard or red_status):
            fails.append(f"{label}：注入后 §20 与撤回总览都没报红（code={code}/{code2}）——判据是空转的")
        else:
            which = "§20" if red_guard else ""
            which += "+总览" if red_status else ""
            print(f"✅ 注入「{label}」→ {which} 报红")
            if not red_guard:
                fails.append(f"{label}：§20 自己没红，是靠总览兜住的（判据偏弱，建议补进 §20）")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ §20 的 {len(CASES)} 条判据都证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
