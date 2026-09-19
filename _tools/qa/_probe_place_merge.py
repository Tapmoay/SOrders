"""合并行为验证：同一位置补两次 → 共享地点库里只有一条（**真代码、真库**）。

## 为什么单独一个脚本（而不是只靠单测）
合并是这套功能里唯一"判据错了也不报错"的地方：
- 判据写宽了 → 会把**隔壁那家店**吃掉（两个地方变成一个，谁也发现不了）；
- 判据写窄了 → 库里慢慢攒出一堆差几米的重复项，用户看到的是"合了跟没合一样"。

所以这里把**四种组合**都打一遍，并且**两侧都验**（该合的必须合、不该合的必须不合）。
单测（`backend/tests/test_place_library.py`）用的是测试库；这个脚本默认打
**跑着的那套后端**（本地 `:8000`），验的是"真的连起来是这样"。

## 两种模式（自动选，且**会明说**用的哪一种）
1. 后端在跑 → 打 `http://127.0.0.1:8000/api/v1/places`，走完整链路（含鉴权/出参）；
2. 后端没起 → **退回进程内**：同一份 `place_service` + 一个临时 SQLite 库。
   判据仍然只有一处实现（`place_service.MERGE_METERS`），两种模式验的是同一段代码。
   静默降级成"其实什么都没验"是最坏的结果，所以模式一定打印出来。

清理：脚本只删自己造的那几条（名字带 `合并验证点-勿用` 前缀），不碰别人的数据。

用法：`python _tools/qa/_probe_place_merge.py [--http|--in-process]`
"""
from __future__ import annotations

import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
B = "http://127.0.0.1:8000/api/v1"
DB = BACKEND / "sorders.db"

PREFIX = "合并验证点-勿用"
# 一个不会被别的脚本碰到的点（内蒙古阿拉善左旗附近的荒地）
LAT = 38.8123456
LNG = 105.8234567
DEG_0_89M = 0.0000080   # ≈ 0.89 米：坐标规则必须合并
DEG_6_7M = 0.0000600    # ≈ 6.7 米：真实 GPS 漂移量级，同名必须合并、异名不许合并

#: (名字, 纬度偏移, 期望是否合并, 说明)
CASES = [
    (PREFIX, 0.0, False, "第一个点：新建"),
    (PREFIX, DEG_0_89M, True, "坐标差 0.89 米：必须并入"),
    # 坐标规则优先于名字规则：同一个坐标（≤1 米）**不管叫什么**都是同一个点
    (PREFIX + "-异名同坐标", DEG_0_89M, True, "同坐标（0.89 米）异名：仍并入"),
    (PREFIX, DEG_6_7M, True, "同名 + 6.7 米（GPS 漂移量级）：必须并入"),
    # 这条才是「隔壁那家店」的护栏
    (PREFIX + "-隔壁", DEG_6_7M, False, "异名 + 6.7 米：不许并（否则吃掉隔壁那家）"),
]


def http_available() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3):
            return True
    except Exception:
        return False


class HttpSink:
    """打真后端。"""

    name = "HTTP（真后端 :8000，含鉴权与出参）"

    def __init__(self) -> None:
        self.token = ""
        s, d = self._req("POST", "/auth/login", {"username": "13800000001", "password": "123321"})
        assert s == 200, f"登录失败 {s} {d}"
        self.token = d["access_token"]

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(B + path, data=data, method=method)
        r.add_header("Content-Type", "application/json")
        if self.token:
            r.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw or b"{}")
            except Exception:
                return e.code, {"raw": raw.decode("utf-8", "replace")}

    def put(self, name: str, lat: float, lng: float) -> tuple[int, bool]:
        s, d = self._req("POST", "/places", {"name": name, "address_lat": lat, "address_lng": lng})
        return s, bool(d.get("merged"))

    def rows(self) -> list[tuple]:
        con = sqlite3.connect(DB)
        try:
            return list(
                con.execute(
                    "SELECT id,name,lat,lng,use_count FROM places WHERE name LIKE ? ORDER BY id",
                    (PREFIX + "%",),
                )
            )
        finally:
            con.close()

    def cleanup(self) -> int:
        con = sqlite3.connect(DB)
        try:
            n = con.execute("DELETE FROM places WHERE name LIKE ?", (PREFIX + "%",)).rowcount
            con.commit()
            return n
        finally:
            con.close()


class InProcessSink:
    """后端没起时的退路：同一份 `place_service` + 临时 SQLite 库。"""

    name = "进程内（同一份 place_service + 临时 SQLite）"

    def __init__(self) -> None:
        import tempfile

        sys.path.insert(0, str(BACKEND))
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        import app.models  # noqa: F401 — 注册所有表
        from app.models.base import Base

        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._engine = create_engine(f"sqlite:///{self._tmp.name}")
        Base.metadata.create_all(bind=self._engine)
        self._db = sessionmaker(bind=self._engine, autoflush=False)()
        from app.services import place_service

        self._svc = place_service

    def put(self, name: str, lat: float, lng: float) -> tuple[int, bool]:
        _, merged = self._svc.upsert_place(
            self._db, lat=lat, lng=lng, name=name, detail_address=name, source="dispatcher"
        )
        self._db.commit()
        return 201, merged

    def rows(self) -> list[tuple]:
        from app.models import Place

        return [
            (r.id, r.name, float(r.lat), float(r.lng), r.use_count)
            for r in self._db.query(Place).order_by(Place.id).all()
        ]

    def cleanup(self) -> int:
        return 0


def main() -> int:
    if "--in-process" in sys.argv:
        sink: object = InProcessSink()
    elif "--http" in sys.argv:
        if not http_available():
            print("❌ 指定了 --http 但后端没在 :8000 上跑")
            return 1
        sink = HttpSink()
    else:
        sink = HttpSink() if http_available() else InProcessSink()
    print(f"模式：{sink.name}\n")  # type: ignore[attr-defined]

    removed = sink.cleanup()  # type: ignore[attr-defined]
    if removed:
        print(f"（清掉上次留下的 {removed} 条）")

    bad = 0
    for name, off, want, why in CASES:
        status, got = sink.put(name, LAT + off, LNG)  # type: ignore[attr-defined]
        if status not in (200, 201):
            print(f"  ✗ {why}: HTTP {status}")
            bad += 1
            continue
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'✓' if ok else '✗'} {why}: merged={got}（期望 {want}）")

    rows = sink.rows()  # type: ignore[attr-defined]
    print("\n库里剩下的：")
    for r in rows:
        print("   ", r)

    # 第一个坐标簇（含异名同坐标）应当只有 1 条、use_count = 4（新建 1 + 并入 3）
    cluster = [r for r in rows if not r[1].endswith("-隔壁")]
    if len(cluster) != 1:
        print(f"  ✗ 同一坐标簇应当只有 1 条，实际 {len(cluster)} 条")
        bad += 1
    elif cluster[0][4] != 4:
        print(f"  ✗ use_count 应当是 4（新建 1 + 并入 3），实际 {cluster[0][4]}")
        bad += 1
    else:
        print("  ✓ 同一坐标簇 1 条、use_count=4（三次并入都记上了）")

    if len(rows) != 2:
        print(f"  ✗ 总共应当 2 条（坐标簇 + 隔壁异名），实际 {len(rows)} 条")
        bad += 1
    else:
        print("  ✓ 异名 + 6.7 米那条独立存在（隔壁那家店没被吃掉）")

    if isinstance(sink, HttpSink):
        n = sink.cleanup()
        print(f"\n（已清掉本次造的 {n} 条）")

    print("\n结果：", "全部通过" if bad == 0 else f"{bad} 项不符")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
