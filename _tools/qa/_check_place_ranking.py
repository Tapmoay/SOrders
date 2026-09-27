#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_place_ranking.py —— **共享地点列表的距离分档排序**（FEAT-0002）的判据。

### 用户定的规则（2026-09-27）

> 「匹配规则优先的是根据它的位置……小于 1 米、小于 10 米、小于 50 米、小于 100 米之内的
>  会进行匹配，而且优先是从小到大，但是 100 米以外的就不会优先匹配了。」

⇒ `≤1 / ≤10 / ≤50 / ≤100` 四档从小到大优先，`>100 米不参与优先`。
⛔ 需求方同时拍板（Q3=A）：**只排序，不合并**。

### 这一条最容易走样的地方（所以要有机器判据）

"排序半径"和"合并半径"是**两个数字**，都住在
`backend/app/services/place_service.py` 里，而且**曾经被混过一次**
（模块开头那段注释就是为那次写的："它是**合并**半径，不是**搜索**半径"）。
混掉的后果不是报错，是**悄悄把隔壁那家店并掉**：两条本来分开的地点被合成了同一条，
用户看到的地址是别人的。

所以本判据盯四件事：

| # | 盯什么 |
| --- | --- |
| 1 | 四个档位的边界**就是** 1 / 10 / 50 / 100（含边界取小档），>100 不优先 |
| 2 | ⛔ **合并半径一个字没动**（`MERGE_METERS = 1` / `SAME_NAME_METERS = 30`）—— Q3=A 的机器形态 |
| 3 | **没有坐标的行不许当 0 米**（否则它们会跑到最前面，看起来像"就在我附近"） |
| 4 | 排序那一段**只用** `_bbox` + `haversine_m`，⛔ 不在 SQL 里写距离公式；且分页语义（`finish_page`）没丢 |

### ⛔ 它证不了什么

- 它证不了**端到端**的顺序对不对（那要跑 `backend/tests/test_place_ranking.py`
  或真机看列表）——这里管的是"规则没被改坏"，不是"这一屏排得对"。
- 它**不重跑**真机/真后端；那些是各自那份证据的事。

### R3-BOUNDARY-JUSTIFICATION

R3-BOUNDARY-JUSTIFICATION: 这条**没法用边界消除** —— 它守的是"**两个数字不许混**"，
而那两个数字是**同一种类型、同一个文件、名字都带 METERS** 的常量。
没有任何类型系统能表达"这一个用于合并、那一个用于排序"。
已经混过一次（注释里留着现场），再混一次的表现仍然是"不报错、只是把别人的店并掉"。
唯一真正的边界是**当场核对它们的取值** —— 那就是这条判据本身。

用法：python _tools/qa/_check_place_ranking.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
SERVICE = BACKEND / "app" / "services" / "place_service.py"
ENDPOINT = BACKEND / "app" / "api" / "v1" / "places.py"
TESTS = BACKEND / "tests" / "test_place_ranking.py"

#: 用户给的四个档位（**硬编码**：⛔ 不许从被测代码里读 —— 那就成了"用被判据的东西当判据"）。
WANT_TIERS = (1.0, 10.0, 50.0, 100.0)
#: 合并口径的**冻结值**（Q3=A：只排序、不合并）。
WANT_MERGE = 1.0
WANT_SAME_NAME = 30.0

#: 边界用例表：米 → 期望档位。含边界（取小档）与跨档两侧。
BOUNDARY = [
    (0.0, 0), (0.6, 0), (1.0, 0),
    (1.01, 1), (5.6, 1), (10.0, 1),
    (10.01, 2), (33.4, 2), (50.0, 2),
    (50.01, 3), (89.1, 3), (100.0, 3),
    (100.01, 4), (167.0, 4),
]

#: 兜底下限 —— 低于它就说明"扫描/导入坏了"，⛔ 不许安静地什么都查不到。
MIN_CHECKS = 14

bad: list[str] = []
checked = 0


def _ok(msg: str) -> None:
    print("  OK   " + msg)


def _bad(msg: str) -> None:
    global checked
    checked += 1
    print("  BAD  " + msg)
    bad.append(msg)


def _pass() -> None:
    global checked
    checked += 1


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def _code_only(src: str) -> str:
    """去掉注释与文档字符串 —— 判据只看**代码**，不看我们自己的说明文字。

    ⚠️ 为什么必须有（2026-09-27 实测踩到）：`places.py` 里那段注释**专门写着**
    "决定要不要新建一行的是 MERGE_METERS / SAME_NAME_METERS……与这里的档位毫无关系"，
    于是第 2 组判据把**注释里的名字**当成了"端点引用了合并口径"，报了一条假红。
    这与 `_check_all.py::_code_only` 是同一条纪律（那里也写着"判断规则会被散文骗过去"）。
    """
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"'''[\s\S]*?'''", "", src)
    return re.sub(r"^[ \t]*#.*$", "", src, flags=re.M)


def _import_service():
    """把真实模块导进来（纯函数，不连库）。导入失败 = 判据不成立，不许糊过去。"""
    sys.path.insert(0, str(BACKEND))
    try:
        from app.services import place_service  # noqa: PLC0415
        return place_service
    except Exception as exc:  # pragma: no cover
        _bad("导入 app.services.place_service 失败：" + repr(exc))
        return None


