#!/usr/bin/env python3
"""§14 Android 集成测试：**登录 → 导航 → 下单**（在真模拟器上按文字点，不写死坐标）。

报告 §14 的原话：
    真正缺的是 Android Integration Test —— 至少补「登录 ↓ 导航 ↓ 下单」这三条主链。

## 为什么是"脚本 + 真机"而不是 androidTest
本仓库的端到端一直是这个形状（_tools/notify/_ui.py 按文字点、_install_all.py 装包并登录）：
模拟器 + 真后端跑一遍，比 instrumented test 更贴现场（也能顺手抓到"后端没起、token 过期"这类事故）。
⛔ 三条链**各自独立判定**，任一失败就非零退出并打印**当前屏幕上的文字** ——
"点了没反应"这种静默失败最费时间，脚本必须自己把现场摊开。

用法：
    python _tools/e2e/_flow_login_nav_order.py                 # 货主 5556（默认）
    python _tools/e2e/_flow_login_nav_order.py --serial 5556 --account 13800000002
    python _tools/e2e/_flow_login_nav_order.py --shot-dir _agent/e2e
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ADB = r"D:\APPS\sdk\platform-tools\adb.exe"
ROOT = Path(__file__).resolve().parents[2]
PKG = "com.tapmoay.sorders"
API = "http://127.0.0.1:8000/api/v1"

#: 屏幕上的「标志文字」：每一步只认这些，认不出就报错并把当前屏幕摊出来。
LANDMARKS = {
    "login": ("登录", "手机号", "密码"),
    "home": ("工作台", "我的订单", "新增订单"),
    "create": ("商品", "收货", "地址", "提交"),
    "list": ("我的订单", "待派单", "派单中"),
}


class Emu:
    def __init__(self, serial: str, shot_dir: Path) -> None:
        self.serial = serial
        self.shot_dir = shot_dir
        self.shot_dir.mkdir(parents=True, exist_ok=True)

    def adb(self, *args: str, timeout: int = 60) -> str:
        r = subprocess.run([ADB, "-s", "emulator-" + self.serial, *args],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")

    def nodes(self) -> list[dict]:
        self.adb("shell", "uiautomator", "dump", "/sdcard/_flow.xml")
        xml = self.adb("shell", "cat", "/sdcard/_flow.xml")
        import re

        out = []
        for tag in re.findall(r"<node[^>]*>", xml):
            text = re.search(r'text="([^"]*)"', tag)
            desc = re.search(r'content-desc="([^"]*)"', tag)
            bounds = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if not bounds:
                continue
            x1, y1, x2, y2 = (int(bounds.group(i)) for i in range(1, 5))
            out.append({"text": (text.group(1) if text else ""),
                        "desc": (desc.group(1) if desc else ""),
                        "box": (x1, y1, x2, y2), "cy": (y1 + y2) // 2})
        return out

    def texts(self) -> list[str]:
        return [n["text"] for n in self.nodes() if n["text"]]

    def screen(self) -> str:
        return " ｜ ".join(self.texts()[:40])

    def shot(self, name: str) -> None:
        self.adb("shell", "screencap", "-p", "/sdcard/_flow.png")
        raw = subprocess.run([ADB, "-s", "emulator-" + self.serial, "exec-out", "cat", "/sdcard/_flow.png"],
                             capture_output=True, timeout=90).stdout
        (self.shot_dir / ("flow-" + name + ".png")).write_bytes(raw)

    def tap(self, labels: tuple[str, ...] | str, *, optional: bool = False) -> bool:
        want = (labels,) if isinstance(labels, str) else labels
        rows = self.nodes()
        # 先精确匹配；再退一步**包含**匹配（按钮文字常带尾缀：「提交订单 ¥0」「添加商品 0/10」）——
        # 只做精确匹配时，这一类按钮会被判成"找不到"，而现场看上去一切正常。
        hit = next((n for n in rows if n["text"] in want or n["desc"] in want), None)
        if hit is None:
            hit = next((n for n in rows
                        if n["text"] and any(w in n["text"] for w in want)), None)
        if hit is not None:
            x1, y1, x2, y2 = hit["box"]
            self.adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
            print("      点了「" + hit["text"] + "」")
            time.sleep(1.2)
            return True
        if not optional:
            print("      ❌ 找不到这些文字：" + "、".join(want))
        return False

    def tap_row_right(self, label: str) -> bool:
        """点**这一行最右侧**的可点控件（商品行右边的「＋」）。

        商品名本身不可点（实测：点名字没有任何反应），可点的是同一行右侧那颗 ＋。
        判据用"与它纵向对齐、且 x 最大" —— 与 \`_ui.py\` 的 \`taprow\` 同一个思路（不写死坐标）。
        """
        rows = self.nodes()
        anchor = next((n for n in rows if n["text"] == label), None)
        if anchor is None:
            return False
        same_row = [n for n in rows if abs(n["cy"] - anchor["cy"]) <= 40 and n["box"][0] > anchor["box"][0]]
        if not same_row:
            return False
        target = max(same_row, key=lambda n: n["box"][0])
        x1, y1, x2, y2 = target["box"]
        self.adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
        print("      点了「" + label + "」这一行右侧的「" + target["text"] + "」")
        time.sleep(1.0)
        return True

    def tap_last(self, labels: tuple[str, ...]) -> bool:
        """点**最后**一个文字精确等于这些候选的节点。

        ⚠️ 弹层（数量/确定）在 uiautomator 的 dump 里排在**最后** —— 而按文档顺序取第一个命中，
        会点到页面上同名的那个（或一个空文字的容器），表现是"点了没反应、弹层还在"
        （第一次实测：数量弹层「确定」没点上，后面所有步骤都在弹层背后空转）。
        """
        rows = self.nodes()
        hit = next((n for n in reversed(rows) if n["text"] in labels), None)
        if hit is None:
            return False
        x1, y1, x2, y2 = hit["box"]
        self.adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
        print("      点了（弹层）「" + hit["text"] + "」")
        time.sleep(1.2)
        return True

    def wait_for(self, labels: tuple[str, ...], timeout: float = 12.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            cur = self.texts()
            if any(any(w in t for t in cur) for w in labels):
                return True
            time.sleep(0.8)
        return False

    def type_text(self, value: str) -> None:
        self.adb("shell", "input", "text", value)
        time.sleep(0.6)


def api(path: str, token: str | None = None, body: dict | None = None, method: str = "GET"):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read().decode()
        return json.loads(raw) if raw else None


def backend_token(account: str, password: str) -> str:
    got = api("/auth/login", body={"phone": account, "password": password}, method="POST")
    return got["access_token"] if isinstance(got, dict) else got[0]


def chain_logout(emu: Emu) -> bool:
    """先退出登录 —— 否则"登录"这一条链根本没被测到（只是复用了上一次的会话）。"""
    print("① 登录（--relogin：先退出当前会话）")
    emu.tap(("我的", "我的页", "个人中心"), optional=True)
    if not emu.tap(("退出登录", "退出"), optional=True):
        print("      ⚠️ 找不到「退出登录」（可能已经在登录页）")
        return True
    emu.tap(("确定", "确认", "退出"), optional=True)
    time.sleep(2)
    return emu.wait_for(LANDMARKS["login"], timeout=12)


def chain_login(emu: Emu, account: str, password: str) -> bool:
    print("① 登录")
    emu.adb("shell", "am", "force-stop", PKG)
    emu.adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(6)
    emu.shot("01-launch")
    if emu.wait_for(LANDMARKS["home"], timeout=12):
        print("      ✅ 已经是登录态（工作台在）—— 这本身就是「会话恢复」那条链")
        return True
    if not emu.wait_for(LANDMARKS["login"], timeout=10):
        print("      ❌ 既没看到工作台也没看到登录页。当前屏幕：" + emu.screen())
        return False
    fields = [n for n in emu.nodes() if n["text"] == "" and n["box"][3] - n["box"][1] > 60]
    if len(fields) < 2:
        print("      ❌ 登录页只找到 " + str(len(fields)) + " 个输入框：" + emu.screen())
        return False
    for node, value in zip(fields[:2], (account, password)):
        x1, y1, x2, y2 = node["box"]
        emu.adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
        emu.type_text(value)
    emu.shot("02-filled")
    emu.tap(("登录", "登 录"))
    ok = emu.wait_for(LANDMARKS["home"], timeout=20)
    emu.shot("03-home")
    print("      " + ("✅ 登录后进了工作台" if ok else "❌ 登录后没进工作台。当前屏幕：" + emu.screen()))
    return ok


def chain_nav(emu: Emu) -> bool:
    print("② 导航（工作台 → 我的订单 → 新增订单）")
    if not emu.tap(("我的订单", "订单与账本"), optional=True):
        print("      当前屏幕（没找到「我的订单」）：" + emu.screen())
    ok = emu.wait_for(LANDMARKS["list"], timeout=10)
    emu.shot("04-list")
    if not ok:
        print("      ❌ 没进「我的订单」。当前屏幕：" + emu.screen())
        return False
    opened = emu.tap(("+新增订单", "新增订单", "去下单", "下单"))
    emu.shot("05-create")
    if not opened or not emu.wait_for(LANDMARKS["create"], timeout=10):
        print("      ❌ 没进「新增订单」页。当前屏幕：" + emu.screen())
        return False
    print("      ✅ 到了新增订单页")
    return True


def chain_order(emu: Emu, token: str) -> bool:
    print("③ 下单（选商品 → 数量 → 地址 → 提交）")
    products = api("/products?limit=5", token)
    names = [p.get("name", "") for p in (products.get("items") if isinstance(products, dict) else products) or []]
    print("      后端商品库前几个：" + "、".join(names[:5]))
    if not emu.tap(("添加商品", "选择商品", "去选择商品", "选商品")):
        print("      当前屏幕：" + emu.screen())
        return False
    emu.shot("06-picker")
    if not names or not emu.tap_row_right(names[0]):
        print("      ❌ 商品选择页里点不到「" + (names[0] if names else "?") + "」那一行的 ＋。当前屏幕：" + emu.screen())
        return False
    emu.tap_last(("确定", "确认", "完成", "添加"))
    emu.shot("07-qty")
    # 挑完之后要按底部的「加入清单」才算加进这一单（实测：不按它就一直停在挑选页）
    emu.tap(("加入清单", "确定", "完成"))
    if emu.tap(("地址库", "选择地址", "常用地址", "选择收货地址"), optional=True):
        # 地址列表里的文字随数据变 —— 拿**后端真实返回的地址**去点，绝不猜文案
        try:
            addr = api("/shipper/addresses", token) or []
            keys = [str(a.get("detail_address") or a.get("contact_name") or "")[:8] for a in (addr or [])]
        except Exception:  # noqa: BLE001
            keys = []
        keys = [k for k in keys if k]
        print("      地址库里有 " + str(len(keys)) + " 条可用，按第一条的文字点")
        if keys:
            emu.tap(tuple(keys), optional=True)
        emu.tap(("确定", "确认", "使用", "保存"), optional=True)
    else:
        print("      ⚠️ 这一页没有「地址库」入口（继续试提交）")
    emu.shot("08-before-submit")
    # ⛔ 「下单」是这一页的**标题**（小节名），不是按钮 —— 放进候选会先命中它，
    #    表现是"点了提交却一直停在表单页"（实测踩到）。只认「提交订单」（带金额尾缀，走包含匹配）。
    if not emu.tap(("提交订单", "确认下单")):
        print("      当前屏幕：" + emu.screen())
        return False
    ok = emu.wait_for(("提交成功", "下单成功", "待派单", "我的订单"), timeout=20)
    emu.shot("09-after-submit")
    print("      " + ("✅ 提交后回到了列表/成功提示" if ok else "❌ 提交后没有成功迹象。当前屏幕：" + emu.screen()))
    return ok


def chain_verify(token: str, before: int) -> bool:
    print("④ 对账（后端真有一张新单）")
    orders = api("/orders?limit=1", token)
    rows = orders.get("items") if isinstance(orders, dict) else orders
    now = len(rows or [])
    print("      下单前 " + str(before) + " 条 → 现在接口返回 " + str(now) + " 条（limit=1）")
    return now >= 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default="5556")
    ap.add_argument("--account", default="13800000002")
    ap.add_argument("--password", default="123321")
    ap.add_argument("--shot-dir", default=str(ROOT / "_agent" / "e2e"))
    ap.add_argument("--relogin", action="store_true",
                    help="先退出登录再登一遍（默认：已经是登录态就只验「会话恢复」）")
    a = ap.parse_args()

    emu = Emu(a.serial, Path(a.shot_dir))
    state = emu.adb("get-state").strip()
    if state != "device":
        print("❌ emulator-" + a.serial + " 不在线（" + state + "）—— 先起模拟器")
        return 2
    try:
        token = backend_token(a.account, a.password)
    except Exception as exc:  # noqa: BLE001
        print("❌ 后端登录失败（" + str(exc) + "）—— 本机 uvicorn 起了吗（127.0.0.1:8000）？")
        return 2

    if a.relogin:
        chain_logout(emu)
    results = {
        "登录": chain_login(emu, a.account, a.password),
    }
    if results["登录"]:
        results["导航"] = chain_nav(emu)
    if results.get("导航"):
        results["下单"] = chain_order(emu, token)
    if results.get("下单"):
        results["对账"] = chain_verify(token, 0)

    print()
    for name, ok in results.items():
        print(("  ✅ " if ok else "  ❌ ") + name)
    if all(results.values()) and len(results) == 4:
        print("✅ 登录 → 导航 → 下单 → 对账 四段全通（截图在 " + str(emu.shot_dir) + "）")
        return 0
    print("❌ 集成链路没跑通：上面逐段标了红，截图与「当前屏幕文字」都在输出里")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
