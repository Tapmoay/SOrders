# -*- coding: utf-8 -*-
"""单位换算的预取必须**按角色**发（2026-10-03 BUG-0008）—— 机器判据。

## 这条是怎么来的

三端真机 E2E 走查报告（`docs/E2E_WALKTHROUGH_REPORT_20261003.md`）§5.3 里躺着一条长期噪声：

    GET /api/v1/unit-conversions → 403

2026-10-03 用户点名要它消失：「那个 403 的……必须解决，不许留在日志里。」

根因不是「谁多写了一次请求」，而是**一次注定被拒绝的请求被无条件发出**：
换算表只有**货主与派单员**能读（`backend/app/api/v1/unit_conversions.py` 的
`UnitOwner = require_roles(UserRole.SHIPPER, UserRole.DISPATCHER)`），而 App 的 `RealtimeHub`
在**会话一建立**时不分角色地拉一次 —— 司机（以及后端确实存在的批发商）每次登录/恢复都换回一条 403。
失败还是**静默**的（`UnitConv.refresh` 把异常吞掉、界面照旧只显示原单位），
所以这件事在页面上永远看不出来，只有后端日志一直在响。

## 为什么必须有机器的判据

修法是把「谁能拉」变成一道**编译期必答**的门：`ensure(repo, roleKey: String?)` 的第一行就是
`if (!canRead(roleKey)) return`，三个调用点各传自己的角色。这三句都是结构性的 ——
谁把门删掉、谁把 `driver` 加进 `READ_ROLE_KEYS`、谁在某个页面改传一个常量角色，页面上都**看不出来**
（顶多多一条 403），只有翻日志才发现噪声又回来了。还有一条更隐蔽的：后端角色与 App 的角色
**不是同一份清单**（App 的 `Role` 枚举把不认识的 key 折成 SHIPPER，而后端有 `wholesaler`）——
所以 §一 必须把两边的清单**放在一起对**，任何一边单独看都是合法的。

R4-BOUNDARY-JUSTIFICATION: **为什么代码边界解决不了这件事。**
（⛔ 标记里必须是 **ASCII 冒号**：`_check_r3_constraints.py::probe_checker_budget` 逐字认
`R3-BOUNDARY-JUSTIFICATION:` / `R4-BOUNDARY-JUSTIFICATION:` —— BUG-0007 那一轮写成了全角「：」，
提交之后全量静检当场翻红。）

「App 问的角色与后端放行的角色是同一批」不是**任何单个文件**的属性：Kotlin 那份 `READ_ROLE_KEYS`
自己看没毛病（就是两个字符串），后端 `UnitOwner` 自己看也没毛病（就是 `require_roles` 两个角色）——
**只有把两边的清单并排放**才知道 App 会不会去问一个后端必然拒绝的问题。类型标注也挡不住：
`roleKey: String?` 什么都能传，`null` 也合法。
**反向破坏用例**：`_tools/qa/_reverse_verify_unit_conv_prefetch_role.py` 逐条把门拆掉
（门改 `if (false) return`、`READ_ROLE_KEYS` 加 `driver` / 去掉 `dispatcher`、RealtimeHub 改传 `null`
或改传折过的 `Role.fromKey(s.role).key`、某屏改传常量 `"driver"`、后端 `require_roles` 加 `DRIVER`、
删掉司机 403 用例、删登记行、文档改 ID、单测删断言），每条都要求本判据报红，跑完逐字节还原。
**静默空转保护**：本判据只读源码，锚点少一个就当场报红（§零 先证明每个文件都读到了、正文长度
不达标即红），**不做**「找不到就跳过」的软处理；判词一律钉在**具体那一行写法**上。

用法：
    python _tools/qa/_check_unit_conv_prefetch_role.py
    python _tools/qa/_check_unit_conv_prefetch_role.py --list
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))

from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "android/app/src"
UC = SRC / "main/java/com/tapmoay/sorders/ui/common/UnitConverts.kt"
HUB = SRC / "main/java/com/tapmoay/sorders/core/RealtimeHub.kt"
CREATE = SRC / "main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt"
FORM = SRC / "main/java/com/tapmoay/sorders/ui/dispatcher/ProductFormScreen.kt"
KTEST = SRC / "test/java/com/tapmoay/sorders/ui/common/UnitConvAccessTest.kt"
BUC = ROOT / "backend/app/api/v1/unit_conversions.py"
BTEST = ROOT / "backend/tests/test_unit_conversions.py"
DOC = ROOT / "docs/changes/BUG-0008.md"
REGISTRY = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"

#: 预取调用点的条数（定义那处不算）—— 少一处 = 某个页面再也拿不到换算，多一处 = 又多一条 403。
CALL_SITES = 3

SECTIONS = [
    "§零 现场（先证明读到了东西）",
    "§一 两边的角色清单逐字一致",
    "§二 门在唯一入口里，且在最前面",
    "§三 三个调用点各传自己的角色",
    "§四 后端契约没有被放宽",
    "§五 单测钉住这份清单",
    "§六 登记与文档",
]


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def kt_code(src: str) -> str:
    """剥 Kotlin 的散文（块注释 + 整行 `//`）：判据只许锚在代码上。

    ⚠️ 教训（BUG-0006 判据的第一条假阳性）：函数体里的一句注释就能把纯子串判断喂饱 ——
    而这次的门旁边正好写着「司机每次登录都会换回一条 403」这种说明句。
    """
    out = re.sub(r"/\*(?:.|\n)*?\*/", "", src)
    return "\n".join(ln for ln in out.splitlines() if not ln.strip().startswith("//"))


def py_code(src: str) -> str:
    """剥 Python 的散文（三引号块 + 整行 `#` 注释）。"""
    out = re.sub(r'"""(?:.|\n)*?"""', "", src)
    out = re.sub(r"'''(?:.|\n)*?'''", "", out)
    return "\n".join(ln for ln in out.splitlines() if not ln.strip().startswith("#"))


def kt_block(src: str, needle: str) -> str:
    """取 Kotlin 里从 needle 开始的一小段（到下一个 4 空格缩进的 `}` 为止）—— 够用即可。"""
    i = src.find(needle)
    if i < 0:
        return ""
    j = src.find("\n    }\n", i)
    return src[i : j + 6] if j > 0 else src[i:]


def kt_sources() -> dict[str, str]:
    """android/app/src 下所有 .kt 的原文（按相对路径索引）—— 「有没有第四处调用」只能这样查。"""
    out: dict[str, str] = {}
    for p in sorted(SRC.rglob("*.kt")):
        out[str(p.relative_to(ROOT)).replace("\\", "/")] = p.read_text(encoding="utf-8", errors="replace")
    return out


class Checker:
    def __init__(self) -> None:
        self.fails = 0
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails += 1
            print(f"  [FAIL] {label}" + (f"\n         → {detail}" if detail else ""))

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {self.fails} 项")
        return 1 if self.fails else 0


def section(title: str) -> None:
    print()
    print(f"-- {title} --")


def main() -> int:
    if "--list" in sys.argv[1:]:
        print("本判据的分组（逐条判定，任一红即整体退 1）：")
        for s in SECTIONS:
            print("  - " + s)
        return 0
    if refuse_if_injecting("单位换算预取的角色门"):
        return 1

    c = Checker()
    uc = kt_code(read(UC))
    hub = kt_code(read(HUB))
    create = kt_code(read(CREATE))
    form = kt_code(read(FORM))
    ktest = kt_code(read(KTEST))
    buc = py_code(read(BUC))
    btest = py_code(read(BTEST))
    doc = read(DOC)
    reg = read(REGISTRY)
    claim = read(CLAIM)

    section(SECTIONS[0])
    c.ok("单位换算缓存 UnitConverts.kt 读到了（> 200 字符）", len(uc) > 200, f"只有 {len(uc)} 字符")
    c.ok("会话持有者 RealtimeHub.kt 读到了（> 200 字符）", len(hub) > 200, f"只有 {len(hub)} 字符")
    c.ok("下单页 OrderCreateScreen.kt 读到了（> 200 字符）", len(create) > 200, f"只有 {len(create)} 字符")
    c.ok("商品页 ProductFormScreen.kt 读到了（> 200 字符）", len(form) > 200, f"只有 {len(form)} 字符")
    c.ok("单测 UnitConvAccessTest.kt 读到了（> 200 字符）", len(ktest) > 200, f"只有 {len(ktest)} 字符")
    c.ok("后端 unit_conversions.py 读到了（> 200 字符）", len(buc) > 200, f"只有 {len(buc)} 字符")
    c.ok("后端 test_unit_conversions.py 读到了（> 200 字符）", len(btest) > 200, f"只有 {len(btest)} 字符")
    sources = kt_sources()
    c.ok("android/app/src 下扫到了 .kt（> 100 个）", len(sources) > 100, f"只有 {len(sources)} 个")

    section(SECTIONS[1])
    KT_LINE = 'val READ_ROLE_KEYS: Set<String> = setOf("shipper", "dispatcher")'
    BE_LINE = "require_roles(UserRole.SHIPPER, UserRole.DISPATCHER)"
    c.ok("Kotlin 的 READ_ROLE_KEYS 就是逐字那一行", KT_LINE in uc, "角色清单被改过（改角色必须同时改后端与判据）")
    c.ok("后端的 UnitOwner 就是逐字那一条", BE_LINE in buc, "后端放行的角色被改过")
    mk = re.search(r'READ_ROLE_KEYS: Set<String> = setOf\(([^)]*)\)', uc)
    kt_keys = sorted(re.findall(r'"([a-z]+)"', mk.group(1))) if mk else []
    mb = re.search(r"UnitOwner = Annotated\[User, Depends\(require_roles\(([^)]*)\)\)\]", buc)
    be_keys = sorted(x.strip().split(".")[-1].lower() for x in mb.group(1).split(",")) if mb else []
    c.ok("两边解析出来的角色 key 完全相同", bool(kt_keys) and kt_keys == be_keys, f"Kotlin={kt_keys} 后端={be_keys}")
    c.ok("两边就是货主 + 派单员那两个", kt_keys == ["dispatcher", "shipper"], f"Kotlin={kt_keys}")
    c.ok("Kotlin 里没有批发商这一格（后端会拒绝它）", "wholesaler" not in uc, "批发商不在后端白名单里，加进来就是一条 403")

    section(SECTIONS[2])
    ens = kt_block(uc, "suspend fun ensure(")
    c.ok("ensure 的签名带必填的 roleKey", "suspend fun ensure(repo: AppRepository, roleKey: String?)" in uc, "签名被打回不带角色的老样子")
    c.ok("门就是 if (!canRead(roleKey)) return 这一行", "if (!canRead(roleKey)) return" in ens, "门不在了")
    p_gate = ens.find("if (!canRead(roleKey)) return")
    p_loaded = ens.find("if (loaded) return")
    c.ok("门排在 loaded 短路之前（先判角色、再判拉过没）", 0 <= p_gate < p_loaded, f"门在 {p_gate}、loaded 在 {p_loaded}")
    c.ok("canRead 的实现就是那一行", "fun canRead(roleKey: String?): Boolean = roleKey != null && roleKey in READ_ROLE_KEYS" in uc, "canRead 被改松了")
    c.ok("拉取仍然只有 refresh 一处、失败静默", "runCatching { repo.unitConversions() }.onSuccess { accept(it) }" in uc, "换算不该在失败时吓到界面")
    c.ok("ensure 体内不自己拉（只调 refresh）", ens.count("repo.unitConversions()") == 0, "绕过 refresh 就会绕开「失败不清空」这条")

    section(SECTIONS[3])
    sites = [rel for rel, src in sources.items() if "UnitConv.ensure(" in src]
    c.ok(f"UnitConv.ensure( 在 android 里正好 {CALL_SITES} 处", len(sites) == CALL_SITES, "、".join(sites))
    c.ok("会话建立时传的是**会话里的**角色 key s.role", "scope.launch { runCatching { UnitConv.ensure(container.repo, s.role) } }" in hub, "预取点的角色来源被换了")
    c.ok("RealtimeHub 拿得到会话里的角色", "s.role" in hub, "没有 s.role 就说明它改从别处取角色了")
    c.ok("下单页传的是同步角色 cachedRole()", "UnitConv.ensure(container.repo, container.tokenStore.cachedRole())" in create, "下单页的角色来源被换了")
    c.ok("商品页传的是同步角色 cachedRole()", "UnitConv.ensure(container.repo, container.tokenStore.cachedRole())" in form, "商品页的角色来源被换了")
    c.ok("没有旧签名残留（不带角色的调用）", all("UnitConv.ensure(container.repo)" not in src for src in sources.values()), "旧调用漏在某个文件里 = 司机照样 403")
    hub_ensure = next((ln for ln in hub.splitlines() if "UnitConv.ensure(" in ln), "")
    c.ok("预取那一行没有拿折过的 Role 当参数", hub_ensure != "" and "Role." not in hub_ensure, hub_ensure.strip())

    section(SECTIONS[4])
    c.ok("UnitOwner 仍是货主 + 派单员", BE_LINE in buc, "后端契约被放宽了")
    c.ok("require_roles 里没有司机", "UserRole.DRIVER" not in buc, "司机不该能读这张表")
    c.ok("列表端点还在", '@router.get("", response_model=list[UnitConversionOut])' in buc, "端点被改名/删掉了")
    c.ok("司机 403 的用例还在（契约没被放宽）", "def test_driver_has_no_access(" in btest, "用例被删/改名 = 契约失去守卫")
    c.ok("那条用例断的就是 403（读）", "assert r.status_code == 403, r.text" in btest, "读路径的断言被改松")
    c.ok("那条用例断的就是 403（写）", "assert _create(client, token_driver).status_code == 403" in btest, "写路径的断言被改松")
    c.ok("货主与派单员共用的用例还在", "def test_conversions_are_shared_between_roles(" in btest, "共用那条被删了")

    section(SECTIONS[5])
    c.ok("单测文件在", len(ktest) > 200, "没写单测 = 这份清单没人钉")
    c.ok("单测断言货主能读", 'assertTrue(UnitConv.canRead("shipper"))' in ktest, "少了正向")
    c.ok("单测断言派单员能读", 'assertTrue(UnitConv.canRead("dispatcher"))' in ktest, "少了代下单那个角色")
    c.ok("单测断言司机不能读", 'assertFalse(UnitConv.canRead("driver"))' in ktest, "少了反向")
    c.ok("单测断言批发商不能读（Role 折过也拦得住）", 'assertFalse(UnitConv.canRead("wholesaler"))' in ktest, "少了折角色那一格")
    c.ok("单测断言 null / 空串不能读", 'assertFalse(UnitConv.canRead(null))' in ktest and 'assertFalse(UnitConv.canRead(""))' in ktest, "没关住空角色")
    c.ok("单测断言清单等于后端那一份", 'assertEquals(setOf("shipper", "dispatcher"), UnitConv.READ_ROLE_KEYS)' in ktest, "清单相等没被钉")

    section(SECTIONS[6])
    c.ok("登记表里有 BUG-0008 这一行", "](BUG-0008.md)" in reg, "登记表没加行")
    c.ok("文档存在且字数够（> 1500）", len(doc) > 1500, f"只有 {len(doc)} 字符")
    missing = [x for x in "①②③④⑤⑥⑦⑧⑨" if f"## {x}" not in doc]
    c.ok("文档九节齐全", not missing, "缺：" + "".join(missing))
    c.ok("文档的 ID 与文件名一致", "**ID**：BUG-0008" in doc, "内文 ID 对不上文件名")
    c.ok("认领页里有这次的声明块", "BUG-0008" in claim, "AI_WORK_CLAIM.md 没记这一笔")

    return c.report("单位换算预取的按角色门（BUG-0008）")


if __name__ == "__main__":
    sys.exit(main())
