"""离线画一遍凹口的路径（与 `ui/nav/NotchedNavBar.kt` 的公式逐条对应），用来做两件事：

1. **肉眼看过渡连上没有**：弧接反/圆心算错时会补一条弦或长出一个钩子——这种错不报错、
   不崩，单测也只看数字，画出来一眼就能看出来（`_measure_notch.py` 量的是像素，
   这里给的是整张图）。
2. **给像素量尺造"已知答案的对照图"**（`--check`）：同一套公式画"带过渡"和"尖角"两张图，
   要求量尺在前者上过、在后者上挂。判据分不开这两张图 = 那把尺子是假的。

用法：
    python _tools/notify/_notch_render.py            # 出两张 PNG（默认写到 _archive/）
    python _tools/notify/_notch_render.py --check    # 只跑对照（量尺判据自检），临时目录里画

⚠️ `--check` 是给 `_check_all.py` 用的（它自己扫 `add_argument("--check")`）：这条判据
每次跑全套检查都会被验一遍，坏了不会没人知道。
"""
import argparse
import math
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _measure_notch import measure  # noqa: E402

# 真机参数：钮 58dp、凸出 12dp、缝 9dp；分辨率 1080px = 3x
D, PROTRUDE, GAP = 58.0, 12.0, 9.0
DENSITY = 3.0
W_DP, H_DP, CORNER_DP = 360.0, 80.0, 18.0
IMG_W, IMG_H = int(W_DP * DENSITY), 2400          # 与模拟器截图同尺寸：导航栏贴在底部
BAR_TOP = IMG_H - int(H_DP * DENSITY)


def geometry(fillet: float) -> dict:
    """与 NavBarNotch.geometry 同一套公式（改那边必须改这边，--check 会立刻发现对不上）"""
    r = D / 2 + GAP
    radius = D / 2
    center_y = radius - PROTRUDE
    half = math.sqrt(r * r - center_y * center_y) if r > abs(center_y) else 0.0
    f = fillet
    fx = math.sqrt(half * half + 2 * f * (r + center_y))
    to_center = math.degrees(math.atan2(center_y - f, fx))
    return {
        "radius": r,
        "half": half,
        "depth": center_y + r,
        "center_y": center_y,
        "start_angle": -to_center,
        "left_angle": 180.0 + to_center,
        "sweep": -180.0 - 2 * to_center,
        "fillet": f,
        "fx": fx,
        "fillet_sweep": 90.0 + to_center,
    }


def _arc(cx, cy, r, start_deg, sweep_deg, steps=240):
    return [
        (
            cx + r * math.cos(math.radians(start_deg + sweep_deg * i / steps)),
            cy + r * math.sin(math.radians(start_deg + sweep_deg * i / steps)),
        )
        for i in range(steps + 1)
    ]


def _quad(p0, p1, p2, steps=24):
    return [
        (
            (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
            (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1],
        )
        for t in [i / steps for i in range(steps + 1)]
    ]


def path_points(g, w, h, corner):
    """与 NotchedBarShape.createOutline 的画法逐条对应（单位 dp，y 从栏上沿往下）"""
    cx = w / 2
    r, cy, fx, f = g["radius"], g["center_y"], g["fx"], g["fillet"]
    pts = [(0.0, h), (0.0, corner)]
    pts += _quad((0.0, corner), (0.0, 0.0), (corner, 0.0))
    pts.append((cx - fx, 0.0))
    if g["half"] > 0 and fx > 0:
        if f > 0:                                              # 左圆角（半径 0 时是空操作）
            pts += _arc(cx - fx, f, f, 270.0, g["fillet_sweep"])
        pts += _arc(cx, cy, r, g["left_angle"], g["sweep"])     # 大缺口弧
        if f > 0:                                              # 右圆角
            pts += _arc(cx + fx, f, f, 180.0 + g["start_angle"], g["fillet_sweep"])
    pts.append((cx + fx, 0.0))
    pts.append((w - corner, 0.0))
    pts += _quad((w - corner, 0.0), (w, 0.0), (w, corner))
    pts.append((w, h))
    return pts


def render(fillet: float, out: Path, outline_old: bool = False) -> Path:
    g = geometry(fillet)
    im = Image.new("RGB", (IMG_W, IMG_H), (244, 246, 248))     # App 背景灰
    dr = ImageDraw.Draw(im)

    def to_px(ps, dy):
        return [(x * DENSITY, dy + y * DENSITY) for x, y in ps]

    dr.polygon(to_px(path_points(g, W_DP, H_DP, CORNER_DP), BAR_TOP), fill=(255, 255, 255))
    if outline_old:
        dr.line(to_px(path_points(geometry(0.0), W_DP, H_DP, CORNER_DP), BAR_TOP),
                fill=(255, 0, 0), width=2, joint="curve")
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    print(f"  {out.name}: 上沿开口半宽 {g['fx']:.1f}dp（大圆交点 {g['half']:.1f}dp）、"
          f"最深 {g['depth']:.1f}dp、切点角 {-g['start_angle']:.1f}°、圆角扫角 {g['fillet_sweep']:.1f}°")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="离线画凹口路径；--check 自检像素量尺的判据")
    ap.add_argument("--check", action="store_true", help="只跑对照：量尺必须能分开「带过渡」和「尖角」")
    args = ap.parse_args()

    if args.check:
        tmp = Path(tempfile.mkdtemp(prefix="notch_render_"))
        smooth_f = geometry(0.0)["center_y"]      # 过渡圆角 = 圆心深度（与 Kotlin 同一取值）
        print("对照图（量尺的判据必须能分开这两张）：")
        smooth = measure(render(smooth_f, tmp / "smooth.png", outline_old=True), quiet=True)
        sharp = measure(render(0.0, tmp / "sharp.png"), quiet=True)
        print(f"  带过渡：爬起来 {[round(r, 1) for r in smooth['runs']]}dp、最深 {smooth['deepest_dp']:.0f}dp → "
              f"{'过' if smooth['ok'] else '挂'}")
        print(f"  尖角  ：爬起来 {[round(r, 1) for r in sharp['runs']]}dp、最深 {sharp['deepest_dp']:.0f}dp → "
              f"{'过' if sharp['ok'] else '挂'}")
        ok = smooth["ok"] and not sharp["ok"]
        print("✅ 量尺的判据分得开（带过渡过、尖角挂）" if ok
              else "❌ 量尺的判据分不开这两张图 —— 判据坏了，等于没有判据")
        return 0 if ok else 1

    out_dir = Path("_archive")
    cy = geometry(0.0)["center_y"]
    print("出图（白=形状，红=没有过渡时的旧边界）：")
    render(cy, out_dir / "_notch_smooth.png", outline_old=True)
    render(0.0, out_dir / "_notch_sharp.png")
    print(f"（另附一张过渡取小了的反例：6dp → 两侧会留下一小块'喙'）")
    render(6.0, out_dir / "_notch_fillet6.png", outline_old=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