def main() -> int:
    print("[1] 真实模块（导入后直接问它，不看源码文本）")
    ps = _import_service()
    if ps is not None:
        if tuple(ps.NEAR_TIERS) == WANT_TIERS:
            _pass()
        else:
            _bad("NEAR_TIERS = " + repr(tuple(ps.NEAR_TIERS)) + "，规则要求 " + repr(WANT_TIERS))
        if ps.NEAR_METERS == 100.0:
            _pass()
        else:
            _bad("NEAR_METERS = " + repr(ps.NEAR_METERS) + "，应该是 100.0")
        if list(ps.NEAR_TIERS) == sorted(ps.NEAR_TIERS):
            _pass()
        else:
            _bad("四个档位不是嵌套递增的 —— 排序规则建立在这上面")
        wrong = [(m, ps.tier_of(m), want) for m, want in BOUNDARY if ps.tier_of(m) != want]
        if wrong:
            _bad("档位边界不对 " + str(len(wrong)) + " 处：" + "、".join(
                str(m) + "米->" + str(got) + "(应为" + str(want) + ")" for m, got, want in wrong[:4]))
        else:
            _pass()
            _ok("档位边界 " + str(len(BOUNDARY)) + " 条全对（含 1/10/50/100 米边界取小档）")
        # ⛔ 没有坐标 → 必须排**所有**有坐标的后面
        if ps.rank_key(None) > ps.rank_key(9_999_999.0):
            _pass()
        else:
            _bad("没有坐标的行被排到了有坐标的前面（rank_key(None) 没兜到最后一档）")
        if ps.rank_key(None)[0] == len(WANT_TIERS):
            _pass()
        else:
            _bad("rank_key(None) 的档位不是「最后一档」—— 它会被当成 0 米附近")
        # ⛔ Q3=A：合并半径一个字没动
        if ps.MERGE_METERS == WANT_MERGE:
            _pass()
        else:
            _bad("MERGE_METERS 被改成了 " + repr(ps.MERGE_METERS) + " —— Q3=A 说的是「只排序、不合并」")
        if ps.SAME_NAME_METERS == WANT_SAME_NAME:
            _pass()
        else:
            _bad("SAME_NAME_METERS 被改成了 " + repr(ps.SAME_NAME_METERS) + " —— 同上")

    print("[2] 代码形状（排序口径与合并口径不许互相渗透）")
    ep = _read(ENDPOINT)
    if not ep:
        _bad("找不到 " + str(ENDPOINT.relative_to(ROOT)))
    else:
        code = _code_only(ep)          # ⛔ 只看代码：注释里提到常量名不算引用
        fn = code.split("def list_places", 1)[-1].split("\ndef ", 1)[0]
        if re.search(r"lat:\s*float \| None", fn) and re.search(r"lng:\s*float \| None", fn):
            _pass()
        else:
            _bad("list_places 没有 lat/lng 参数（分档排序进不来）")
        if "lat is not None and lng is not None" in fn:
            _pass()
        else:
            _bad("list_places 里没有「两个都给才排序」这个条件 —— 只给一个就排会算出乱七八糟的距离")
        for need, why in (("near_places(", "取近处候选"), ("rank_key(", "排档"), ("finish_page(", "分页语义")):
            if need in fn:
                _pass()
            else:
                _bad("list_places 里看不到 " + need + "（" + why + "）")
        # ⛔ 端点文件里不许摸合并半径
        touched = [n for n in ("MERGE_METERS", "SAME_NAME_METERS") if n in code]
        if touched:
            _bad("places.py 里出现了合并口径 " + "、".join(touched) + " —— 排序与合并必须互不引用")
        else:
            _pass()
            _ok("端点只碰排序口径，一个合并常量都没引用")

    svc = _read(SERVICE)
    # ⚠️ 必须锚**函数定义行**，不能只找裸子串 `def near_places` ——
    #    `def near_places_gone(` 也满足那个子串，于是"函数被改名/删掉"这条判据**恒绿**
    #    （2026-09-27 反向验证第 11 条实测抓到；与本仓库"裸子串会被兄弟文案满足"是同一类毛病）。
    _m = re.search(r"^def near_places\(", svc, re.M)
    np_body = svc[_m.start():].split("\ndef ", 1)[0] if _m else ""
    if not np_body:
        _bad("place_service.py 里找不到 near_places")
    else:
        if "_bbox(" in np_body:
            _pass()
        else:
            _bad("near_places 没用 _bbox 先卡盒子 —— 会退化成全表扫描")
        if "haversine_m(" in np_body:
            _pass()
        else:
            _bad("near_places 没用 haversine_m 复核距离")
        if re.search(r"(?i)(select|where).{0,80}(acos|sin|cos|radians)", np_body):
            _bad("near_places 把距离公式写进 SQL 了（列上做函数 = 索引失效）")
        else:
            _pass()

    print("[3] 行为用例在不在")
    if TESTS.is_file():
        _pass()
        _ok("backend/tests/test_place_ranking.py 在（端到端顺序由它证）")
    else:
        _bad("没有 backend/tests/test_place_ranking.py —— 判据只剩「规则没被改坏」，没人证「这一屏排得对」")

    if checked < MIN_CHECKS:
        _bad("只跑了 " + str(checked) + " 项，低于下限 " + str(MIN_CHECKS) + "（判据自己坏了）")

    print("")
    if bad:
        print("❌ 地点分档排序判据：共 " + str(checked) + " 项，" + str(len(bad)) + " 项不成立：")
        for b in bad:
            print("   - " + b)
        return 1
    print("✅ 地点分档排序判据 " + str(checked) + " 项全部通过："
          "四档边界正确、>100 米不优先、没有坐标的排最后、合并半径一个字没动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
