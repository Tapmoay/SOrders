#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_current_location_button.py —— 下单页「我就在这里」按钮（FEAT-0003 / CHG-0004）的判据。

### 用户要的是什么

> 「在下单选择地点的时候，他不是有那么多吗？再加一个按钮啊，就是比较长的就是说我就在这啊，
>  直接定位……**它其实就是获取当前的手机定位就可以了**。」

货主端与派单员端都要有（两端共用同一个 `OrderCreateScreen`）。

### ⚠️ 它**放在哪**被改过一次（CHG-0004，2026-09-28）

第一版（FEAT-0003）把它放在「地址库」**抽屉里面**。用户看过之后：

> 「还有一个就是我已到了那个界面**不要放在那个地点库里面**，它直接放在**选手动选点和
>  地点库的下面一个按钮**，对直接放在那里，不要放地点库里面啊，进行选择」。

⇒ 它现在与「地图选点 / 地址库」并排成**同一层的三个选项**，在表单的「收货地址」卡里。
⛔ 所以本判据**两个方向都盯**：表单里必须有；`AddressPickerSheet` 里一处都不许有
（只判前者的话，有人把它加回抽屉也不会有任何反应）。

### 这条最容易走样的地方

"取当前定位"这件事有**三条**看起来都能跑、其实都会出错的路：

| 写法 | 后果（都不报错） |
| --- | --- |
| 退到系统定位 `DeviceLocation` | 那是 **WGS84**，国内偏几百米 —— 地址看着像真的，司机却开到隔壁街 |
| 把高德的 `(0,0)` 当有效点 | 高德**失败时照常回调** `(0,0)`，不判的话会填一个"几内亚湾"的地址 |
| 顺手把点存进地点库 | 用户只是想填一次表单，却往全库共享的地点库里塞了一条 |

所以判据盯四件事：

| # | 盯什么 |
| --- | --- |
| 1 | 按钮在（文案 + 回调 + 权限申请），且**两端共用**那一个页面 |
| 2 | ⛔ 不许出现 `DeviceLocation`（必须走高德那条） |
| 3 | 拿不到定位时**必须不填**：失效点要被 `SunLocation.isPlausible` 拦下，且**失败分支里不许调用回填回调** |
| 4 | ⛔ 不写库：回填处只允许 `vm.applyPicked` + 关抽屉（不许出现 repository 的写方法） |

### ⛔ 它证不了什么

- 它证不了"真机上真的能拿到点" —— 那是真机的事（本事项的真机证据见
  `docs/changes/FEAT-0003.md` ⑧：真机派单员端点一下，收货地址被填成
  "江西省景德镇市昌江区纬三路5号靠近万城云"）。
- 它证不了"这一下真的符合用户预期"（覆盖已填地址是有意为之，但没让用户确认过）。

### R3-BOUNDARY-JUSTIFICATION

R3-BOUNDARY-JUSTIFICATION: 这条**没法用边界消除** —— 它守的是"**这三条错路不许走**"，
而三条都是**能编译、能运行、界面上看起来正常**的写法。
第 2 条尤其：`DeviceLocation` 与本按钮用的是**同一个定位权限**，类型完全一样；
区别只在坐标系（WGS84 vs GCJ-02），而那是一个**数据含义**，不是类型。
唯一真正的边界是当场核对"这个文件里有没有引用它" —— 那就是这条判据本身。

用法：python _tools/qa/_check_current_location_button.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt"
NAV = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/nav/NavGraph.kt"

#: 兜底下限：低于它就说明源码形状变了、判据什么都查不到，必须先喊。
#: ⚠️ 这个数是**判据自己实际会跑几项**算出来的（当前 10 项：CHG-0004 加了一条
#: 「抽屉里一处都不许有」），不是拍的。
MIN_CHECKS = 10

bad: list[str] = []
checked = 0


def _ok(m: str) -> None:
    print("  OK   " + m)


def _bad(m: str) -> None:
    global checked
    checked += 1
    print("  BAD  " + m)
    bad.append(m)


def _pass() -> None:
    global checked
    checked += 1


def _sheet_body(code: str) -> str | None:
    """`AddressPickerSheet` 的函数体（判"抽屉里有没有那颗按钮"要用它）。

    ⚠️ 它是这个文件里**最后一个**大 composable，后面跟着的是别的小函数；
    切到下一个顶格的 `@Composable` / `private fun` 为止就够了（不追求精确配对）。
    """
    start = code.find("fun AddressPickerSheet(")
    if start < 0:
        return None
    tail = code[start + 10:]
    m = re.search(r"\n(@Composable\n)?(private |internal )?fun ", tail)
    return tail[: m.start()] if m else tail


def _code_only(src: str) -> str:
    """去掉注释 —— 判据只看**代码**（注释里会提到 DeviceLocation 之类的名字来解释"为什么不用"）。"""
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    return re.sub(r"^[ \t]*//.*$", "", src, flags=re.M)


