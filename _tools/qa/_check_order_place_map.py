# -*- coding: utf-8 -*-
"""订单详情的「地点信息」点开一张**只读**地图看一眼 —— 台账 L-18（2026-10-06）。

## 用户口径（原话）
- m00481：「订单详情页面……点击那个地点信息……是可以直接调用高德，然后直接在地图上显示出来」
  「这只是能看，不能做修改，修改的话只能到那个地点库里面去修改」。
- **m00542（更晚，以它为准）**：「点击订单详情就直接打开一个地图，就是我们直接定位的那个地图……
  只是看一些详细……不会产生任何返回结果」⇒ **不跳高德 App**，在 App 内打开只读地图。

## 机制：这一条为什么必须有机器的判据
「地址那一行可点」写出来只有两种可能：`Modifier.clickable { showPlaceMap = true }` 在、或者不在。
删掉它**不会有编译错误、不会有任何用例报红** —— 地址照旧显示、司机那颗「高德导航」照旧能开，
`_check_delivery_flow.py` / `_check_detail_inline_edit.py` 那一类判据全都照样通过。
更贵的是**退化**，而且每一条退化源码都完全合法：
- 换回 m00481 那条旧口径（跳高德 `androidamap://viewMap`）：一样是"点一下打开一张地图"，
  只是把用户从 App 里踢出去、还依赖装了高德 —— 这正是"旧口径被漏改回来"的样子；
- 复用选点弹层 `AmapPickerDialog`（它有 `onPicked` 与确认口）：从"看一眼"变成"能改坐标"，
  而口径明写「不会产生任何返回结果」；
- 少摘一次 marker：地图是进程内单例，会叠着上一单的目标点，还会跟着出现在后面打开的**选点**弹层里；
- 闸门写成 `true`：没坐标的订单点下去是一张空地图。

## 这一刀动什么 / 不动什么
- **动**：新增 `ui/common/AmapViewDialog.kt`（只读看位置弹层）；`ui/order/OrderDetailScreen.kt`
  收货信息卡里**地址那一行有坐标时整行可点**（开这个弹层），行尾多一颗只显示的「看地图」。
- **不动**：`util/AmapUri.kt`（导航那条路，逐字与 HEAD 一致）、司机那颗「高德导航」按钮、
  `NavigationBlock` 的三种状态与文案、行尾「改」（仍是恰好 4 颗）、`ui/common/AmapPicker.kt`
  （选点弹层那份契约一个字没动）、后端（零改动）。

## 判据（8 组）
1. 新弹层本身：签名 / 复用同一份地图单例 / 相机落到目标点 / 一枚 marker 且自己收拾 / 只 onPause 不 onDestroy；
2. 它**不是**选点弹层（没有 onPicked、不注册点击与相机监听、没有搜索与定位、没有确认口）；
3. 它**不跳高德**：全仓不再有 viewMap 那条旧口径、AmapUri 只剩导航一条路；
4. 入口＝收货信息卡地址那一行（闸门 hasCoords ＋ 整行可点 ＋ 开的是这个弹层）；
5. 只读：那一段里没有任何写操作；
6. 闸门与 `NavigationBlock` 里那句**逐字一致**（同一个表达式恰好 2 处）；
7. 行尾那颗「看地图」自己不带点击（一行只留一个热区 ＋ 一颗「改」）；弹层调用点恰好两处；
8. 文档（CHG / README / CLAIM）＋ 反验脚本 ＋ 防静默空转。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
这一条要守的是一串**否定式**属性：「不许跳高德」「不许长出选点出口」「不许有确认口」「不许叠 marker」
「不许在没坐标时给入口」。否定式属性在类型系统里没有位置：`fun AmapViewDialog(...)` 少一个
`onPicked` 参数不会让任何调用点编译失败，多加一个也不会；把整个 `clickable` 段删掉，
`if (hasCoords)` 那个闸门就变成死代码，编译器一声不吭；把 `showPlaceMap = true` 换成
`openAmapNavigation(...)` 仍然返回 Unit、仍然"点一下打开一张地图"。
正向的边界（接口 / 分层 / 数据 Owner）在这里也使不上劲：这个弹层**不写任何数据**，
没有"写入方"可以收敛 —— 仓库层根本没有一个点能拦住「多显示了一张图」或者「多长了一个确认按钮」。
所以在源码结构上钉：谁被调用、签名里有没有出口、那一行是不是可点、单例上的 marker 有没有被摘。

用法：python _tools/qa/_check_order_place_map.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
# 注释剥离**只有一份实现**（抄一份必踩同一个坑）
from _check_product_card_single_source import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = AND / "ui/order/OrderDetailScreen.kt"
AMAP = AND / "util/AmapUri.kt"
PICKER = AND / "ui/common/AmapPicker.kt"
VIEW = AND / "ui/common/AmapViewDialog.kt"
MAP_PICKER_CHECK = ROOT / "_tools/qa/_check_map_picker.py"
DETAIL_EDIT_CHECK = ROOT / "_tools/qa/_check_detail_inline_edit.py"
CHG = ROOT / "docs/changes/CHG-0053.md"
README = ROOT / "docs/changes/README.md"
CLAIM = ROOT / "docs/AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools/qa/_reverse_verify_order_place_map.py"

#: 全仓至少要有这么多 .kt（防「目录被搬走 → 一个都没扫到 → 全绿」）。
MIN_KT = 100
#: 半角双引号：源码里字符串字面量的定界符。
DQ = chr(34)
#: 地址行与 NavigationBlock 里**逐字**同一句闸门（判据 6）。
COORDS_GATE = "val hasCoords = !order.addressLat.isNullOrBlank() && !order.addressLng.isNullOrBlank()"
#: 收货信息卡那一段的头尾（切段用；中间就是地址行 ＋ 位置图）。
CARD_HEAD = 'SectionTitle(Icons.Default.Place, Color(ShipperTeal), "收货信息")'
CARD_TAIL = "PlacePhotoStrip("
#: 那一下点下去做的事：只开本地那个开关（判据 4）。
SHOW = "Modifier.clickable { showPlaceMap = true }"
#: 弹层的调用（判据 4/7）。
VIEW_CALL = "AmapViewDialog("
#: 导航空调那个既有调用点（判据 6：司机那颗按钮，本次一个字没动）。
NAV_CALL = "openAmapNavigation(context, vm.order?.addressLng, vm.order?.addressLat, vm.order?.addressDetail)"
REQUIRED_FILES = [SCREEN, AMAP, PICKER, VIEW, MAP_PICKER_CHECK, DETAIL_EDIT_CHECK, CHG, README, CLAIM, REVERSE]


def read(p: Path) -> str:
    """读文本并**统一成 LF**（判据里有跨行锚点，CRLF 会让它们一处也匹配不上）。"""
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").replace(chr(13) + chr(10), chr(10))


def code(p: Path) -> str:
    return strip_comments(read(p))


def between(text: str, a: str, b: str) -> str:
    """`a` 之后、`b` 之前的那一段（用来问「这句在不在这一段里」）。"""
    i = text.find(a)
    if i < 0:
        return ""
    j = text.find(b, i + len(a))
    return text[i : j if j >= 0 else len(text)]


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def absent(self, label: str, text: str, needle: str) -> None:
        self.ok(label, needle not in text, f"不该出现却出现了 {needle!r}")


def main() -> int:
    c = Checker()
    screen = code(SCREEN)
    amap = code(AMAP)
    picker = code(PICKER)
    view = code(VIEW)
    kts = sorted(AND.rglob("*.kt"))
    ui = [(p.relative_to(AND).as_posix(), code(p)) for p in kts]
    card = between(screen, CARD_HEAD, CARD_TAIL)

    print("== 1. 新弹层本身：一份地图载体 ＋ 一枚会自己收拾的 marker ==")
    c.ok("先确认读到了东西（否则下面每一条都是空转）",
         len(screen) > 1000 and len(view) > 800, f"screen={len(screen)} view={len(view)}")
    c.ok("签名逐字（lat/lng 是 Double，签名里**没有** onPicked 这个出口）",
         "fun AmapViewDialog(\n    lat: Double,\n    lng: Double,\n    title: String,\n    onDismiss: () -> Unit,\n) {" in view,
         "弹层不在 —— 地址行点下去没有东西可开")
    c.ok("复用同一份地图单例（不是自己 new 一个 MapView）",
         "AmapMapHolder.get(context.applicationContext)" in view)
    c.ok("图层用的还是单例上那份记忆（与选点弹层是同一个开关）",
         "AmapMapHolder.satellite = satellite" in view and "AmapMapHolder.applyMapType(aMap, satellite)" in view)
    c.ok("打开即落到目标点（newLatLngZoom 16f）",
         "CameraUpdateFactory.newLatLngZoom(LatLng(lat, lng), 16f)" in view)
    c.ok("目标点是**真 marker**（不是画在屏幕中央的图钉）",
         "MarkerOptions().position(LatLng(lat, lng))" in view and "placeMarker = aMap.addMarker(opts)" in view)
    c.ok("marker 句柄是**文件级**的（写成 remember 就没人能在下一次打开时摘掉）",
         "private var placeMarker: Marker? = null" in view)
    c.ok("开弹层先清一次 ＋ 关弹层再清一次 ＋ 定义一次（恰好 3 处）",
         view.count("clearPlaceMarker()") == 3, f"实际 {view.count(chr(99)+chr(108)+chr(101)+chr(97)+chr(114)+chr(80)+chr(108)+chr(97)+chr(99)+chr(101)+chr(77)+chr(97)+chr(114)+chr(107)+chr(101)+chr(114)+chr(40)+chr(41))} 处")
    c.ok("清的时候把句柄置空（幂等）", "placeMarker = null" in view)
    c.ok("关闭只 onPause（不许 onDestroy：9.8.3 在 Android 15+/16 arm64 上 native 闪退）",
         "mapView.onPause()" in view)
    c.absent("⛔ 永不 onDestroy", view, "onDestroy")
    c.ok("顶栏只有标题与「关闭」", 'TextButton(onClick = onDismiss) { Text("关闭") }' in view)
    c.ok("标题会截断且带省略号（长地址不许把顶栏撑爆）",
         "maxLines = 2" in view and "overflow = TextOverflow.Ellipsis" in view)

    print("== 2. 它是「看一眼」而不是「选点」：没有出口、没有监听、没有确认口 ==")
    c.absent("没有 onPicked（签名里就没有地方能把坐标交出去）", view, "onPicked")
    c.absent("不注册点击选点", view, "setOnMapClickListener")
    c.absent("不注册相机监听（拖地图不会反算地址）", view, "setOnCameraChangeListener")
    c.absent("不碰逆地理", view, "GeocodeSearch")
    c.absent("不碰定位", view, "locationManager")
    c.absent("没有搜索框", view, "OutlinedTextField")
    c.absent("没有 AppContainer / container（这一层根本不需要后端）", view, "AppContainer")
    c.absent("没有「确认」口（口径：不会产生任何返回结果）", view, DQ + "确认" + DQ)
    c.absent("不画 DialogTitle（那是会带单号的另一种弹层）", view, "DialogTitle")
    c.absent("不拉起任何外部页面", view, "startActivity")

    print("== 3. 不跳高德（m00542 推翻了 m00481 的旧口径） ==")
    viewmap_files = [rel for rel, src in ui if "viewMap" in src]
    c.ok("全仓没有 viewMap 那条旧口径（旧实现已撤掉，不留半条路）", viewmap_files == [], f"实际 {viewmap_files}")
    old_files = [rel for rel, src in ui if "openAmapView" in src]
    c.ok("全仓也没有 openAmapView（撤掉的那个函数名不该留痕）", old_files == [], f"实际 {old_files}")
    c.ok("AmapUri 只剩导航一条路：openAmapNavigation 在",
         "fun openAmapNavigation(context: Context, lng: String?, lat: String?, name: String?) {" in amap)
    c.ok("route 深链逐字未动（dlat / dlon / dname / style=0）",
         (DQ + "androidamap://route?sourceApplication=sorders&dev=0&t=0" + DQ + " +") in amap
         and (DQ + "&dlat=" + DQ + " + dLat + " + DQ + "&dlon=" + DQ + " + dLng + " + DQ + "&dname=" + DQ + " + dName + " + DQ + "&style=0") in amap)
    c.ok("H5 导航页仍是唯一那条回退（navigation?mode=car&policy=1）",
         (DQ + "https://uri.amap.com/navigation?mode=car&policy=1&src=sorders&coordinate=gaode&callnative=1" + DQ) in amap)
    marker_files = [rel for rel, src in ui if "uri.amap.com/marker" in src]
    c.ok("高德的 marker 标注页全仓 0 处（回退页不许被改成 marker）", marker_files == [], f"实际 {marker_files}")
    c.ok("applyMapType 在 AmapPicker.kt 里仍恰好 2 处（既有红线的口径没被改松）",
         picker.count("AmapMapHolder.applyMapType(") == 2, f"实际 {picker.count(chr(65)+chr(109)+chr(97)+chr(112)+chr(77)+chr(97)+chr(112)+chr(72)+chr(111)+chr(108)+chr(100)+chr(101)+chr(114)+chr(46)+chr(97)+chr(112)+chr(112)+chr(108)+chr(121)+chr(77)+chr(97)+chr(112)+chr(84)+chr(121)+chr(112)+chr(101)+chr(40))} 处")
    c.ok("既有那条判据还在（_check_map_picker.py 里数 applyMapType 的那句）",
         'src.count("AmapMapHolder.applyMapType(")' in read(MAP_PICKER_CHECK))
    c.ok("applyMapType 在这个弹层里恰好 2 处（打开时一次、切图层一次）",
         view.count("AmapMapHolder.applyMapType(") == 2, f"实际 {view.count(chr(65)+chr(109)+chr(97)+chr(112)+chr(77)+chr(97)+chr(112)+chr(72)+chr(111)+chr(108)+chr(100)+chr(101)+chr(114)+chr(46)+chr(97)+chr(112)+chr(112)+chr(108)+chr(121)+chr(77)+chr(97)+chr(112)+chr(84)+chr(121)+chr(112)+chr(101)+chr(40))} 处")

    print("== 4. 入口＝收货信息卡里地址那一行（有坐标整行可点） ==")
    c.ok("先确认切到了收货信息卡里那一段", len(card) > 200, f"切出来 {len(card)} 字符")
    c.ok("闸门逐字在地址那一行里：" + COORDS_GATE, COORDS_GATE in card)
    c.ok("整行可点：modifier = if (hasCoords) {", "modifier = if (hasCoords) {" in card)
    c.ok("点下去只是把本地那个开关打开：" + SHOW, SHOW in card)
    c.ok("闸门在点击之前（没坐标就整行不可点，不是靠开关兜）",
         0 <= card.find(COORDS_GATE) < card.find(SHOW))
    c.absent("闸门不许写成 if (true) {", card, "if (true) {")
    c.ok("开关是 remember 出来的本地状态（不落库、不进 VM）",
         "var showPlaceMap by remember { mutableStateOf(false) }" in screen)
    c.ok("弹层在渲染块里被点名（标题就是这一单的收货地址）", VIEW_CALL in card)
    c.ok("渲染闸门与解析兜底都在（拿不到坐标就不开一张空地图）",
         "if (showPlaceMap) {" in card
         and "val placeLat = order.addressLat?.toDoubleOrNull()" in card
         and "val placeLng = order.addressLng?.toDoubleOrNull()" in card
         and "if (placeLat != null && placeLng != null) {" in card)
    c.ok("关弹层只是把开关复位", "onDismiss = { showPlaceMap = false }" in card)

    print("== 5. 只读：这一段里没有任何写操作 ==")
    c.absent("不碰 VM", card, "vm.")
    c.absent("不碰容器", card, "container.")
    c.absent("不碰仓库", card, "repo.")
    c.absent("没有保存", card, ".saveEdit")
    c.absent("没有提交", card, ".submit")
    c.absent("这一段里不出现高德深链", card, "androidamap")
    c.ok("这一段的弹层调用恰好 1 处", card.count(VIEW_CALL) == 1, f"实际 {card.count(chr(65)+chr(109)+chr(97)+chr(112)+chr(86)+chr(105)+chr(101)+chr(119)+chr(68)+chr(105)+chr(97)+chr(108)+chr(111)+chr(103)+chr(40))} 处")

    print("== 6. 闸门与既有那块逐字一致 ＋ 既有的三样东西没被碰 ==")
    c.ok("闸门这句在客户端恰好 2 处（地址行 ＋ NavigationBlock），没有第二套写法",
         screen.count(COORDS_GATE) == 2, f"实际 {screen.count(COORDS_GATE)} 处")
    c.ok("NavigationBlock 的三种状态文案都还在",
         (DQ + "导航可用" + DQ in screen) and (DQ + "我到了，补导航" + DQ in screen) and (DQ + "司机到场补录" + DQ in screen))
    c.ok("NavigationBlock 仍是按 hasCoords / canFill / else 三分支",
         "hasCoords -> Row(verticalAlignment = Alignment.CenterVertically) {" in screen
         and "canFill -> Column {" in screen)
    c.ok("司机那颗「高德导航」按钮的调用点逐字未动：" + NAV_CALL, NAV_CALL in screen)
    c.ok("它仍挂在 onNavigate 上（按钮本体没被换）", "onClick = onNavigate" in screen)
    c.absent("详情页里不再出现高德深链（看一眼不再跳出 App）", screen, "androidamap")

    print("== 7. 行尾那颗「看地图」＋ 全仓调用点计数 ==")
    look_body = between(screen, "private fun MapLookHint() {", "@Composable")
    c.ok("MapLookHint 的定义在", len(look_body) > 40, f"切出来 {len(look_body)} 字符")
    c.ok("它画的就是「看地图」三个字", DQ + "看地图" + DQ in look_body)
    c.absent("它自己**不带** onClick（一行里两颗按键，用户分不清点哪儿）", look_body, "onClick")
    c.absent("它自己**不带** clickable（热区是整行）", look_body, "clickable")
    c.ok("四颗「改」仍是四颗、且全挂在 canEditInfo 后面（这次的入口不是 EditHint）",
         screen.count("EditHint(") == 4 and screen.count("if (canEditInfo) EditHint(") == 4,
         f"EditHint={screen.count(chr(69)+chr(100)+chr(105)+chr(116)+chr(72)+chr(105)+chr(110)+chr(116)+chr(40))}")
    c.ok("既有红线 _check_detail_inline_edit.py 那两条判据还在（四颗 / 全仓调用点）",
         "n_gated == 4 and n_any == 4" in read(DETAIL_EDIT_CHECK))
    callers = sorted((rel, src.count(VIEW_CALL)) for rel, src in ui if src.count(VIEW_CALL) > 0)
    c.ok("弹层调用点恰好两处：详情页那 1 处 ＋ 定义文件 1 处",
         callers == [("ui/common/AmapViewDialog.kt", 1), ("ui/order/OrderDetailScreen.kt", 1)],
         f"实际 {callers}（多出来的地方也会点开地图）")
    c.ok("定义只有一份（没有第二个 AmapViewDialog 函数）",
         sum(src.count("fun AmapViewDialog(") for _, src in ui) == 1)
    c.ok("详情页里没有裸 Dialog(（既有红线 _check_image_preview.py 的口径）",
         re.search(r"(?<![\w.])Dialog\(", screen) is None)

    print("== 8. 文档 / 反验 / 防静默空转 ==")
    chg = read(CHG)
    c.ok("CHG-0053.md 在", len(chg) > 500, f"{len(chg)} 字符")
    c.ok("它点了台账 L-18 与两条用户口径（m00481 / m00542，后者为准）",
         ("L-18" in chg) and ("m00481" in chg) and ("m00542" in chg))
    c.ok("它写明了最后落的是 App 内只读地图（AmapViewDialog），不是跳高德",
         ("AmapViewDialog" in chg) and ("只读" in chg))
    c.ok("它写明了「看一眼」与「导航」是两件事", ("看一眼" in chg) and ("导航" in chg))
    c.ok("它的 Boundary 结论逐字宣布 PRESENTATION（本事项没碰 Core）",
         "- **结论**：**PRESENTATION（展示层）**" in chg)
    c.ok("它记了「没坐标不给入口」这条口径", "没坐标不给入口" in chg)
    c.ok("README 登记簿有 CHG-0053 行", "[CHG-0053.md](CHG-0053.md)" in read(README))
    c.ok("AI_WORK_CLAIM 有本事项条目", "会话：**CHG-0053" in read(CLAIM))
    rvsrc = read(REVERSE)
    n_inj = rvsrc.count(chr(10) + "    (" + chr(10))
    c.ok("反验脚本在，且注入表至少 12 条", n_inj >= 12, f"实际 {n_inj} 条")
    c.ok(f"扫到的 .kt 有 {len(kts)} 份（>= {MIN_KT}）", len(kts) >= MIN_KT)
    for f in REQUIRED_FILES:
        c.ok("关键文件在：" + f.relative_to(ROOT).as_posix(), f.exists())

    print()
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print(f"  - {f}")
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
