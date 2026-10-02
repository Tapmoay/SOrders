#!/usr/bin/env python3
"""_upload_tiles.py —— 把本地抓好的自备高清瓦片整批送上生产服务器。

### 背景（FEAT-0006）
地图选点在 z19/z20 要显示自备影像（高德本区域原生只到 z18，z19/z20 是灰底占位），
瓦片必须先落到服务器上。本地目录形如 `<src>/<z>/<x>/<y>.jpg`（标准 XYZ），
**与高德同网格**，所以上传就是原样搬运 —— ⛔ 不做任何坐标换算。

### 为什么按 x 目录分批，而不是整包一条管道
整包 6.4 GB / 735,194 个小文件走一条 `tar | ssh`，中途任何一次网络抖动都会毁掉
**整次**传输（tar 不支持断点续传）。按「累计约 `--batch-mb` 兆」切批，
失败只损失一批；重跑幂等（同名文件直接覆盖）。

### 为什么用 Popen 直接对接 tar.stdout → ssh.stdin
少一层 shell 就少一层转义/编码风险。⛔ 不要走 `cmd /c "tar … | ssh …"`，
更⛔ 不要走 PowerShell 的管道 —— 它是文本导向的，会把二进制流写坏
（本仓记过同形状的坑；实测 `cmd` 那条路可行但引号极易出错，Popen 不需要引号）。

### 三条纪律（照 `_tools/ops/_prodssh.py`）
1. ⛔ 生产主机 / 用户 / 密钥路径**只从 `_prodssh` 来**，本文件不写第二份。
2. ⛔ **默认 dry-run**：不加 `--apply` 只打印计划，一个字节都不传。
3. ⛔ **不吞错误**：tar 与 ssh 的退出码都要检查，失败立刻停下并报告是第几批。

### 用法
    # 只看计划（默认，不传任何东西）
    python _tools/map/_upload_tiles.py --src "D:\\…\\tiles_z20_final" --zoom 20

    # 只对账（本地 vs 服务器）
    python _tools/map/_upload_tiles.py --src "D:\\…\\tiles_z20_final" --zoom 20 --status

    # 真传（跳过服务器上已经完整的 x 目录）
    python _tools/map/_upload_tiles.py --src "D:\\…\\tiles_z20_final" --zoom 20 --apply
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ops"))
import _prodssh  # noqa: E402  —— 生产事实的唯一出处

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:                                     # noqa: BLE001
    pass

REMOTE_ROOT = f"{_prodssh.APP_DIR}/tiles"


def _local_scan(zoom_dir: Path) -> dict[str, tuple[int, int]]:
    """{x 目录名: (文件数, 字节数)}。

    ⚠️ **必须用 `os.scandir`，不要用 `Path.iterdir()` + `is_file()` + `stat()`**：
    后者是**每个文件两次 stat 系统调用**，73.5 万个文件在 Windows 上（叠加 Defender
    实时扫描）实测十几分钟都跑不完；`os.scandir` 的 `DirEntry` 在 Windows 上直接复用
    目录枚举已经返回的大小与属性，**零额外系统调用**（跑完只要几秒）。
    """
    out: dict[str, tuple[int, int]] = {}
    with os.scandir(zoom_dir) as it:
        for d in it:
            if not d.is_dir(follow_symlinks=False) or not d.name.isdigit():
                continue
            n = 0
            b = 0
            with os.scandir(d.path) as fit:
                for f in fit:
                    if not f.is_file(follow_symlinks=False):
                        continue
                    if not f.name.lower().endswith((".jpg", ".jpeg", ".png")):
                        continue
                    n += 1
                    b += f.stat(follow_symlinks=False).st_size
            if n:
                out[d.name] = (n, b)
    return out


def _remote_scan(zoom: str) -> dict[str, int]:
    """{x 目录名: 文件数}。一条 find + awk，⛔ 不要每个目录起一次 find（1078 次太慢）。"""
    script = (
        f"if [ -d {REMOTE_ROOT}/{zoom} ]; then "
        f"find {REMOTE_ROOT}/{zoom} -type f -name '*.jpg' "
        f"| awk -F/ '{{print $(NF-1)}}' | sort | uniq -c "
        f"| awk '{{print $2, $1}}'; fi"
    )
    out: dict[str, int] = {}
    for ln in _prodssh.ssh_lines(script, timeout=180):
        parts = ln.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            out[parts[0]] = int(parts[1])
    return out


def _batch_by_bytes(items: list[tuple[str, int, int]], target_mb: float):
    """按累计字节切批，让每批体积接近 —— x 目录的文件数从 1 到 1026 不等，
    按目录个数切会让批次大小差 1000 倍。"""
    target = target_mb * 1024 * 1024
    cur: list[str] = []
    cur_b = 0
    for name, _n, b in items:
        cur.append(name)
        cur_b += b
        if cur_b >= target:
            yield cur
            cur, cur_b = [], 0
    if cur:
        yield cur


def _upload_one_batch(local_root: Path, zoom: str, xs: list[str], mb: float, idx: int, total: int) -> None:
    """一批 = 一次 tar | ssh。tar 从本地根出发带上 `<zoom>/<x>` 相对路径，
    远端解到 REMOTE_ROOT，于是落点自然是 `<REMOTE_ROOT>/<zoom>/<x>/<y>.jpg`。"""
    rel = [f"{zoom}/{x}" for x in xs]
    remote = f"mkdir -p {REMOTE_ROOT} && tar -xf - -C {REMOTE_ROOT}"

    print(f"  [{idx}/{total}] {len(xs)} 个 x 目录 / {mb:.0f} MB  {rel[0]} … {rel[-1]}", flush=True)
    t0 = time.time()

    # ⚠️ tar 的 stderr 走**临时文件**而不是 PIPE：tar.stdout 已经交给 ssh 了，
    #    再用 communicate() 去读它会炸（`ValueError: read of closed file`，实测踩过）；
    #    而 stderr 留成没人读的 PIPE 又有"写满 64KB 把 tar 卡死"的风险。
    #    临时文件两头都不占。
    with tempfile.TemporaryFile() as tar_err_f:
        tar = subprocess.Popen(
            ["tar", "-cf", "-", "-C", str(local_root), *rel],
            stdout=subprocess.PIPE, stderr=tar_err_f,
        )
        try:
            ssh = subprocess.Popen(
                ["ssh", *_prodssh.SSH_COMMON, f"{_prodssh.PROD_USER}@{_prodssh.PROD_HOST}", remote],
                stdin=tar.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        finally:
            assert tar.stdout is not None
            tar.stdout.close()                        # 让 tar 收到 EPIPE 时能自己收尾

        ssh_out, ssh_err = ssh.communicate()
        tar_rc = tar.wait()
        tar_err_f.seek(0)
        tar_err = tar_err_f.read()

    if tar_rc != 0:
        raise SystemExit(f"⛔ 第 {idx} 批 tar 失败（exit {tar_rc}）："
                         f"{tar_err.decode('utf-8', 'replace')[-800:]}")
    if ssh.returncode != 0:
        raise SystemExit(f"⛔ 第 {idx} 批 ssh/远端 tar 失败（exit {ssh.returncode}）："
                         f"{ssh_err.decode('utf-8', 'replace')[-800:]}")

    el = time.time() - t0
    rate = mb / el if el > 0 else 0
    print(f"         ✅ {el:.0f}s  {rate:.1f} MB/s"
          + (f"  {ssh_out.decode('utf-8', 'replace').strip()}" if ssh_out.strip() else ""), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="把本地自备瓦片送上生产服务器（默认 dry-run）")
    ap.add_argument("--src", required=True, help="本地瓦片根目录（其下有 <zoom>/<x>/<y>.jpg）")
    ap.add_argument("--zoom", required=True, help="要传的层级目录名，如 20")
    ap.add_argument("--batch-mb", type=float, default=400.0, help="每批约多少 MB（默认 400）")
    ap.add_argument("--apply", action="store_true", help="真的传；不加只打印计划")
    ap.add_argument("--status", action="store_true", help="只对账本地 vs 服务器，不传")
    ap.add_argument("--force", action="store_true",
                    help="连服务器上已经完整的 x 目录也重传（默认跳过）")
    args = ap.parse_args()

    local_root = Path(args.src).expanduser().resolve()
    zoom_dir = local_root / args.zoom
    if not zoom_dir.is_dir():
        raise SystemExit(f"⛔ 本地没有这个层级目录：{zoom_dir}")

    print(f"本地根   : {local_root}")
    print(f"层级     : {args.zoom}")
    print(f"远端根   : {_prodssh.PROD_HOST}:{REMOTE_ROOT}/{args.zoom}")
    print()

    print("扫描本地…", flush=True)
    loc = _local_scan(zoom_dir)
    loc_n = sum(n for n, _ in loc.values())
    loc_b = sum(b for _, b in loc.values())
    print(f"  本地: {len(loc)} 个 x 目录 / {loc_n:,} 个文件 / {loc_b / 1048576:.1f} MB")

    print("扫描远端…", flush=True)
    rem = _remote_scan(args.zoom)
    rem_n = sum(rem.values())
    print(f"  远端: {len(rem)} 个 x 目录 / {rem_n:,} 个文件")

    if args.status:
        missing = {x: nb[0] for x, nb in loc.items() if rem.get(x, 0) < nb[0]}
        print(f"\n对账：{len(loc) - len(missing)}/{len(loc)} 个 x 目录已完整，{len(missing)} 个还需要传")
        if missing:
            need = sum(loc[x][1] for x in missing)
            print(f"  还需约 {need / 1048576:.1f} MB")
        return 0

    todo = [(x, n, b) for x, (n, b) in sorted(loc.items())
            if args.force or rem.get(x, 0) < n]
    todo_b = sum(b for _, _, b in todo)
    batches = list(_batch_by_bytes(todo, args.batch_mb))

    print(f"\n计划：{len(todo)} 个 x 目录 / {todo_b / 1048576:.1f} MB / {len(batches)} 批"
          f"（每批约 {args.batch_mb:.0f} MB）")
    if not todo:
        print("✅ 服务器上已经全了，不用传。")
        return 0

    if not args.apply:
        for i, b in enumerate(batches, 1):
            mb = sum(loc[x][1] for x in b) / 1048576
            print(f"  批 {i:>2}: {len(b):>4} 个 x 目录  {mb:>7.1f} MB  {b[0]} … {b[-1]}")
        print("\n（dry-run：什么都没有传。加 --apply 才真传。）")
        return 0

    print()
    t0 = time.time()
    for i, b in enumerate(batches, 1):
        mb = sum(loc[x][1] for x in b) / 1048576
        _upload_one_batch(local_root, args.zoom, b, mb, i, len(batches))

    el = time.time() - t0
    print(f"\n全部完成：{todo_b / 1048576:.1f} MB / {el:.0f}s（{todo_b / 1048576 / max(el, 1):.1f} MB/s）")
    print("复核：python _tools/map/_upload_tiles.py "
          f'--src "{args.src}" --zoom {args.zoom} --status')
    return 0


if __name__ == "__main__":
    sys.exit(main())
