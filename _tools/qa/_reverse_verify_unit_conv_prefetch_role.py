"""反向验证 BUG-0008（单位换算的预取按角色发）那批修复**真的在检查**。

2026-10-03 用户点名：`GET /api/v1/unit-conversions → 403` 这条后台噪声必须消失，不许留在日志里。
修法是「把『谁能拉』变成 ensure 的第一道门 + 三个调用点各传自己的角色」，
这份脚本逐条把修复撤回，证明对应的检查（判据脚本 / Android 单测）会红。

| 注入 | 应该红的检查 |
|---|---|
| 门被删掉（不看角色就发请求） | 判据 §二 |
| 角色清单里多放司机 / 少了派单员 | 判据 §一（两边清单并排对） |
| `canRead` 改成恒真 | 判据 §二 + Android 单测（真跑一遍） |
| 拉取不再静默（`runCatching` 拿掉） | 判据 §二 |
| 会话预取传 `null` / 传折过的 `Role` / 打回旧签名 | 判据 §三 |
| 下单页改传常量角色 / 商品页干脆不拉了 | 判据 §三 |
| 后端 `require_roles` 放行司机 | 判据 §一、§四 |
| 司机 403 那条用例被删 / 断言被改松 | 判据 §四 |
| 登记行的文档链接被改 / 文档 ID 与文件名不一致 | 判据 §六 |
| 单测里的反向断言被换成正向 / 清单断言被放宽 | 判据 §五 |

⚠️ 快照/还原按**字节**做（仓库里有 CRLF 文件），跑完逐字节核对。
⚠️ 最后一条注入是**真跑一遍 Android 单测**（gradle），它会覆盖 `android/app/build/test-results/`：
   跑完请重跑一次 gradle，否则 `_tools/qa/_android_test_count.py` 会读到 failures>0。

用法：python _tools/qa/_reverse_verify_unit_conv_prefetch_role.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
JUDGE = ROOT / "_tools/qa/_check_unit_conv_prefetch_role.py"
GRADLE = ROOT / "_agent/gradle/gradle-8.9/bin/gradle.bat"

UC = "android/app/src/main/java/com/tapmoay/sorders/ui/common/UnitConverts.kt"
HUB = "android/app/src/main/java/com/tapmoay/sorders/core/RealtimeHub.kt"
CREATE = "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt"
FORM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductFormScreen.kt"
KTEST = "android/app/src/test/java/com/tapmoay/sorders/ui/common/UnitConvAccessTest.kt"
BUC = "backend/app/api/v1/unit_conversions.py"
BTEST = "backend/tests/test_unit_conversions.py"
REG = "docs/changes/README.md"
DOC = "docs/changes/BUG-0008.md"

ROLES = 'val READ_ROLE_KEYS: Set<String> = setOf("shipper", "dispatcher")'
GATE = "if (!canRead(roleKey)) return"
CANREAD = "fun canRead(roleKey: String?): Boolean = roleKey != null && roleKey in READ_ROLE_KEYS"
PREFETCH = "scope.launch { runCatching { UnitConv.ensure(container.repo, s.role) } }"
SCREEN = "UnitConv.ensure(container.repo, container.tokenStore.cachedRole())"

#: (说明, 相对路径, 注入, 期望变红的 node)；`CHECK:` = 跑判据脚本找那条 [FAIL]，`GRADLE:` = 真跑 Android 单测
CASES: list[tuple[str, str, object, str]] = [
    (
        "门被删掉（不看角色就发那次请求）",
        UC,
        lambda s: s.replace(GATE, "if (false) return", 1),
        "CHECK:门就是",
    ),
    (
        "角色清单里多放了司机（门形同虚设）",
        UC,
        lambda s: s.replace(ROLES, ROLES[:-1] + ', "driver")', 1),
        "CHECK:两边解析出来的角色 key",
    ),
    (
        "角色清单里少了派单员（代下单的人再也拉不到换算）",
        UC,
        lambda s: s.replace(ROLES, 'val READ_ROLE_KEYS: Set<String> = setOf("shipper")', 1),
        "CHECK:两边解析出来的角色 key",
    ),
    (
        "canRead 被改成恒真",
        UC,
        lambda s: s.replace(CANREAD, "fun canRead(roleKey: String?): Boolean = true", 1),
        "CHECK:canRead 的实现就是那一行",
    ),
    (
        "拉取不再静默（一次网络抖动就会把页面打红）",
        UC,
        lambda s: s.replace("runCatching { repo.unitConversions() }.onSuccess { accept(it) }", "accept(repo.unitConversions())", 1),
        "CHECK:拉取仍然只有 refresh 一处",
    ),
    (
        "会话预取不看角色（传 null）",
        HUB,
        lambda s: s.replace(PREFETCH, "scope.launch { runCatching { UnitConv.ensure(container.repo, null) } }", 1),
        "CHECK:会话建立时传的是",
    ),
    (
        "会话预取用折过的 Role（批发商照旧 403）",
        HUB,
        lambda s: s.replace(PREFETCH, "scope.launch { runCatching { UnitConv.ensure(container.repo, Role.fromKey(s.role).key) } }", 1),
        "CHECK:预取那一行没有拿折过的 Role",
    ),
    (
        "旧签名在会话里复活（不看角色地拉）",
        HUB,
        lambda s: s.replace(PREFETCH, "scope.launch { runCatching { UnitConv.ensure(container.repo) } }", 1),
        "CHECK:没有旧签名残留",
    ),
    (
        "下单页改传常量角色",
        CREATE,
        lambda s: s.replace(SCREEN, 'UnitConv.ensure(container.repo, "driver")', 1),
        "CHECK:下单页传的是同步角色",
    ),
    (
        "商品页干脆不拉了",
        FORM,
        lambda s: s.replace(SCREEN, "", 1),
        "CHECK:在 android 里正好",
    ),
    (
        "后端放行司机（契约被放宽）",
        BUC,
        lambda s: s.replace("require_roles(UserRole.SHIPPER, UserRole.DISPATCHER)", "require_roles(UserRole.SHIPPER, UserRole.DISPATCHER, UserRole.DRIVER)", 1),
        "CHECK:后端的 UnitOwner 就是逐字那一条",
    ),
    (
        "删掉司机 403 那条用例",
        BTEST,
        lambda s: s.replace("def test_driver_has_no_access(", "def _test_driver_has_no_access(", 1),
        "CHECK:司机 403 的用例还在",
    ),
    (
        "那条用例的断言被改松（403 → 200）",
        BTEST,
        lambda s: s.replace("assert r.status_code == 403, r.text", "assert r.status_code == 200, r.text", 1),
        "CHECK:那条用例断的就是 403（读）",
    ),
    (
        "写路径那条断言也被改松（403 → 200）",
        BTEST,
        lambda s: s.replace("assert _create(client, token_driver).status_code == 403", "assert _create(client, token_driver).status_code == 200", 1),
        "CHECK:那条用例断的就是 403（写）",
    ),
    (
        "登记行里的文档链接被改掉",
        REG,
        lambda s: s.replace("](BUG-0008.md)", "](BUG-XXXX.md)", 1),
        "CHECK:登记表里有 BUG-0008",
    ),
    (
        "文档自己的 ID 与文件名不一致",
        DOC,
        lambda s: s.replace("**ID**：BUG-0008", "**ID**：BUG-XXXX", 1),
        "CHECK:文档的 ID 与文件名一致",
    ),
    (
        "单测里的反向断言被换成正向",
        KTEST,
        lambda s: s.replace('assertFalse(UnitConv.canRead("wholesaler"))', 'assertTrue(UnitConv.canRead("wholesaler"))', 1),
        "CHECK:单测断言批发商不能读",
    ),
    (
        "单测里的清单断言被放宽",
        KTEST,
        lambda s: s.replace('assertEquals(setOf("shipper", "dispatcher"), UnitConv.READ_ROLE_KEYS)', 'assertEquals(setOf("shipper", "dispatcher", "driver"), UnitConv.READ_ROLE_KEYS)', 1),
        "CHECK:单测断言清单等于后端那一份",
    ),
    (
        "canRead 恒真时，Android 单测自己会红（真跑一遍 gradle）",
        UC,
        lambda s: s.replace(CANREAD, "fun canRead(roleKey: String?): Boolean = true", 1),
        "GRADLE:testEmuDebugUnitTest",
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


def run_test(node: str) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, "-m", "pytest", node, "-q", "--no-header"],
        cwd=str(ROOT / "backend"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_judge() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(JUDGE)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def run_gradle() -> tuple[int, str]:
    p = subprocess.run(
        ["cmd", "/c", str(GRADLE), "-p", "android", ":app:testEmuDebugUnitTest"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_judge()
    if code != 0:
        print("❌ 前提不成立：源码完好时判据脚本就没过")
        print(out[-1500:])
        return 1
    code, out = run_test("tests/test_unit_conversions.py")
    if code != 0:
        print("❌ 前提不成立：源码完好时后端换算用例就没过")
        print(out[-1500:])
        return 1
    print("✅ 前提：源码完好时判据脚本与后端换算用例都是绿的")

    gradle_ran = False
    if any(n.startswith("GRADLE:") for *_rest, n in CASES):
        if not GRADLE.exists():
            print(f"❌ 找不到 gradle：{GRADLE}")
            return 1
        code, out = run_gradle()
        if code != 0:
            print("❌ 前提不成立：源码完好时 Android 单测就没过")
            print(out[-1500:])
            return 1
        print("✅ 前提：源码完好时 Android 单测也是绿的")

    touched = sorted({rel for _l, rel, _m, _n in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}
    crlfs = {rel: b"\r\n" in originals[rel] for rel in touched}

    for label, rel, mutate, node in CASES:
        path = ROOT / rel
        plain = originals[rel].decode("utf-8").replace("\r\n", "\n")
        mutated = mutate(plain)
        if mutated == plain:
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        try:
            write_src(path, mutated, crlfs[rel])
            if node.startswith("CHECK:"):
                jcode, jout = run_judge()
                expect = node.split(":", 1)[1]
                hit = jcode != 0 and any("[FAIL]" in ln and expect in ln for ln in jout.splitlines())
            elif node.startswith("GRADLE:"):
                gradle_ran = True
                gcode, _gout = run_gradle()
                hit = gcode != 0
            else:
                tcode, _tout = run_test(node)
                hit = tcode != 0
        finally:
            path.write_bytes(originals[rel])
        kind = "判据" if node.startswith("CHECK:") else ("Android 单测" if node.startswith("GRADLE:") else "回归测试")
        if hit:
            print(f"  [OK] {label} → {kind}报红")
        else:
            fails.append(f"{label}：注入之后**没有任何检查报红**（修复没有被钉住）")
            print(f"  [MISS] {label} → 全绿")

    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    if gradle_ran:
        print("⚠️  Android 单测结果目录刚被那条注入污染过 —— 提交前重跑一次 "
              "`_agent/gradle/gradle-8.9/bin/gradle.bat -p android :app:testEmuDebugUnitTest`，"
              "否则 `_tools/qa/_android_test_count.py` 会读到 failures>0。")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明 BUG-0008 的修复真的被钉住了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