def main() -> int:
    src = SCREEN.read_text(encoding="utf-8", errors="replace") if SCREEN.is_file() else ""
    if not src:
        print("❌ 找不到 " + str(SCREEN.relative_to(ROOT)))
        return 1
    code = _code_only(src)

    print("[1] 按钮在不在（文案 / 位置 / 权限）")
    if "我就在这里" in code:
        _pass()
        _ok("按钮文案在")
    else:
        _bad("找不到「我就在这里」这个按钮")

    # ⛔ 位置：必须在**表单**里，而且**不许在抽屉里**（CHG-0004 用户点名）。
    #    两个方向都判 —— 只判一个的话另一种坏法会安安静静地过。
    sheet_body = _sheet_body(code)
    if sheet_body is None:
        _bad("找不到 AddressPickerSheet 的函数体（形状变了？判据要跟着改）")
    elif "我就在这里" in sheet_body:
        _bad("「我就在这里」又出现在地址库抽屉里了 —— 用户 2026-09-28：「不要放在那个地点库里面」")
    else:
        _pass()
        _ok("地址库抽屉里没有它（用户点名不许放那儿）")
    # 在表单里 = 出现在 AddressPickerSheet 之前的那一段
    form_body = code.split("fun AddressPickerSheet(")[0]
    if "我就在这里" in form_body:
        _pass()
        _ok("它在表单那一侧（与「地图选点 / 地址库」同一层）")
    else:
        _bad("表单里找不到这颗按钮 —— 它被挪到别处了？")
    n_perm = code.count("ACCESS_FINE_LOCATION")
    if n_perm >= 1 and "rememberLauncherForActivityResult" in code:
        _pass()
        _ok("定位权限申请在（%d 处，与地图选点同一套）" % n_perm)
    else:
        _bad("没有定位权限申请 —— 没权限时连「问用户」这一步都没有")
    if "container.locationManager" in code:
        _pass()
    else:
        _bad("没有走 container.locationManager（那是全 App 唯一的取点路径）")

    print("[2] ⛔ 不许退到系统定位（WGS84，国内偏几百米）")
    if "DeviceLocation" in code:
        _bad("代码里引用了 DeviceLocation —— 那是系统定位(WGS84)，国内会偏几百米")
    else:
        _pass()
        _ok("没有引用 DeviceLocation")

    print("[3] 拿不到定位时**必须不填**")
    if "SunLocation.isPlausible" in code:
        _pass()
    else:
        _bad("没有用 SunLocation.isPlausible 过滤 —— 高德失败回的 (0,0) 会被当成有效点填进表单")
    # 失败分支里不许出现回填调用：取 isPlausible 判断到下一个 } 之间
    # ⚠️ 括号是**两层**（`isPlausible(pt.lat, pt.lng)` 自身带一对）—— 第一版写成 `[^)]*` 卡在里层，
    #    于是"找不到失败分支"永远成立（判据自己错，2026-09-27 实测）。
    m = re.search(r"if \(!SunLocation\.isPlausible\([^)]*\)\)\s*\{([^}]*)\}", code)
    if m is None:
        _bad("找不到「失效点 → 直接返回」这个分支（形状变了？）")
    elif "applyPicked" in m.group(1):
        _bad("失败分支里居然调用了 vm.applyPicked —— 拿不到点也会填一个假地址")
        # ⚠️ CHG-0004 之前这里判的是 `onPickCurrentLocation`（那层回调已经删了，
        #    按钮直接在表单里调 `vm.applyPicked`）—— 判据跟着改，否则它会**永远绿**。
    else:
        _pass()
        _ok("失败分支只提示、不回填")

    print("[4] ⛔ 只填表单，不写库")
    # ⚠️ CHG-0004 之后那层 `onPickCurrentLocation` 回调**没有了**（按钮直接在表单里，
    #    拿到点就调 `vm.applyPicked`）—— 判据跟着看"收集定位的那一段"。
    m2 = re.search(r"container\.locationManager\.locations\.collect \{ pt ->([\s\S]*?)\n    \}", code)
    if m2 is None:
        _bad("找不到收集定位那一段（`locationManager.locations.collect`）—— 形状变了？")
    else:
        body = m2.group(1)
        if "applyPicked" not in body:
            _bad("回填没走 vm.applyPicked（那是与本页其它取点一致的那一条）")
        elif re.search(r"repo\.|createLocation|saveLocation|shareLocation", body):
            _bad("回填处出现了写库调用 —— 用户只是要填一次表单")
        else:
            _pass()
            _ok("回填只走 applyPicked，没有写库")

    print("[5] 两端共用（货主 + 派单员）")
    nav = NAV.read_text(encoding="utf-8", errors="replace") if NAV.is_file() else ""
    n = len(re.findall(r"OrderCreateScreen\(", nav))
    if n >= 2:
        _pass()
        _ok("NavGraph 里有 %d 处 OrderCreateScreen（货主端 + 派单员端共用同一个页面）" % n)
    else:
        _bad("NavGraph 里只找到 %d 处 OrderCreateScreen —— 两端可能不是同一个页面，"
             "那本判据只覆盖了其中一端" % n)

    if checked < MIN_CHECKS:
        _bad("只跑了 " + str(checked) + " 项，低于下限 " + str(MIN_CHECKS) + "（判据自己坏了）")

    print("")
    if bad:
        print("❌ 我就在这里按钮判据：共 " + str(checked) + " 项，" + str(len(bad)) + " 项不成立：")
        for b in bad:
            print("   - " + b)
        return 1
    print("✅ 我就在这里按钮判据 " + str(checked) + " 项全部通过：按钮在、走高德、失效点不填、不写库、两端共用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
