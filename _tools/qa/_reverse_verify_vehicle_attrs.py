#!/usr/bin/env python3
"""_reverse_verify_vehicle_attrs.py —— **反向验证**：逐条注入"写坏车辆属性表"的方式，
看 _tools/qa/_check_vehicle_attrs.py 是不是**真的会红**。

## 为什么必须有这一份

本项目 §15 的原话：「**永远绿的检查 = 没有检查**」。判据写完之后，唯一能证明它没在空转的办法
就是**把它要防的那种坏情况真的做出来一次**，看它是否当场变红。

这一族尤其需要：车辆属性横跨**四份文件**（后端纯函数 / 迁移 / 模型 / 安卓镜像），
而写歪的后果全都**不报错** —— 界面照画、接口照收、本机全绿，只有生产老库或某几种车型上
"一车 = 多少方"悄悄失去依据。

## 注入点选在哪里（一条纪律）

⛔ 注入要选在**旧检查不看的地方**：比如"迁移里加了一个模型没有的列"这种漂移，
只查文本存在性的判据是抓不到的。这里的每一个用例都对应 _check_vehicle_attrs.py
里的一条**具体断言**，并且把那条断言的原文写在 line 上，方便对读。

## 安全

⚠️ 每个用例**先读字节进内存、改、跑、再把原字节写回**，并且最后校验哈希一致。
⛔ 不用 `git checkout --` 还原（那会把工作区里未提交的改动一起抹掉，本仓库实测栽过）。

用法：
    python _tools/qa/_reverse_verify_vehicle_attrs.py
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = "_tools/qa/_check_vehicle_attrs.py"

#: 注入用例：(说明, 目标文件, 原文, 改成, 期望看到的那句判据)
#: ⚠️ 目标文件路径**必须写成仓库相对完整路径的字面量** ——
#:    `_tools/ai/_reverse_verify_all.py` 的 --for / --changed 靠"源码里有没有这个路径"来选子集，
#:    拼出来的路径选不中（那份脚本的注释里写着这个坑）。
#: 最后一项是**可接受的失败文案**（元组）：红在哪一条兄弟判据上都算数，
#: 因为写坏一处经常同时踩响两条（比如把 integer 标志改掉，列类型那条也会跟着红）。
CASES: list[tuple[str, str, str, str, tuple[str, ...] | str]] = [
    # ---------------- 后端属性表（真源）----------------
    (
        "把载重(吨)从通用档挪到只有箱式车能填",
        "backend/app/services/vehicle_attrs.py",
        'AttrField("load_tons", "载重", "吨", _d("200"), False, _ALL),',
        'AttrField("load_tons", "载重", "吨", _d("200"), False, (BODY_BOX,)),',
        "适用型式不一致",
    ),
    (
        "把容积(方)的通用名改成「容量」（界面上会与后端叫法分裂）",
        "backend/app/services/vehicle_attrs.py",
        '        "volume_cubic", "容积", "方", _d("500"), False, _ALL,',
        '        "volume_cubic", "容量", "方", _d("500"), False, _ALL,',
        ("通用名不一致",),
    ),
    (
        "往「参与换算的两项」里再塞一个（吨/方的范围被悄悄放宽）",
        "backend/app/services/vehicle_attrs.py",
        'CAPACITY_KEYS: tuple[str, ...] = ("load_tons", "volume_cubic")',
        'CAPACITY_KEYS: tuple[str, ...] = ("load_tons", "volume_cubic", "height_m")',
        "CAPACITY_KEYS 被改成了",
    ),
    (
        "轴数不再要求整数（存得进 3.5 个轴）",
        "backend/app/services/vehicle_attrs.py",
        'AttrField("axle_count", "轴数", "个", _d("10"), True, (BODY_TRAILER,)),',
        'AttrField("axle_count", "轴数", "个", _d("10"), False, (BODY_TRAILER,)),',
        ("integer 标志两边不一致", "的模型列类型是"),
    ),
    (
        "平板车也能填货厢高（需求方给的清单里没有「台面高」）",
        "backend/app/services/vehicle_attrs.py",
        "_HAS_BED_HEIGHT = (BODY_BOX, BODY_DUMP)",
        "_HAS_BED_HEIGHT = _HAS_BED",
        "适用型式不一致",
    ),
    (
        "「未设置」不再是合法取值（老车会被判成非法）",
        "backend/app/services/vehicle_attrs.py",
        'BODY_TYPES: tuple[str, ...] = (BODY_NONE, BODY_BOX, BODY_FLAT, BODY_DUMP, BODY_TRAILER)',
        'BODY_TYPES: tuple[str, ...] = (BODY_BOX, BODY_FLAT, BODY_DUMP, BODY_TRAILER)',
        ("BODY_TYPES 里没有空串", "车身型式取值不一致"),
    ),
    (
        "在属性判据里算起了钱（车辆属性只登记事实）",
        "backend/app/services/vehicle_attrs.py",
        "def format_value(value: Decimal) -> str:",
        "def format_value(value: Decimal) -> str:\n    total_price = Decimal(0)  # noqa: F841",
        ("的代码里出现了",),
    ),
    # ---------------- 迁移 ↔ 模型 ----------------
    (
        "迁移把 volume_cubic 写成了 FLOAT（浮点会让 8 变成 7.999999999999999）",
        "backend/app/migrations/010_vehicle_attrs.py",
        '("volume_cubic", "volume_cubic NUMERIC(12, 3) NULL"),',
        '("volume_cubic", "volume_cubic FLOAT NULL"),',
        "不能用浮点存",
    ),
    (
        "迁移漏了 load_tons 这一列（老库上这个属性根本不存在）",
        "backend/app/migrations/010_vehicle_attrs.py",
        '    ("load_tons", "load_tons NUMERIC(12, 3) NULL"),\n',
        "",
        "没有对应的库列",
    ),
    (
        "迁移漏了 body_type（老库上的车全是「没有型式」，界面上一片未设置）",
        "backend/app/migrations/010_vehicle_attrs.py",
        '("body_type", "body_type VARCHAR(16)',
        '("body_type_x", "body_type VARCHAR(16)',
        "迁移没有加 body_type",
    ),
    (
        "模型漏了 volume_cubic 列（本机 create_all 会少一列，迁移却加了）",
        "backend/app/models/vehicle.py",
        "    volume_cubic: Mapped[Decimal | None] = mapped_column(Numeric(12, 3), nullable=True)\n",
        "",
        "迁移加了模型没有的列",
    ),
    (
        "模型把 axle_count 写成 Numeric（能存 3.5 个轴）",
        "backend/app/models/vehicle.py",
        "    axle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)",
        "    axle_count: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)",
        "的模型列类型是",
    ),
    # ---------------- API 语义 ----------------
    (
        "PATCH 退回 body.attrs is not None（「传空对象=全部清空」再也表达不出来）",
        "backend/app/api/v1/vehicles.py",
        '    raw_attrs = body.attrs if "attrs" in body.model_fields_set else vattrs.attrs_of(v)',
        "    raw_attrs = body.attrs if body.attrs is not None else vattrs.attrs_of(v)",
        "body.attrs is not None",
    ),
    (
        "往车型（计费口径）里塞一个 box —— 那是 resolve_billing_mode 的输入，是钱",
        "backend/app/api/v1/vehicles.py",
        '_VEHICLE_TYPES = ("small", "large", "trailer", "")',
        '_VEHICLE_TYPES = ("small", "large", "trailer", "box", "")',
        "车型取值被改了",
    ),
    (
        "改掉 resolve_billing_mode 的挂车分支（钱的口径被顺手改掉）",
        "backend/app/models/user.py",
        'return "PIECE" if vehicle_type == "trailer" else "SALARY"',
        'return "PIECE" if vehicle_type == "large" else "SALARY"',
        ("resolve_billing_mode 的挂车判断",),
    ),
    (
        "出参里去掉 VehicleOut.attrs（界面永远拿不到属性）",
        "backend/app/schemas/accounting_v2.py",
        "    attrs: dict[str, str] = Field(default_factory=dict)",
        "    attrs_removed: dict[str, str] = Field(default_factory=dict)",
        "VehicleOut 没有 attrs",
    ),
    (
        "安卓 DTO 去掉 body_type（界面填了也发不出去）",
        "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt",
        '@SerialName("body_type") val bodyType: String = "",',
        '     */\n    @SerialName("body_type_x") val bodyType: String = "",',
        ("Dtos.kt 的车辆 DTO 缺字段",),
    ),
    # ---------------- 安卓镜像 ----------------
    (
        "安卓镜像把「车高」的量纲写成厘米（4 与 400 在界面上都像是对的）",
        "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleAttrs.kt",
        'VehicleAttrField("height_m", "车高", "米", ALL_BODIES),',
        'VehicleAttrField("height_m", "车高", "厘米", ALL_BODIES),',
        "量纲不一致",
    ),
    (
        "安卓镜像把「车斗长」写成「车厢长」（两种车的叫法混了）",
        "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleAttrs.kt",
        'mapOf("box" to "车厢长", "flat" to "台面长", "dump" to "车斗长")',
        'mapOf("box" to "车厢长", "flat" to "台面长", "dump" to "车厢长")',
        "叫法不一致",
    ),
    (
        "安卓镜像让平板车也能填货厢高",
        "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleAttrs.kt",
        "private val HAS_BED_HEIGHT = setOf(\"box\", \"dump\")",
        "private val HAS_BED_HEIGHT = setOf(\"box\", \"flat\", \"dump\")",
        "适用型式不一致",
    ),
    (
        "安卓镜像把轴数开放给所有车",
        "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleAttrs.kt",
        'private val TRAILER_ONLY = setOf("trailer")',
        'private val TRAILER_ONLY = setOf("trailer", "box")',
        "适用型式不一致",
    ),
    (
        "安卓 chips 把自卸车写成「倾卸车」（同一件事两个叫法）",
        "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleAttrs.kt",
        '    "dump" to "自卸车",',
        '    "dump" to "倾卸车",',
        "的中文名一致",
    ),
    (
        "安卓车型 chips 里塞进车身型式（两件事被合并）",
        "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleManageScreen.kt",
        'internal val VEHICLE_TYPES = listOf("trailer" to "挂车", "large" to "大货车", "small" to "小货车")',
        'internal val VEHICLE_TYPES = listOf("trailer" to "挂车", "large" to "大货车", "small" to "小货车", "box" to "箱式车")',
        ("安卓 VEHICLE_TYPES 里出现了",),
    ),
    (
        "界面不再按车身型式长属性（所有型式看到同一张表）",
        "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleManageScreen.kt",
        "attrsFor(vm.draftBody).forEach { f ->",
        "VEHICLE_ATTR_FIELDS.forEach { f ->",
        ("没有按型式过滤属性",),
    ),
    (
        "卡片自己拼一份载重/容积（绕开共享的 capacityText）",
        "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/VehicleManageScreen.kt",
        "val capacity = capacityText(v.attrs)",
        'val capacity = (v.attrs["load_tons"] ?: "") + (v.attrs["volume_cubic"] ?: "")',
        ("卡片自己拼了一份载重/容积文字",),
    ),
]


def run_checker() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, CHECKER],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    # ⓪ 对照组：**没注入时必须绿** —— 否则下面每一条"红了"都可能是别的原因。
    code, out = run_checker()
    if code != 0:
        print("⛔ 对照组失败：没有注入时判据就是红的，先把它修绿再谈反向验证。")
        print(out[-2000:])
        return 1
    print("[对照] 未注入 → 判据绿（说明下面的红都来自注入）")

    bad: list[str] = []
    for i, (label, rel, old, new, expected) in enumerate(CASES, 1):
        path = ROOT / rel
        if not path.exists():
            bad.append(f"{label} —— 目标文件不存在：{rel}")
            print(f"  [{i}] [FAIL] {label} —— 目标文件不存在：{rel}")
            continue
        original = path.read_bytes()
        before = sha(original)
        text = original.decode("utf-8")
        n_hits = text.count(old)
        if n_hits < 1:
            bad.append(f"{label} —— 锚点在 {rel} 里一次都没出现（判据/代码改名了？）")
            print(f"  [{i}] [FAIL] {label} —— 锚点出现 0 次，注入不了")
            continue
        try:
            # ⚠️ 出现多次时**全部替换**：有的判据断言的是"每个 DTO 各自都有"，
            #    只改一处它仍然绿（那就证明不了判据在守什么）。改了几处会打出来。
            path.write_bytes(text.replace(old, new).encode("utf-8"))
            code, out = run_checker()
        finally:
            path.write_bytes(original)
        after = sha(path.read_bytes())
        if after != before:
            bad.append(f"{label} —— ⛔ 文件没还原干净（{rel}）")
            print(f"  [{i}] [FAIL] {label} —— ⛔ 文件没还原（{before} → {after}）")
            continue
        if code == 0:
            bad.append(f"{label} —— 判据**没红**（这条判据是假的）")
            print(f"  [{i}] [FAIL] {label} —— 判据没红！")
            continue
        wants = (expected,) if isinstance(expected, str) else expected
        hit = any(w in out for w in wants)
        mark = "OK" if hit else "WARN"
        print(f"  [{i}] [{mark}] {label} → 判据变红" + (f"（注入 {n_hits} 处）" if n_hits > 1 else "") + ("" if hit else f"（但没看到期望的那几句：{list(wants)}）"))
        if not hit:
            bad.append(f"{label} —— 红了，但不是因为期望的那条判据（{list(wants)}）")

    total = len(CASES)
    print(f"\n反向验证：{total - len(bad)}/{total} 条注入都让判据变红")
    for b in bad:
        print("  ⛔ " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
