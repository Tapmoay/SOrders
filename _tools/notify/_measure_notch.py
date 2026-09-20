"""量真机截图里的导航栏「凹口」：证明它真的画出来了（而不是"看着像"）。

为什么要量：第一版凹口的圆心算错了（放在栏外），切出来的坑又浅又藏在圆钮背后，
**肉眼在截图上根本看不出来**，但拉一条逐像素的剖面就一目了然。
这个脚本就是那把尺子——以后调凹口深浅，用它对比改动前后。

2026-09-20 加了第二把尺子：**两侧的圆滑过渡**（用户：「那个角是尖尖，把它做一个曲线过渡」）。
判据是"缺口边缘爬起来有多快"：圆角与上沿相切 ⇒ 边缘是二次曲线，从 15px 深爬到 3px 深
要走 ≈5dp 横向；尖角时代是 70° 直插（直线，而且上沿还留着一小块"喙"），同样的落差是 0dp。
取 2.5dp 为界就能把两者分开——这也是唯一能在真机上证明"过渡真的画上去了"的办法
（形状画错了不会报错、也不会崩）。两个已知答案的对照图见 `_notch_render.py --check`。

    这把尺子的判据本身有**已知答案的对照图**：`python _tools/notify/_notch_render.py --check`
    用同一套几何公式画两张图（带过渡 / 尖角），要求这把尺子前者过、后者挂。
    判据改了就重跑它——分不开就等于没有判据。

用法：python _tools/notify/_measure_notch.py <截图路径> [中心x]
"""
import sys
from pathlib import Path

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def first_white(px, x, y0, y1):
    """从 y0 往下找第一块纯白 = 导航条上沿（缺口内会晚很多才出现）"""
    for y in range(y0, y1):
        r, g, b = px[x, y]
        if r >= 253 and g >= 253 and b >= 253:
            return y
    return None


def measure(path, cx=None, quiet=False) -> dict:
    """量一张图；返回 {density, deepest_dp, runs(两侧爬起来走了多少dp), visible, smooth, ok}"""
    im = Image.open(path).convert("RGB")
    px = im.load()
    w, h = im.size
    cx = cx if cx is not None else w // 2
    density = w / 360          # 1080px 宽的模拟器 = 3x
    y0, y1 = int(h * 0.85), h  # 导航栏在底部：只在下沿那一段找

    def drop_at(x):
        y = first_white(px, x, y0, y1)
        return None if (y is None or base is None) else y - base

    base = first_white(px, cx - 300, y0, y1)
    if not quiet:
        print(f"图 {path}  宽 {w}x{h}  密度≈{density:.1f}")
        print("预期：上沿开口半宽 ≈43dp（含 6dp 圆滑过渡撑宽的 ≈7dp），最深 ≈55dp（相对基准）")
        print(f"基准上沿 y={base}\n")
        print("列偏移   上沿y   下沉")
    prof = {}
    for dx in range(-160, 161, 20):
        d = drop_at(cx + dx)
        prof[dx] = d
        if not quiet:
            bar = "" if not d else "#" * max(0, d // 8)
            print(f"{dx:+5d}   {base if d is None else base + d}   {d}  {bar}")

    deepest = max((d for d in prof.values() if d is not None), default=0)
    half = max((abs(dx) for dx, d in prof.items() if d and d > 20), default=0)
    if not quiet:
        print(f"\n实测：最深 {deepest}px（{deepest / density:.0f}dp），缺口半宽 ≥{half}px")

    # ---- 判据一：坑要够深（>25dp）才看得见；第一版只有 18dp 且被圆钮挡住 ----
    visible = deepest / density > 25

    # ---- 判据二：两侧是不是「圆滑过渡」（而不是尖角）----
    # 从缺口中心往外逐像素扫，量"边缘从 15px 深爬到 3px 深"走了多少横向距离：
    #   圆滑（圆角与上沿相切，边缘是二次曲线）⇒ 真机参数下 ≈5dp
    #   尖角（70° 直插，边缘是直线 + 上沿一小块"喙"）⇒ 0dp（两档掉在同一列里）
    # 判据取 2.5dp：两边都留得下余量，且这个数**与分辨率无关**（两边都是 dp）。
    def rise_run(sign: int):
        # ⚠️ 从圆钮外沿（±32dp）开始扫，不要从中心开始：圆钮自己（还有里面那个白色星标）
        #    也是白的，从中心往外扫时"第一块白"量到的是**圆钮**，不是缺口边缘。
        start = int(32 * density)
        deep = shallow = None
        for k in range(start, 240):
            dx = k * sign
            d = drop_at(cx + dx)
            if d is None:
                continue
            if deep is None and d <= 15:
                deep = dx
            if deep is not None and d <= 3:
                shallow = dx
                break
        if deep is None or shallow is None:
            return None, None, None
        return deep, shallow, abs(shallow - deep) / density

    runs = []
    for sign in (1, -1):
        deep, shallow, run = rise_run(sign)
        side = "右" if sign > 0 else "左"
        if run is None:
            if not quiet:
                print(f"{side}侧：没量到（缺口太浅或圆钮/阴影挡住了这一列）")
        else:
            if not quiet:
                print(f"{side}侧：15px 深在 x{cx + deep:+d} → 3px 深在 x{cx + shallow:+d}，横向 {run:.1f}dp")
            runs.append(run)
    smooth = bool(runs) and all(r >= 2.5 for r in runs)
    if not quiet:
        print(
            "✅ 两侧都是圆滑过渡（边缘贴着上沿慢慢下沉）"
            if smooth
            else "❌ 两侧还是尖角（边缘一上来就直插下去，没有过渡）"
        )
        print(("✅ 凹口看得见" if visible else "❌ 凹口太浅/没画出来（第一版就是这个毛病）"))
    return {
        "density": density,
        "deepest_dp": deepest / density,
        "runs": runs,
        "visible": visible,
        "smooth": smooth,
        "ok": visible and smooth,
    }


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "_agent/nav-dispatcher2.png"
    cx = int(sys.argv[2]) if len(sys.argv) > 2 else None
    return 0 if measure(path, cx)["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
