"""反向验证：把 CHG-0053 那条判据（_check_order_place_map.py）逐条弄坏，看它**真的会红**。

为什么这块必须反向验证：这条规矩坏掉的方式**全部不报错**——
- 地址那一行的 `Modifier.clickable { showPlaceMap = true }` 整段删掉：地址照旧显示、
  司机那颗「高德导航」照旧能开，编译器一声不吭（用户说的「点那个地点信息」就完全没反应了）；
- 点下去改回 `openAmapNavigation`（m00481 那条被推翻的旧口径）：一样"点一下打开一张地图"，
  只是把用户踢出 App、还依赖装了高德；
- 弹层多加一个 `onPicked` / 多一个「确认」按钮：从"看一眼"变成"能改坐标"，
  而口径明写「不会产生任何返回结果」；
- 少摘一次 marker：地图是进程内单例，会叠着上一单的点、还会污染后面打开的**选点**弹层；
- `onPause` 写成 `onDestroy`：高德 9.8.3 在 Android 15+/16 arm64 上当场 native SIGABRT。

机器判据本身几乎全是"读源码里有没有那一行"，这种判据如果不反向验证，就可能因为名字改了、
文件搬了、正则写松了而**永远绿**。

用法：python _tools/qa/_reverse_verify_order_place_map.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_order_place_map.py"

AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
SCREEN = AND / "ui/order/OrderDetailScreen.kt"
AMAP = AND / "util/AmapUri.kt"
VIEW = AND / "ui/common/AmapViewDialog.kt"
CHG = ROOT / "docs/changes/CHG-0053.md"
README = ROOT / "docs/changes/README.md"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "弹层长出选点出口（看一眼变成能改坐标）",
        VIEW,
        "fun AmapViewDialog(\n    lat: Double,",
        "fun AmapViewDialog(\n    onPicked: (Double, Double) -> Unit,\n    lat: Double,",
        "没有 onPicked",
    ),
    (
        "弹层不再复用那份地图单例（自己 new 一个 MapView）",
        VIEW,
        "    val mapView = remember { AmapMapHolder.get(context.applicationContext) }",
        "    val mapView = remember { com.amap.api.maps.MapView(context.applicationContext) }",
        "复用同一份地图单例",
    ),
    (
        "目标点不再落在这一单的坐标上（写死 0,0 = 看的是几内亚湾）",
        VIEW,
        "            val opts = MarkerOptions().position(LatLng(lat, lng))",
        "            val opts = MarkerOptions().position(LatLng(0.0, 0.0))",
        "目标点是**真 marker**",
    ),
    (
        "关弹层不摘自己那枚 marker（单例地图上会叠着上一单的点）",
        VIEW,
        "            clearPlaceMarker()\n            try { mapView.onPause() } catch (_: Exception) {}",
        "            try { mapView.onPause() } catch (_: Exception) {}",
        "关弹层再清一次",
    ),
    (
        "关闭改成 onDestroy（高德 9.8.3 在 Android 15+/16 arm64 上 native SIGABRT）",
        VIEW,
        "            try { mapView.onPause() } catch (_: Exception) {}",
        "            try { mapView.onDestroy() } catch (_: Exception) {}",
        "永不 onDestroy",
    ),
    (
        "顶栏那颗「关闭」改成「确认」（从看一眼变成能落一个结果）",
        VIEW,
        "                    TextButton(onClick = onDismiss) { Text(\"关闭\") }",
        "                    TextButton(onClick = onDismiss) { Text(\"确认\") }",
        "没有「确认」口",
    ),
    (
        "注册点击选点（点哪儿就把哪儿的坐标当结果）",
        VIEW,
        "        try { aMap.moveCamera(CameraUpdateFactory.newLatLngZoom(LatLng(lat, lng), 16f)) } catch (_: Exception) {}",
        "        try { aMap.moveCamera(CameraUpdateFactory.newLatLngZoom(LatLng(lat, lng), 16f)) } catch (_: Exception) {}\n        aMap.setOnMapClickListener { p -> aMap.moveCamera(CameraUpdateFactory.newLatLng(p)) }",
        "不注册点击选点",
    ),
    (
        "标题不再截断（长地址把顶栏撑爆）",
        VIEW,
        "                        maxLines = 2,\n                        overflow = TextOverflow.Ellipsis,",
        "",
        "标题会截断且带省略号",
    ),
    (
        "导航深链被改回 viewMap（m00481 那条被推翻的旧口径漏改回来）",
        AMAP,
        "    val scheme = \"androidamap://route?sourceApplication=sorders&dev=0&t=0\" +",
        "    val scheme = \"androidamap://viewMap?sourceApplication=sorders\" +",
        "route 深链逐字未动",
    ),
    (
        "没装高德时的回退页改成 marker 标注页",
        AMAP,
        "    val base = \"https://uri.amap.com/navigation?mode=car&policy=1&src=sorders&coordinate=gaode&callnative=1\"",
        "    val base = \"https://uri.amap.com/marker?src=sorders&coordinate=gaode&callnative=1\"",
        "marker 标注页全仓 0 处",
    ),
    (
        "司机那颗「高德导航」按钮被换成只读弹层（导航没了）",
        SCREEN,
        "openAmapNavigation(context, vm.order?.addressLng, vm.order?.addressLat, vm.order?.addressDetail)",
        "AmapViewDialog(lat = 0.0, lng = 0.0, title = \"\", onDismiss = {})",
        "调用点逐字未动",
    ),
    (
        "地址那一行整段不可点（用户说的「点那个地点信息」没有任何反应）",
        SCREEN,
        "                        modifier = if (hasCoords) {\n                            Modifier.clickable { showPlaceMap = true }\n                        } else Modifier,",
        "                        modifier = Modifier,",
        "整行可点",
    ),
    (
        "闸门写成 if (true)（没坐标的订单也能点开）",
        SCREEN,
        "                        modifier = if (hasCoords) {",
        "                        modifier = if (true) {",
        "闸门不许写成 if (true) {",
    ),
    (
        "点下去改回跳高德（旧口径回归：一样能打开地图，只是把用户踢出 App）",
        SCREEN,
        "                            Modifier.clickable { showPlaceMap = true }",
        "                            Modifier.clickable {\n                                openAmapNavigation(ctx, order.addressLng, order.addressLat, order.addressDetail)\n                            }",
        "点下去只是把本地那个开关打开",
    ),
    (
        "解析兜底放宽成 ||（半个坐标也开弹层：目标点落在赤道上）",
        SCREEN,
        "                    if (placeLat != null && placeLng != null) {",
        "                    if (placeLat != null || placeLng != null) {",
        "渲染闸门与解析兜底都在",
    ),
    (
        "弹层被换成选点弹层（看一眼变成能改坐标）",
        SCREEN,
        "                        AmapViewDialog(\n                            lat = placeLat,\n                            lng = placeLng,\n                            title = order.addressDetail,\n                            onDismiss = { showPlaceMap = false },\n                        )",
        "                        AmapPickerDialog(\n                            container = container,\n                            initialLat = placeLat,\n                            initialLng = placeLng,\n                            onPicked = { _, _, _ -> },\n                            onDismiss = { showPlaceMap = false },\n                        )",
        "弹层在渲染块里被点名",
    ),
    (
        "关弹层顺手写一次仓库（只读的那一下长出写操作）",
        SCREEN,
        "                            onDismiss = { showPlaceMap = false },",
        "                            onDismiss = { showPlaceMap = false; repo.saveEdit() },",
        "不碰仓库",
    ),
    (
        "地址行的闸门就地写成恒真（与 NavigationBlock 那句不再是同一句）",
        SCREEN,
        "                    val hasCoords = !order.addressLat.isNullOrBlank() && !order.addressLng.isNullOrBlank()",
        "                    val hasCoords = true",
        "闸门逐字在地址那一行里",
    ),
    (
        "行尾那颗「看地图」长成第二颗按钮（一行两颗按键分不清点哪儿）",
        SCREEN,
        "        style = MaterialTheme.typography.bodyMedium,\n        color = MaterialTheme.colorScheme.primary,\n        modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),",
        "        style = MaterialTheme.typography.bodyMedium,\n        color = MaterialTheme.colorScheme.primary,\n        modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp).clickable { },",
        "它自己**不带** clickable",
    ),
    (
        "CHG 的 Boundary 结论改口成 CORE",
        CHG,
        "- **结论**：**PRESENTATION（展示层）**",
        "- **结论**：**CORE（核心层）**",
        "Boundary 结论逐字宣布 PRESENTATION",
    ),
    (
        "README 登记簿那行改成死链",
        README,
        "[CHG-0053.md](CHG-0053.md)",
        "[CHG-0053.md](#)",
        "README 登记簿有 CHG-0053 行",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out


def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**：写回后重新读回来逐字节比，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        raise SystemExit(2)


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            hit, detail = verdict(expect)
        finally:
            restore_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
