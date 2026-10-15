"""红线：地图选点弹层 `ui/common/AmapPicker.kt`（**下单 / 地址与联系人 / 订单详情导航三处共用**）。

## 这一页在防什么（每条都对应一种"真机上不报错"的坏）
1. **坐标不可信还敢确认**（2026-09-19 全项目报告 P1-13，中）：高德定位失败回的是 **`(0,0)` 而不是 null**，
   而这个弹层的初始坐标就是 `initialLat ?: 0.0` —— 「没拿到定位就直接点确认」会把 `(0.0, 0.0)`
   写进订单、也写进**全库共享的地点库**（那个库没有删除接口，污染不可逆），导航还会把人指到几内亚湾。
   → 闸只能有**这一处**（复用 `SunLocation.isPlausible`），三个调用方一起受保护。
2. **地图实例被销毁**：高德 **9.8.3** 在 Android 15+/16 arm64 上 `mapView.onDestroy()` 触发 native SIGABRT
   （SDK 未适配新系统）→ 实例常驻单例、只 `onPause/onResume`。
3. **卫星图层**（2026-09-22 用户点名：「那个地图**能否是卫星地图**呢」）：
   · ⛔ **瓦片地址必须 https**：本包 `res/xml/network_security_config.xml` 是
     `cleartextTrafficPermitted="false"`，http 瓦片在真机上会被**静默**拦掉 ——
     界面不报错、只是路名永远不出现（"看起来没坏"的那一类，最难查）；
   · **`applyMapType` 只许在「打开弹层」与「用户点切换」两处调用**（都经 `AmapMapHolder`）——
     放进 `onCameraChange` 会**每拖一次地图就叠一层**瓦片；
   · 卫星只有**影像、没有路名**（9.8.3 实测）→ 必须叠一层「路网 + 注记」瓦片，
     否则选点时认不出是哪个门、哪条巷子（厂区/仓库一片屋顶）。
4. **三个调用方共用这一份**：哪个页面自己再画一个地图弹层，"坐标不可信"那道闸就会漏掉那一页。

用法：python _tools/qa/_check_map_picker.py
配套：python _tools/qa/_reverse_verify_map_picker.py（9 种破坏方式全被抓）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, read, strip_comments  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
UI_DIR = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui"
PICKER = UI_DIR / "common/AmapPicker.kt"
DETAIL = UI_DIR / "order/OrderDetailScreen.kt"      # 司机/派单员「我到了，补导航」
CREATE = UI_DIR / "shipper/OrderCreateScreen.kt"    # 下单
ADDR = UI_DIR / "shipper/AddressScreen.kt"          # 地址与联系人

#: 除弹层自己以外，还有谁在用它（下单 / 地址与联系人 / 订单详情导航）。
EXPECTED_CALLERS = 3


def main() -> int:
    if refuse_if_injecting("地图选点红线"):
        return 1

    c = Checker()

    # ── 0. 反空转 ─────────────────────────────────────────────────────────
    c.section("0. 反空转（文件/结构变了要先喊，而不是安静地什么都不查）")
    c.ok("AmapPicker.kt 在", PICKER.exists())
    if not PICKER.exists():
        return 1
    raw = read(PICKER)
    src = strip_comments(raw)
    c.ok("它仍然是那个弹层（有 `fun AmapPickerDialog(`）", "fun AmapPickerDialog(" in src)
    c.ok("地图载体是 AMap 的 `MapView`", "MapView" in src and "import com.amap.api.maps.AMap" in src)

    # ── 1. 坐标不可信不许确认（P1-13 那道闸）────────────────────────────────
    c.section("1. 坐标不可信时**不许**确认（这道闸只有这一处，三页共用）")
    c.ok("用共用判据 `SunLocation.isPlausible`（不自己写一套坐标校验）",
         "SunLocation.isPlausible(lat, lng)" in src)
    c.ok("守卫出现在**确认回调之前**（先判后给，顺序反了就白判）",
         src.find("isPlausible") != -1 and src.find("onPicked(") != -1
         and src.find("isPlausible") < src.find("onPicked("))
    c.ok("被拦住时**就地**给一句中文提示（不是静默点了没反应）",
         'coordError = "' in src and "coordError" in src)
    c.ok("重新选点时把上一次的提示撤掉", "coordError = null" in src)

    # ── 1b. 拿不到定位 / 还没选过点：**不许静默**、**不许确认**（BUG-0039，2026-10-15）──
    # 现场（emulator-5554 派单员，代理下单 → 地图选点）：地图停在高德默认视图（北京）、
    # 底部只有"拖动地图或点击地图选择位置"、点「定位到当前位置」毫无反馈。
    # 两个根因：① 高德失败回的是哨兵 `(0,0)`，collector 原来直接跳过 —— 一句话都不说；
    #          ② 「确认」那道闸只知道 `(0,0)` 不可信，**挡不住北京**（39.9,116.4 是可信坐标）。
    c.section("1b. 拿不到定位要说话、没选过的中心不许确认（BUG-0039）")
    c.ok("定位失败那条分支真的会说话（哨兵 `(0,0)` 不再被 `if` 吞掉）",
         re.search(r"if \(pt\.lat != 0\.0 \|\| pt\.lng != 0\.0\)[\s\S]{0,600}?else \{[\s\S]{0,300}?locateNote = \"", src)
         is not None)
    c.ok("成功那条分支会把那句话撤掉（成功还挂着失败提示 = 自相矛盾）",
         re.search(r"if \(pt\.lat != 0\.0 \|\| pt\.lng != 0\.0\) \{\s*\n\s*locateNote = null", src) is not None)
    c.ok("`requestSingle()` 的返回值不再丢（false = 一个回调都不会来）",
         "if (!container.locationManager.requestSingle()) {" in src)
    c.ok("`requestSingle()` 返回 false 时按钮不再卡在「定位中…」",
         re.search(r"if \(!container\.locationManager\.requestSingle\(\)\) \{\s*\n\s*locating = false", src) is not None)
    c.ok("权限被拒也说话（那条路上同样一个回调都没有）",
         'locateNote = "没有定位权限' in src)
    c.ok("那句话画在屏上（不是只写进状态没人用）", "locateNote?.let" in src)
    c.ok("「这个中心有没有出处」进状态：`centered`", "var centered by remember { mutableStateOf(false) }" in src)
    c.ok("跳转过的中心算有出处（初始坐标 / 上次定位 / 搜索命中 / 定位回流都走 `jumpTo`）",
         re.search(r"fun jumpTo\(p: LatLng, zoom: Float = 16f\) \{[\s\S]{0,400}?centered = true", src) is not None)
    c.ok("用户自己拖/点地图也算有出处（相机停稳那一支）",
         re.search(r"onCameraChangeFinish[\s\S]{0,600}?centered = true", src) is not None)
    c.ok("⛔ 没选过（`!centered`）就不许出坐标 —— 挡的是「北京」这种**可信但从没看过**的中心",
         "if (!centered) {" in src)
    c.ok("那道闸在**确认口里面**（写进状态却在别处判 = 白判）",
         src.find("if (!centered) {") != -1 and src.find("if (!centered) {") > src.find("onClick = {")
         and src.find("if (!centered) {") < src.find("onPicked("))

    # ── 2. 图层：卫星 / 标准 两档，且有切换入口 ─────────────────────────────
    c.section("2. 图层切换：卫星 ↔ 标准")
    c.ok("用了 SDK 的卫星图层常量", "AMap.MAP_TYPE_SATELLITE" in src)
    c.ok("标准档也在（切回来要有明确的一档，不能靠「不设」）", "AMap.MAP_TYPE_NORMAL" in src)
    c.ok("按钮文案两档都在（写「将要切到的那个」）", '"卫星"' in src and '"标准"' in src)
    c.ok("选择写回共用持有者（地图实例是单例，重开弹层要能记住）",
         "AmapMapHolder.satellite = satellite" in src)
    c.ok("⛔**默认图层 = 卫星**（用户 2026-09-22：「不要……默认做成卫星地图，然后再是可以切换成标准地图」）",
         re.search(r"var satellite: Boolean = true", src) is not None)

    # ── 2b. 司机那一侧起步是标准（同一页里派单员仍是卫星）────────────────────
    c.section("2b. 司机那一侧起步 = **标准地图**（用户：「但是司机的导航是标准地图」）")
    detail = strip_comments(read(DETAIL))
    # ⚠️ 这里必须**逐处**判（原来只要求"存在一处带 driver 的写法"）：CHG-0133 在这一页加了
    #    第二处 `startSatellite =`（改地址那个弹层），于是"只把第一处改成全局值"这种注入
    #    会被**第二处**顶绿 —— 2026-10-15 跑反验时当场抓到（注入 ⑦ 漏网）。改成"每一处都带 driver"。
    _sat_sites = re.findall(r"startSatellite\s*=\s*([^\n,]+)", detail)
    c.ok(f"订单详情页**每一处** `startSatellite` 都按角色判 driver（不拿「上次那个」给司机；实际 {len(_sat_sites)} 处）",
         len(_sat_sites) >= 1 and all('"driver"' in s for s in _sat_sites))
    c.ok("下单页不传（用默认＝卫星）", "startSatellite" not in strip_comments(read(CREATE)))
    c.ok("地址与联系人页不传（用默认＝卫星）", "startSatellite" not in strip_comments(read(ADDR)))
    c.ok("图层是**当参数传**进去的（不在持有者里读全局 —— 否则司机会被「上次选的卫星」顶掉）",
         "fun applyMapType(aMap: AMap, satellite: Boolean)" in src)

    # ── 3. ⛔ 瓦片必须 https ────────────────────────────────────────────────
    c.section("3. ⛔ 瓦片地址必须 https（http 会被网络策略静默拦掉，只表现为「没有路名」）")
    c.ok("路网注记瓦片用的是 https", "https://wprd0" in src)
    c.ok("全文件**没有**任何 `http://`（明文地址一律不许出现）", "http://" not in src,
         "出现明文地址：本包禁明文，真机上会被拦掉且不报错")

    # ── 4. 图层只在这两处应用 ──────────────────────────────────────────────
    c.section("4. 图层只在「打开弹层」与「用户点切换」两处应用（防每拖一次叠一层）")
    n_calls = src.count("AmapMapHolder.applyMapType(")
    c.ok(f"经持有者调用 `applyMapType` 恰好 2 处（实际 {n_calls}）", n_calls == 2)
    c.ok("打开弹层时就应用一次（记住上次选择）",
         re.search(r"LaunchedEffect\(Unit\)\s*\{[\s\S]{0,400}?AmapMapHolder\.applyMapType\(", src) is not None)
    c.ok("定义处带 `satellite` 判断（两档都真的用上了）",
         re.search(r"if \(satellite\) AMap\.MAP_TYPE_SATELLITE else AMap\.MAP_TYPE_NORMAL", src) is not None)

    # ── 5. 地图实例不许销毁（9.8.3 的 native 崩溃规避）──────────────────────
    c.section("5. 地图实例常驻：⛔ 不许调 onDestroy（9.8.3 在 Android 15+/16 arm64 上会 native SIGABRT）")
    c.ok("没有 `onDestroy`", "onDestroy" not in src)
    c.ok("有关闭时的 `onPause`（只暂停渲染）", "onPause" in src)
    c.ok("有关闭标记 `alive`（关掉之后所有地图回调短路，防定位回流闪退）", "alive" in src)

    # ── 6. 三处共用同一份 ──────────────────────────────────────────────────
    c.section("6. 三个调用方共用这一份（谁自己再画一个，那道坐标闸就漏了那一页）")
    callers = []
    for p in sorted(UI_DIR.rglob("*.kt")):
        if p == PICKER:
            continue
        if "AmapPickerDialog(" in strip_comments(read(p)):
            callers.append(p.relative_to(UI_DIR).as_posix())
    c.ok(f"调用方恰好 {EXPECTED_CALLERS} 个（实际 {len(callers)}：{', '.join(callers)}）",
         len(callers) == EXPECTED_CALLERS)
    c.ok("弹层本身只有一处定义（`fun AmapPickerDialog(` 全库 1 处）",
         sum(strip_comments(read(p)).count("fun AmapPickerDialog(") for p in UI_DIR.rglob("*.kt")) == 1)

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {c.n_ok} 项通过，{len(c.fails)} 项失败：")
        for label, detail in c.fails:
            print(f"   - {label}" + (f"\n     {detail}" if detail else ""))
        return 1
    print(f"✅ 地图选点弹层 {c.n_ok} 项全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
