#!/usr/bin/env python3
"""_check_vehicle_attrs.py —— **车辆属性**（车身型式 → 能填哪些项）的静态判据。

用户 2026-09-27 要的是「给一辆车固定一个属性……**在创建车辆的时候就需要填相应的属性**。
**不同的车型会需要填的属性是不同的**」，并且「（车辆属性）**是要算钱的**……
主要的是**吨和方**这种即便（计量）单位」。属性清单他逐条批准过
（「属性清单可以啊，就可以就这样子」）。

## 为什么这一族要靠机器判据

这张表**横跨四份文件**：后端纯函数（真源）、数据库列的迁移、模型、以及安卓界面那份镜像。
写歪的后果全都**不报错**：

| 写歪的地方 | 表现（谁都不报错） |
|---|---|
| 模型加了列、迁移忘了加 | 本机（create_all）一切正常，**生产**老库上这一列根本不存在 |
| 迁移列宽与模型不一致 | 新库能存 8.0005、老库给你悄悄截成 8.000 |
| 安卓镜像与后端表不一致 | 界面画出一个后端不认的输入框：填了 → 保存被 400，而界面上看不出为什么 |
| 吨 / 方被挪出通用档 | "一车 = 多少方"对某几种车突然没有依据，而界面上只是少一个框 |
| PATCH 把"传了 attrs"写成 body.attrs is not None | **传空对象 = 全部清空**这个用法再也表达不出来 |
| 有人顺手往 vehicle_type 里加值 | 那是**计费口径**（resolve_billing_mode：挂车→按单计费、其余→固定工资）——**钱**会变 |

## 判据分五组
① 文件与接线 · ② 迁移↔模型逐列一致 · ③ 后端表↔安卓镜像逐项一致 ·
④ 语义（吨/方通用、整份替换、车型不被扩、这里不算钱）· ⑤ 数量下限（防"检查空转"）

用法：
    python _tools/qa/_check_vehicle_attrs.py            # 打印每一项；有红则非零退出
    python _tools/qa/_check_vehicle_attrs.py --check    # 同上（_check_all.py 两种都会跑）

⛔ 反向验证在 _tools/qa/_reverse_verify_vehicle_attrs.py：它逐条注入上面这张表里的
每一种写坏方式，**每一条都必须让这里变红**（不变红的判据等于没有判据）。

### R4-BOUNDARY-JUSTIFICATION

R4-BOUNDARY-JUSTIFICATION: 这一族**没法用边界消除**，因为它守的全是「**四份文件对同一件事的
说法不一致**」，而四份文件之间没有任何编译期或运行期的连接：

1. **后端纯函数 ↔ 迁移 ↔ 模型**：本机是 `create_all` 按模型建表、生产老库是 ALTER 出来的，
   两边不一致时**本机全绿、生产出事**（那一列在新库存在、老库不存在，或者列宽悄悄不同）。
   没有任何类型系统能跨"Python 类声明"与"SQL 字符串"做这件事。
2. **后端表 ↔ 安卓镜像**：界面要离线画表单，所以那张表必须编译进 App。
   两份都是"数据"，不是"代码"；不一致时两边各自都自洽，只有**用户**看得见
   （界面上画出一个后端不认的输入框：填了 → 保存被 400，而界面上看不出为什么）。
3. **计费口径不许被扩**：`vehicle_type` 与 `body_type` 是两件事，而它们在界面上长得很像，
   "顺手把 box 加进车型 chips"是一个**能编译、能运行、看起来更整齐**的动作 ——
   它的后果（`resolve_billing_mode` 里某些司机从固定工资变成按单计费）在类型上完全不可见。
4. **`PATCH` 的整份替换语义**：写成 `body.attrs is not None` 与写成
   `"attrs" in body.model_fields_set` 都编译、都能跑，"传空对象 = 全部清空"这个用法
   只是**静默失效**（用户清空属性会变成"什么都没发生"）。

唯一真正的边界是**当场核对这四份是不是还说得一样** —— 那就是这条判据本身。
它的牙齿是 `_tools/qa/_reverse_verify_vehicle_attrs.py`（25 条注入，每条都必须让它变红）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY_ATTRS = ROOT / "backend" / "app" / "services" / "vehicle_attrs.py"
MIGRATION = ROOT / "backend" / "app" / "migrations" / "010_vehicle_attrs.py"
MODEL = ROOT / "backend" / "app" / "models" / "vehicle.py"
SCHEMAS = ROOT / "backend" / "app" / "schemas" / "accounting_v2.py"
API = ROOT / "backend" / "app" / "api" / "v1" / "vehicles.py"
MODULES = ROOT / "backend" / "app" / "models" / "user.py"
KT_ATTRS = (
    ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
    / "ui" / "dispatcher" / "VehicleAttrs.kt"
)
KT_DTOS = (
    ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
    / "data" / "remote" / "dto" / "Dtos.kt"
)
KT_SCREEN = (
    ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
    / "ui" / "dispatcher" / "VehicleManageScreen.kt"
)

#: 判据条数下限。判据自己也会腐烂（文件改名、glob 写错），低于这个数说明它在空转。
MIN_RULES = 45

#: ⛔ 车型（计费口径）**只许有这几个值**。它被 resolve_billing_mode 用来决定
#: 「挂车→按单计费、其余→固定工资」——**那是钱**。往这里加值 = 让"箱式车按什么算钱"
#: 变成一个没人回答过的问题，而且答错了不报错。
FROZEN_VEHICLE_TYPES = {"small", "large", "trailer", ""}

#: 代码里**不许出现**的金额词汇（与 services/unit_conversion.py 那条同源：
#: 换算只改数量的显示，钱一个字节都不动）。这里同样：车辆属性只登记事实，不算钱。
MONEY_WORDS = ("price", "money", "amount", "total", "金额", "单价", "合价", "运费")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def code_only(src: str) -> str:
    """剥掉注释与文档字符串 —— **判据只许锚在代码上**。

    ⚠️ 这一条是本仓库反复踩的坑（_check_all.py 的说明里写着）：判据搜纯文本时会被
    **自己写的说明文字**满足。本文件尤其危险：模块头那段散文里就写着"这里不算钱"，
    而判据要断言的恰恰是**代码里**没有金额词汇。
    """
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"'''[\s\S]*?'''", "", src)
    return re.sub(r"^[ \t]*#.*$", "", src, flags=re.M)


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    passed: list[str] = []
    failed: list[str] = []

    def want(cond: bool, ok: str, bad: str) -> None:
        (passed if cond else failed).append(ok if cond else bad)

    # ============================================================ ① 文件与接线
    for p in (PY_ATTRS, MIGRATION, MODEL, SCHEMAS, API, KT_ATTRS, KT_DTOS, KT_SCREEN):
        want(p.exists(), f"存在 {p.relative_to(ROOT)}", f"⛔ 缺文件 {p.relative_to(ROOT)}")
    if failed:
        print("\n".join("  [FAIL] " + f for f in failed))
        return 1

    attrs_src = read(PY_ATTRS)
    model_src = read(MODEL)
    mig_src = read(MIGRATION)
    api_src = read(API)
    schema_src = read(SCHEMAS)
    kt_attrs = read(KT_ATTRS)
    dto_src = read(KT_DTOS)
    screen_src = read(KT_SCREEN)

    # 真源：直接 import 那个纯函数模块（判据读的就是运行时真的在用的那张表）
    sys.path.insert(0, str(ROOT / "backend"))
    try:
        from app.services import vehicle_attrs as va  # noqa: E402
    except Exception as e:                                        # pragma: no cover
        print(f"⛔ 导入 backend/app/services/vehicle_attrs.py 失败：{e}")
        return 1

    want("vehicle_attrs" in api_src, "API 层用了 services/vehicle_attrs（唯一真源）",
         "⛔ api/v1/vehicles.py 没有引用 services/vehicle_attrs —— 判据散了吗？")
    # ⚠️ 基类认「BaseModel 或 MoneyInput」两者之一：FEAT-0012 让 VehicleCreate / VehicleUpdate 继承
    #    `MoneyInput`（购置价要有上界 —— `_audit_money_fields.py` 只认「继承 MoneyInput」或「字段带 le=」）。
    #    本判据要守的是**字段声明** `attrs:` 还在，不是它们恰好继承 `BaseModel`。
    for name in ("VehicleCreate", "VehicleUpdate", "VehicleOut"):
        m = re.search(rf"class {name}\((?:BaseModel|MoneyInput)\):[\s\S]*?\n(?=class |\Z)", schema_src)
        body = m.group(0) if m else ""
        # ⚠️ 必须锚在**字段声明**上：搜子串的话，把 `attrs` 改名成 `attrs_removed` 也算"有"
        #    （反向验证第 16 条实测抓到过这个洞）。
        want(bool(body) and re.search(r"^\s+attrs\s*:", body, re.M) is not None,
             f"{name} 带 attrs", f"⛔ {name} 没有 attrs")
    # ⚠️ 数**出现次数**而不是"有没有出现过"：三个 DTO（Create / Update / Dto）都要有，
    #    只判"出现过"的话，漏掉其中两个也是绿的（反向验证第 17 条实测抓到的洞）。
    want(dto_src.count('@SerialName("body_type")') == 3
         and len(re.findall(r"val attrs\s*:", dto_src)) == 3,
         "安卓三个车辆 DTO 各自都带 body_type / attrs",
         "⛔ Dtos.kt 的车辆 DTO 缺字段（Create / Update / Dto 三处都要有——界面填了才发得出去）")
    want("VehicleDto(" in dto_src and "bodyLabel" in dto_src,
         "VehicleDto 带 bodyLabel（中文名由后端给）",
         "⛔ VehicleDto 没有 bodyLabel —— 客户端会自己 when(型式) 编一份叫法")

    # ============================================================ ② 迁移 ↔ 模型
    #
    # ⚠️ 这是本仓库最贵的一类漂移：**本机是 create_all 建的表**（按模型），
    # 生产老库是 ALTER 出来的（按迁移）。两边不一致时本机全绿、生产出事。
    model_cols = set(re.findall(r"^    ([a-z_]+): Mapped\[", model_src, re.M))
    mig_cols = set(re.findall(r'^\s*\("([a-z_]+)",', mig_src, re.M))
    want(bool(mig_cols), "迁移里解析出了列清单", "⛔ 没解析出 010_vehicle_attrs 的 COLUMNS")
    want(mig_cols <= model_cols,
         f"迁移加的列模型里都有（{len(mig_cols)} 列）",
         f"⛔ 迁移加了模型没有的列：{sorted(mig_cols - model_cols)}")
    field_keys = {f.key for f in va.FIELDS}
    want(field_keys <= mig_cols,
         "属性表里的每一项在迁移里都有列",
         f"⛔ 这些属性没有对应的库列：{sorted(field_keys - mig_cols)}")
    want("body_type" in mig_cols, "迁移加了 body_type", "⛔ 迁移没有加 body_type")
    for f in va.FIELDS:
        col = re.search(rf"^    {f.key}: Mapped\[[^\]]+\] = mapped_column\(([A-Za-z]+)", model_src, re.M)
        typ = col.group(1) if col else ""
        want(typ == ("Integer" if f.integer else "Numeric"),
             f"{f.key} 模型列类型={typ}",
             f"⛔ {f.key} 的模型列类型是 {typ}（整数项要 Integer、其余要 Numeric；⛔ 不许 Float）")
    # ⚠️ 必须剥注释：迁移的模块头里**写着**"不用 FLOAT"这句说明，直接搜纯文本会被自己满足。
    want("FLOAT" not in code_only(mig_src).upper().replace("NUMERIC", ""),
         "迁移里没有 FLOAT（浮点会让 8 变成 7.999999999999999）",
         "⛔ 迁移里出现了 FLOAT —— 吨/方要参与换算，不能用浮点存")

    # ============================================================ ③ 后端表 ↔ 安卓镜像
    kt_sets = {
        m.group(1): tuple(sorted(x for x in re.findall(r'"([a-z_]*)"', m.group(2))))
        for m in re.finditer(r"private val ([A-Z_]+) = setOf\(([^)]*)\)", kt_attrs)
    }
    want(len(kt_sets) >= 4, f"安卓镜像解析出 {len(kt_sets)} 个型式集合",
         "⛔ 没解析出 VehicleAttrs.kt 里的 setOf(...) 常量（写法变了？判据要跟着改）")
    kt_entries = list(re.finditer(
        r'VehicleAttrField\("([a-z_]+)", "([^"]+)", "([^"]+)", ([A-Z_]+)'
        r'(?:, (.+?))?\),\s*$',
        kt_attrs,
        re.M,
    ))
    want(len(kt_entries) == len(va.FIELDS),
         f"安卓镜像与后端表项数一致（{len(kt_entries)}）",
         f"⛔ 安卓镜像 {len(kt_entries)} 项 vs 后端 {len(va.FIELDS)} 项")

    for idx, (m, f) in enumerate(zip(kt_entries, va.FIELDS)):
        key, label, unit, setname, rest = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5) or ""
        want(key == f.key, f"{key} 键一致", f"⛔ 第 {idx + 1} 项键不一致：{key} vs {f.key}")
        want(label == f.label, f"{key} 通用名一致（{label}）",
             f"⛔ {key} 通用名不一致：{label} vs {f.label}")
        want(unit == f.unit, f"{key} 量纲一致（{unit}）",
             f"⛔ {key} 量纲不一致：{unit} vs {f.unit}")
        kt_bodies = set(kt_sets.get(setname, ()))
        want(kt_bodies == set(f.bodies),
             f"{key} 适用型式一致（{sorted(b for b in kt_bodies if b)}）",
             f"⛔ {key} 适用型式不一致：安卓 {sorted(kt_bodies)} vs 后端 {sorted(f.bodies)}")
        kt_per = dict(re.findall(r'"([a-z_]+)" to "([^"]+)"', rest))
        want(kt_per == dict(f.per_body), f"{key} 按型式的叫法一致",
             f"⛔ {key} 叫法不一致：安卓 {kt_per} vs 后端 {dict(f.per_body)}")
        want(("integer = true" in rest) == f.integer, f"{key} 整数标志一致",
             f"⛔ {key} 的 integer 标志两边不一致")

    kt_bodies = dict(re.findall(r'^\s*"([a-z]*)" to "([^"]+)",$', kt_attrs, re.M))
    want(set(kt_bodies) == set(va.BODY_TYPES),
         f"车身型式取值两边一致（{len(kt_bodies)} 个）",
         f"⛔ 车身型式取值不一致：安卓 {sorted(kt_bodies)} vs 后端 {sorted(va.BODY_TYPES)}")
    for b, cn in kt_bodies.items():
        want(va.BODY_LABELS.get(b) == cn, f"型式 {b or '(未设置)'} 的中文名一致（{cn}）",
             f"⛔ {b} 的中文名不一致：安卓 {cn} vs 后端 {va.BODY_LABELS.get(b)}")

    # ============================================================ ④ 语义
    want(va.CAPACITY_KEYS == ("load_tons", "volume_cubic"),
         "参与换算的两项就是载重(吨) / 容积(方)",
         f"⛔ CAPACITY_KEYS 被改成了 {va.CAPACITY_KEYS}")
    for b in va.BODY_TYPES:
        have = {f.key for f in va.fields_for(b)}
        want(set(va.CAPACITY_KEYS) <= have,
             f"型式 {b or '(未设置)'} 能填吨与方",
             f"⛔ 型式 {b} 填不了 {sorted(set(va.CAPACITY_KEYS) - have)} —— 那几种车的换算会失去依据")
    want(va.BODY_NONE in va.BODY_TYPES, "「未设置」是正式取值（老车不被迁移判成非法）",
         "⛔ BODY_TYPES 里没有空串 —— 老车会读不出来")

    api_code = code_only(api_src)
    want('"attrs" in body.model_fields_set' in api_code,
         "PATCH 用 model_fields_set 认「传了 attrs 没有」",
         '⛔ 没看到 "attrs" in body.model_fields_set —— 那"传空对象=全部清空"就表达不出来')
    want("body.attrs is not None" not in api_code,
         "没有退回 body.attrs is not None（那个坑会让清空变成什么都没发生）",
         "⛔ 出现了 body.attrs is not None —— 变回没传/传空分不清的老写法了")

    m = re.search(r"_VEHICLE_TYPES = \(([^)]*)\)", api_code)
    want(m is not None, "还认得 _VEHICLE_TYPES", "⛔ api/v1/vehicles.py 里没有 _VEHICLE_TYPES 了")
    if m:
        vals = {v.strip().strip('"').strip("'") for v in m.group(1).split(",")}
        want(vals == FROZEN_VEHICLE_TYPES,
             "车型取值仍是 小货车/大货车/挂车/未设置（计费口径，一个字不扩）",
             f"⛔ 车型取值被改了：{sorted(vals)} —— 它是 resolve_billing_mode 的输入，**那是钱**")
    # 钱的另一头：resolve_billing_mode 的挂车分支必须还在（谁顺手改了它，这条会红）
    user_src = code_only(read(MODULES))
    want('vehicle_type == "trailer"' in user_src,
         "resolve_billing_mode 的挂车分支还在（那是钱）",
         "⛔ users.py 里 resolve_billing_mode 的挂车判断没了/被改了")
    kt_types = re.search(r"internal val VEHICLE_TYPES = listOf\(([^)]*)\)", screen_src)
    want(kt_types is not None and "box" not in (kt_types.group(1) if kt_types else ""),
         "安卓的车型 chips 也没有被塞进车身型式",
         "⛔ 安卓 VEHICLE_TYPES 里出现了 box/flat/dump —— 车型与车身型式被合并了")

    body_code = code_only(attrs_src)
    hits = sorted({w for w in MONEY_WORDS if w in body_code})
    want(not hits,
         "vehicle_attrs.py 的代码里没有任何金额词汇",
         f"⛔ vehicle_attrs.py 的代码里出现了 {hits} —— 车辆属性只登记事实，换算那一环是 FEAT-0005")

    want("attrsFor(vm.draftBody)" in screen_src,
         "界面按车身型式长出属性输入项",
         "⛔ VehicleManageScreen 没有按型式过滤属性（所有型式会看到同一张表）")
    want("capacityText(v.attrs)" in screen_src,
         "卡片上能装多少那一行走 capacityText（共享的唯一一份拼法）",
         "⛔ 卡片自己拼了一份载重/容积文字")

    # ============================================================ ⑤ 数量下限
    n = len(passed) + len(failed)
    want(n >= MIN_RULES,
         f"判据条数 {n} ≥ {MIN_RULES}（没有空转）",
         f"⛔ 只认出 {n} 条判据（下限 {MIN_RULES}）—— 检查正在空转")

    print(f"\n车辆属性判据：{len(passed)} 项通过 / {len(failed)} 项失败\n")
    for ok in passed:
        print(f"  [OK]   {ok}")
    for bad in failed:
        print(f"  [FAIL] {bad}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
