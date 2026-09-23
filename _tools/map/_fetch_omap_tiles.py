"""从**奥维互动地图的 Web 瓦片服务**批量抓瓦片 → 标准 XYZ 目录（供 App 离线高清图层用）。

## 为什么要走奥维，而不是直接读文件（2026-09-23 实测结论）

用户的「谷歌高清图源」落在 `D:\\APPS\\map\\310\\`，18 个 `<图源>_<z>_<块x>_<块y>.sdb`，1.84 GB。
**它是加密容器，不能直接解包** —— 三份文件独立数学校验，JPEG 签名命中数与随机期望值同量级：

| 文件 | 大小 | JPEG 标记 | 随机期望 |
|---|---|---|---|
| `mapcache.sdb` | 85.91 MB | 5 | 5 |
| `mapcachegh.sdb` | 0.73 MB | 0 | 0 |
| `310_15_0105_0053.sdb` | 290.9 MB | 26 | ~18 |

唯一出口是奥维**自己**把瓦片吐出来（它本就要解密才能显示）：

    http://127.0.0.1:<port>/getomap_310_{z}_{x}_{y}_{ext}_{time}.jpg

出处：官方帮助《如何在奥维中启用WEB瓦片服务》 https://www.ovital.com/132277-2/
  · `{ext}`：0=只发卫星地图 / 1=地图+叠加层+奥维对象 / 2=只发奥维对象 / 3=地图+路网（**不含奥维对象**）
  · `{time}`：`yyyyMMdd` 只对历史影像有效；**填 0 = 取当前最新**
  · `{x}/{y}` 是**标准 Web Mercator XYZ**（与高德同为 GCJ-02 墨卡托，故 App 侧不用做坐标转换）

## 为什么 ext 默认 0（不是 3）

`ext=1` 会把**用户自己在奥维里标的标签/轨迹**一起烧进瓦片 —— 那是他的私人标注，
不该出现在 App 的地图选点里。默认 `0`（纯卫星影像）。310 图源本身是 `lyrs=y`（影像+路网合体），
所以路网注记**本来就在影像里**，不需要 ext=3。

## 分层策略（用户 2026-09-23 拍板）

| 层 | zoom | 用途 | 说明 |
|---|---|---|---|
| A | z16 | 认路（乡镇/村落/连接道路） | 每瓦片 534.8 m，覆盖大范围便宜 |
| B | z18 | 看门牌（镇区街区） | 每瓦片 133.7 m，只盖镇区建成区 |

⛔ **不要盲目上 z20**：z16→z20 是 256 倍体积；且本机离线数据只到 z16，
z17~z20 只能在线拉，而官方文档明说「18级以上仅是像素放大」。

## 用法

    # 0) 先探活（3 秒）：确认奥维服务开着、能取到真图
    python _tools/map/_fetch_omap_tiles.py --probe

    # 1) 只算量不下载
    python _tools/map/_fetch_omap_tiles.py --layer all --dry-run

    # 2) 正式抓（断点续传：已存在且校验通过的文件直接跳过）
    python _tools/map/_fetch_omap_tiles.py --layer all --out D:\\omap-tiles

    # 3) 只抓某一层 / 某几个镇
    python _tools/map/_fetch_omap_tiles.py --layer B --towns 田畈街,金领岭

## 前置条件（缺一不可）

1. 奥维 PC 端开着：**【系统】→【系统设置】→【高级】→【第三方接口】→【Web接口】→
   服务选项【启用WebSocket协议】→ 勾选【启用HTTP瓦块服务】→ 端口填 9999 → 保存**
2. 该端口防火墙放行（本机访问一般不用，跨机器才要）

## 输出

    <out>/tiles/{z}/{x}/{y}.jpg     ← 标准 XYZ 目录，可直接给 nginx / 高德 TileLayer 用
    <out>/_fetch_report.json        ← 成功/失败/跳过 计数 + 失败清单（补抓用）

## 为什么要逐个校验内容而不是只看 HTTP 200

奥维在**没有该瓦片**时不一定返回 404（源站无数据、越界、服务刚开还没加载地图都可能
回一张空白图或错误页，**状态码仍是 200**）。所以判据是三重：状态码 + `Content-Type` + JPEG magic。
抓错的东西比抓不到更糟 —— 它会静静地在 App 里显示成"地图坏了"。
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import math
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

# ── 图源与端点 ────────────────────────────────────────────────────────────
MAP_ID = "310"          # 【谷歌】高清卫星图（小字）；见 D:\APPS\map\310\310.txt
DEFAULT_PORT = 9999
EXT = 0                 # 0=只发卫星地图（见模块 docstring：为什么不带奥维对象）
TIME = 0                # 0=取当前最新
JPEG_MAGIC = b"\xff\xd8\xff"
MIN_TILE_BYTES = 512    # 比这还小基本是错误页/占位图

# ── 区域表 ────────────────────────────────────────────────────────────────
#: 乡镇/镇区中心坐标。
#: `conf` = 坐标置信度，**抓 B 层（z18 街区）前必须全部升到 "ok"** —— z18 每瓦片才 133.7 m，
#: 坐标错 1 km 就整片抓偏（而 z16 每瓦片 534.8 m，容错大得多）。
#:   ok   = 两个以上独立来源一致（或与已知距离交叉验证过）
#:   todo = 待核实（只有单一来源/推断）→ 只可参与 A 层，不许单独用于 B 层
TOWNS: dict[str, dict] = {
    # 两来源一致 + 距县城 42.5km 与 xzqh「距县城44千米」交叉验证
    "田畈街": {"lat": 29.3528, "lon": 116.8698, "conf": "ok",
             "src": "维基 29°21′10″N 116°52′11″E / abcdtools 29.352786,116.8697869"},
    "侯家岗": {"lat": 29.5215, "lon": 116.8477, "conf": "todo",
             "src": "abcdtools 29.521532,116.8477459"},
    "金盘岭": {"lat": 29.4200, "lon": 117.0000, "conf": "todo", "src": "推断（田畈街东邻）"},
    "油墩街": {"lat": 29.4300, "lon": 116.6800, "conf": "todo", "src": "推断（田畈街西靠）"},
    "凰岗":   {"lat": 29.1000, "lon": 117.0000, "conf": "todo", "src": "推断（县中东部）"},
    "谢家滩": {"lat": 29.5500, "lon": 116.7500, "conf": "todo", "src": "推断（田畈街北接）"},
    "柘港":   {"lat": 29.4000, "lon": 116.5800, "conf": "todo", "src": "推断（田畈街西靠）"},
    "游城":   {"lat": 29.2500, "lon": 116.8500, "conf": "todo", "src": "推断（田畈街南连）"},
    "鄱阳镇": {"lat": 29.0050, "lon": 116.7000, "conf": "todo", "src": "县城（粗）"},
}

#: A 层（大范围 z16）的包络：**整个鄱阳县**。
#: 为什么是全县而不是"点名的几个镇"：用户说「等等等等」，范围本就没列全；
#: 而 z16 全县也才 ~1.2 GB（他已有 1.84 GB），一次抓全比事后补抓划算得多。
COUNTY_BBOX = {"lon_min": 116.10, "lon_max": 117.07, "lat_min": 28.77, "lat_max": 29.70}

#: B 层（街区 z18）每个镇区盖多大：中心 ± 这个度数。
#: 3km×3km ≈ 0.027° 纬 / 0.031° 经 —— 覆盖一般镇区建成区。
BLOCK_HALF_LAT = 0.0135
BLOCK_HALF_LON = 0.0157


def tile_xy(lat: float, lon: float, z: int) -> tuple[float, float]:
    """WGS-84 经纬度 → Web Mercator 瓦片坐标（浮点）。"""
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def tile_center(z: int, x: int, y: int) -> tuple[float, float]:
    """瓦片坐标 → 该瓦片中心经纬度（探测时打印用）。"""
    n = 2 ** z
    lon = (x + 0.5) / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 0.5) / n))))
    return lat, lon


def tiles_for_bbox(lat_min, lat_max, lon_min, lon_max, z) -> list[tuple[int, int]]:
    """矩形包络内的全部瓦片（含边界）。注意 y 轴向南递增，故用 max_lat 取 y 的下界。"""
    x0, y0 = tile_xy(lat_max, lon_min, z)   # 左上
    x1, y1 = tile_xy(lat_min, lon_max, z)   # 右下
    xs = range(int(x0), int(x1) + 1)
    ys = range(int(y0), int(y1) + 1)
    return [(x, y) for x in xs for y in ys]


def tiles_for_zone(lat: float, lon: float, z: int) -> list[tuple[int, int]]:
    """镇区方框内的瓦片。"""
    return tiles_for_bbox(lat - BLOCK_HALF_LAT, lat + BLOCK_HALF_LAT,
                          lon - BLOCK_HALF_LON, lon + BLOCK_HALF_LON, z)


# ── 抓取 ──────────────────────────────────────────────────────────────────
@dataclass
class Report:
    ok: int = 0
    skip: int = 0
    fail: int = 0
    failed: list[str] = field(default_factory=list)
    bytes: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def hit(self, kind: str, key: str, nbytes: int = 0) -> None:
        with self.lock:
            if kind == "ok":
                self.ok += 1
                self.bytes += nbytes
            elif kind == "skip":
                self.skip += 1
            else:
                self.fail += 1
                if len(self.failed) < 2000:
                    self.failed.append(key)


def tile_url(port: int, z: int, x: int, y: int) -> str:
    return f"http://127.0.0.1:{port}/getomap_{MAP_ID}_{z}_{x}_{y}_{EXT}_{TIME}.jpg"


def fetch_one(port: int, z: int, x: int, y: int, out: Path,
              retries: int = 3, timeout: float = 20.0) -> tuple[str, bytes]:
    """抓一张瓦片。返回 (结果, 内容)。结果 ∈ ok / skip / fail:<原因>。"""
    dest = out / "tiles" / str(z) / str(x) / f"{y}.jpg"
    if dest.exists() and dest.stat().st_size >= MIN_TILE_BYTES:
        head = dest.open("rb").read(3)
        if head == JPEG_MAGIC:
            return "skip", b""

    url = tile_url(port, z, x, y)
    last = "未知"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sorders-tile-fetch/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    last = f"HTTP {resp.status}"
                else:
                    body = resp.read()
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    if len(body) < MIN_TILE_BYTES:
                        last = f"内容过小({len(body)}B) 疑似空图/错误页"
                    elif body[:3] != JPEG_MAGIC:
                        last = f"非 JPEG 开头({body[:3].hex()}) ctype={ctype or '?'}"
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        tmp = dest.with_suffix(".jpg.part")
                        tmp.write_bytes(body)
                        tmp.replace(dest)          # 原子落盘：中断不会留下半个文件
                        return "ok", body
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
        except urllib.error.URLError as e:
            last = f"连接失败({e.reason})"
        except Exception as e:                      # noqa: BLE001 - 抓取工具要能扛住任何单张失败
            last = f"{type(e).__name__}: {e}"
        if attempt < retries - 1:
            time.sleep(0.5 * (attempt + 1))
    return f"fail:{last}", b""


def probe(port: int, z: int, x: int, y: int) -> int:
    """探活：抓一张并给出人话结论。"""
    print(f"探测 {tile_url(port, z, x, y)}")
    lat, lon = tile_center(z, x, y)
    print(f"  该瓦片中心 ≈ ({lat:.5f}, {lon:.5f})  z{z}")
    result, body = fetch_one(port, z, x, y, Path("."), retries=1, timeout=15.0)
    if result in ("ok", "skip"):
        print(f"  ✅ 拿到真图（{len(body)} 字节，JPEG）—— 服务可用")
        return 0
    print(f"  ❌ {result}")
    print("  排查：① 奥维是否开着并勾了【启用HTTP瓦块服务】② 端口对不对 "
          "③ 地图数据是否已下载（D:\\APPS\\map\\310）")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="从奥维 Web 瓦片服务抓取 XYZ 瓦片")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"奥维 HTTP 瓦块服务端口（默认 {DEFAULT_PORT}）")
    ap.add_argument("--out", default=r"D:\omap-tiles", help="输出根目录（默认 D:\\omap-tiles）")
    ap.add_argument("--layer", choices=["A", "B", "all"], default="all",
                    help="A=z16 大范围 / B=z18 街区 / all")
    ap.add_argument("--towns", default="", help="逗号分隔，只抓这些镇（默认全部）")
    ap.add_argument("--workers", type=int, default=2, help="并发（默认 2，别打爆奥维）")
    ap.add_argument("--delay", type=float, default=0.05, help="每张之间的间隔秒（默认 0.05）")
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 张（0=不限，调试用）")
    ap.add_argument("--dry-run", action="store_true", help="只算量不下载")
    ap.add_argument("--probe", action="store_true", help="探活后就退出")
    args = ap.parse_args()

    if args.probe:
        x, y = (int(v) for v in tile_xy(TOWNS["田畈街"]["lat"], TOWNS["田畈街"]["lon"], 16))
        return probe(args.port, 16, x, y)

    out = Path(args.out)
    want = [t.strip() for t in args.towns.split(",") if t.strip()] or list(TOWNS)

    # ── 组任务 ──
    plan: list[tuple[int, int, int, str]] = []
    if args.layer in ("A", "all"):
        for x, y in tiles_for_bbox(COUNTY_BBOX["lat_min"], COUNTY_BBOX["lat_max"],
                                   COUNTY_BBOX["lon_min"], COUNTY_BBOX["lon_max"], 16):
            plan.append((16, x, y, "A:全县"))
    if args.layer in ("B", "all"):
        unverified: list[str] = []
        for name in want:
            t = TOWNS[name]
            if t["conf"] != "ok":
                unverified.append(name)
                continue
            for x, y in tiles_for_zone(t["lat"], t["lon"], 18):
                plan.append((18, x, y, f"B:{name}"))
        if unverified:
            # 汇总成一条：z18 每瓦片才 133.7 m、容错极小，坐标没核准就抓等于白抓
            print(f"⚠️  跳过 {len(unverified)} 个镇的 B 层（坐标未核实）：{'、'.join(unverified)}")
            print(f"   原因：z18 容错只有 133.7 m/张，坐标准确性必须先由 ≥2 个独立来源确认。")
            print(f"   这些镇**仍会**被 A 层（z16）覆盖（z16 每张 534.8 m，容错大得多）。")

    if args.limit:
        plan = plan[: args.limit]

    by_z: dict[int, int] = {}
    for z, *_ in plan:
        by_z[z] = by_z.get(z, 0) + 1
    est_mb = len(plan) * 35 / 1024                       # 35 KB/张 → MB
    per_sec = max(args.workers, 1) / max(args.delay + 0.12, 0.01)
    print(f"计划 {len(plan):,} 张：" + "  ".join(f"z{z}={n:,}" for z, n in sorted(by_z.items())))
    print(f"估算体积 ≈ {est_mb:.0f} MB（{est_mb / 1024:.2f} GB，按 35 KB/张）"
          f"   预计耗时 ≈ {len(plan) / per_sec / 60:.0f} 分钟（{args.workers} 并发）")
    print(f"输出目录 {out}")

    if args.dry_run:
        print("\n--dry-run：未下载。")
        return 0

    port_ok = probe(args.port, *plan[0][:3]) if plan else 1
    if port_ok != 0:
        print("\n⛔ 探活失败，已中止（一张都没抓）。先按上面提示把奥维的服务开起来。")
        return 1
    print()

    rep = Report()
    t0 = time.time()
    total = len(plan)

    def work(item: tuple[int, int, int, str]) -> None:
        z, x, y, _tag = item
        kind, body = fetch_one(args.port, z, x, y, out)
        rep.hit("ok" if kind == "ok" else ("skip" if kind == "skip" else "fail"),
                f"{z}/{x}/{y} {kind}", len(body))
        if args.delay:
            time.sleep(args.delay)
        done = rep.ok + rep.skip + rep.fail
        if done % 200 == 0 or done == total:
            el = time.time() - t0
            rate = done / el if el else 0
            eta = (total - done) / rate / 60 if rate else 0
            print(f"  {done:,}/{total:,}  新增{rep.ok:,} 跳过{rep.skip:,} 失败{rep.fail:,}"
                  f"  {rate:.1f}张/秒  剩≈{eta:.0f}分", flush=True)

    with cf.ThreadPoolExecutor(max_workers=max(args.workers, 1)) as pool:
        list(pool.map(work, plan))

    elapsed = time.time() - t0
    report = {
        "port": args.port, "layer": args.layer, "out": str(out),
        "total": total, "ok": rep.ok, "skip": rep.skip, "fail": rep.fail,
        "bytes": rep.bytes, "elapsed_sec": round(elapsed, 1),
        "failed": rep.failed,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "_fetch_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成：新增 {rep.ok:,} / 跳过 {rep.skip:,} / 失败 {rep.fail:,}"
          f"  用时 {elapsed / 60:.1f} 分  新增体积 {rep.bytes / 1048576:.0f} MB")
    if rep.fail:
        print(f"⚠️  {rep.fail:,} 张失败，清单见 {out / '_fetch_report.json'} 的 failed 字段"
              f"（重跑本脚本会只补这些 —— 已成功的会被跳过）")
        for line in rep.failed[:5]:
            print(f"     {line}")
    return 0 if rep.fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
