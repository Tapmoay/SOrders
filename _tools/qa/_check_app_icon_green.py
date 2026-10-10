"""桌面图标 / 启动画面 跟没跟上 App 的配色（CHG-0108）。

## 这个判据在防什么

`res/drawable/ic_launcher_background.xml` 与 `ic_launcher_foreground.xml` 里的颜色
是**手抄**的十六进制，不是读 `Color.kt` 的 token。CHG-0091「整体基调从蓝变绿」
把登录页从浅蓝/藏蓝换成了浅绿/墨绿，App 里全换了，**唯独这两层没人跟**——
于是桌面图标和启动画面（API 31+ 每次冷启动都画一屏，图标就取自这里）一直是旧的蓝色，
直到用户 2026-10-10 自己看出来：「既然我们的图标改成了这个颜色那我们手机桌面上的
图标也要改一下包括加载动画也就是我们一开始进app的那个预加载动画也要改一下。」

这就是本项目那类「同一个语义两处定义、改了一处」的老毛病。判据的做法是
**拿 Color.kt 的现值去对资源里的字面量**，而不是把现值再抄一遍到判据里——
抄一遍的话，下一次换色时判据和资源会一起过期，等于没判据。

R4-BOUNDARY-JUSTIFICATION: 这一条**只能**靠机器判据，扩展点/边界都解决不了它 ——
颜色在这里跨了两种语言与两种构建阶段：真源是 Kotlin 的 `Color.kt`，而图标与启动画面是
`res/drawable/*.xml`、`res/values{,-v31}/*.xml` 里的**手抄十六进制字面量**，AAPT/编译器
不会把两边对上，类型系统也管不到资源里的字符串；`colorPrimary` 之类的主题属性只覆盖
Material 组件取色，覆盖不到 launcher 图标那两层 vector。于是「换色时只改了 App、忘了图标」
在编译、单测、真机点按里**全都不报错**，只有用户在手机桌面上看得出来（CHG-0091 → CHG-0108
就是这么发生的）。所以必须有一条判据把「资源现值 == Color.kt 现值」钉住。

## 检查什么

1. 图标两层 + 兜底色 + 启动画面底色，四处都等于 `Color.kt` 的现值；
2. 三处字面量互相一致（背景层 / colors.xml 的两项）；
3. 主题分两层（`.Base` + v31 覆盖），且 v31 只覆盖启动画面那两条；
4. 旧值（`#D9E8FF` / `#0A3168` / `#FFB020`）在图标资源里**一个都不许剩**；
5. 主题图标（monochrome）的形状与前景层**逐字相同**（改一处不改另一处，
   开了「主题图标」的桌面会显示成另一个形状）；
6. 清单仍然指向 `@mipmap/ic_launcher` 与 `@style/Theme.SOrders`；
7. 通知栏小图标仍在用 `ic_stat_order`（那是 24dp 单色剪影，**不能**换成
   `@mipmap/ic_launcher`——状态栏只取 alpha，自适应图标会显示成一个纯白方块）。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事

这一单的病**不在代码逻辑里**：`ic_launcher_background.xml` / `ic_launcher_foreground.xml`
里的十六进制是**手抄**的（不是读 `Color.kt` 的 token），编译器、类型系统、契约层都看不出
「它跟 `Color.kt` 的 `PrimaryContainer` 已经不是同一个值了」——两处都是合法的颜色字面量，
编译一样过、单测一样绿（本单跑 `:app:testEmuDebugUnitTest` 是 1507 条 0 失败）。
资源文件的形状里也没有任何一处能把「语义色」与「抄下来的旧值」分开。

启动画面那一半更难：它只在 **API 31+ 真机冷启动的那一瞬**才存在，
`values-v31/themes.xml` 里那两条属性不参与任何编译期或运行期校验，连截图都要靠
「冷启动后连拍 14 帧再挑出那一帧」才拿得到。所以这件事没有边界可下沉，只能由一条静态判据
把「资源的字面量 == `Color.kt` 的现值」钉住 —— 并且必须由反向验证证明它真的会红
（12 条注入里第 ⑧ 条当场抓出过判据自己的一处假绿：`@mipmap/ic_launcher` 被自己的
KDoc 满足了）。
"""

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
RES = ROOT / "android/app/src/main/res"
COLOR_KT = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/theme/Color.kt"
MANIFEST = ROOT / "android/app/src/main/AndroidManifest.xml"

BG_XML = RES / "drawable/ic_launcher_background.xml"
FG_XML = RES / "drawable/ic_launcher_foreground.xml"
MONO_XML = RES / "drawable/ic_launcher_monochrome.xml"
STAT_XML = RES / "drawable/ic_stat_order.xml"
COLORS_XML = RES / "values/colors.xml"
THEMES_XML = RES / "values/themes.xml"
THEMES_V31 = RES / "values-v31/themes.xml"

#: 这三条是 CHG-0108 之前的旧值。留在图标资源里就说明有人改回去了。
OLD_VALUES = ("D9E8FF", "0A3168", "FFB020")

_total = 0
_bad: list[str] = []


def read(p: Path) -> str:
    return io.open(p, encoding="utf-8").read()


def token(name: str) -> str:
    """从 Color.kt 读一个 token 的六位十六进制（不区分大小写，统一大写返回）。"""
    m = re.search(r"^val %s = (?:Color\()?0x(?:FF)?([0-9A-Fa-f]{6})\)?" % re.escape(name),
                  read(COLOR_KT), re.M)
    if not m:
        raise SystemExit(f"⛔ Color.kt 里找不到 token {name}")
    return m.group(1).upper()


def ok(cond: bool, what: str) -> None:
    global _total
    _total += 1
    if cond:
        print(f"  ✅ {what}")
    else:
        print(f"  ❌ {what}")
        _bad.append(what)


def code_only(src: str) -> str:
    """去掉 XML 注释（判据锚在**代码**上，不锚在我们的说明文字上）。

    ⚠️ 不剥会当场假红：这一版的两处 KDoc 里正大光明写着旧值
    「底色一直停在旧蓝 `#D9E8FF`、货车停在旧藏蓝 `#0A3168`」，
    裸子串扫描会把这段**说明**当成"旧值还在"。与 `_check_all.py` 的
    `_code_only()` 是同一个道理：判据必须锚在代码上。
    """
    return re.sub(r"<!--[\s\S]*?-->", "", src)


def fill_colors(xml: str) -> list[str]:
    """取矢量图里所有 `android:fillColor="#XXXXXX"`（只取六位十六进制那种）。"""
    return [c.upper() for c in re.findall(r'android:fillColor="#([0-9A-Fa-f]{6})"', xml)]


def main() -> int:
    for p in (BG_XML, FG_XML, MONO_XML, STAT_XML, COLORS_XML, THEMES_XML, THEMES_V31, MANIFEST):
        if not p.exists():
            raise SystemExit(f"⛔ 缺文件：{p.relative_to(ROOT)}")
        print(f"  ℹ️ {p.relative_to(ROOT)}")

    if not COLOR_KT.exists():
        raise SystemExit("⛔ 缺 Color.kt")

    pale = token("PrimaryContainer")     # 底色
    ink = token("OnPrimaryContainer")    # 货车

    print("\n[1] 颜色跟上了 Color.kt 的现值")
    print(f"    Color.kt: PrimaryContainer = #{pale}（底） / OnPrimaryContainer = #{ink}（货车）")
    bg = fill_colors(read(BG_XML))
    fg = fill_colors(read(FG_XML))
    ok(len(bg) == 1, f"背景层只有一个平涂色（实际 {len(bg)} 个）")
    ok(bg == [pale], f"背景层 = PrimaryContainer #{pale}（实际 {bg}）")
    ok(len(fg) == 1, f"前景层只有一个平涂色（实际 {len(fg)} 个）")
    ok(fg == [ink], f"前景层（货车）= OnPrimaryContainer #{ink}（实际 {fg}）")

    print("\n[2] 兜底色 / 启动画面底色 与图标层一致")
    colors = read(COLORS_XML)
    m = re.search(r'<color name="ic_launcher_background">#([0-9A-Fa-f]{6})</color>', colors)
    ok(bool(m), "colors.xml 里有 ic_launcher_background")
    ok(bool(m) and m.group(1).upper() == pale,
       f"ic_launcher_background = 背景层同色 #{pale}（实际 {m.group(1) if m else '缺'}）")
    m2 = re.search(r'<color name="splash_background">#([0-9A-Fa-f]{6})</color>', colors)
    ok(bool(m2), "colors.xml 里有 splash_background（启动画面底色）")
    ok(bool(m2) and m2.group(1).upper() == pale,
       f"splash_background = 背景层同色 #{pale}（实际 {m2.group(1) if m2 else '缺'}）")

    print("\n[3] 旧值一个都不许剩（图标与主题资源里）")
    for p in (BG_XML, FG_XML, MONO_XML, COLORS_XML, THEMES_XML, THEMES_V31):
        src = code_only(read(p))
        hits = [v for v in OLD_VALUES if v.lower() in src.lower()]
        ok(not hits, f"{p.name} 里没有旧值 {list(OLD_VALUES)}（实际命中 {hits}）")

    print("\n[4] 主题分两层：基础项只在 .Base，启动画面只在 v31")
    base = read(THEMES_XML)
    v31 = read(THEMES_V31)
    # ⚠️ 这两条必须只看**代码**：本文件的 KDoc 里正大光明写着「图标显式写
    #    `@mipmap/ic_launcher`」，裸子串扫描会被这段说明满足 —— 反向验证第 ⑧ 条
    #    就是这么抓出来的（把该项换成 @drawable/ic_stat_order 之后判据仍然全绿）。
    base_code = code_only(base)
    v31_code = code_only(v31)
    ok(re.search(r'<style name="Theme\.SOrders\.Base"', base_code) is not None,
       "values/themes.xml 定义了 Theme.SOrders.Base")
    ok(re.search(r'<style name="Theme\.SOrders" parent="Theme\.SOrders\.Base"\s*/>', base_code) is not None,
       "values/themes.xml 里 Theme.SOrders 继承 .Base（API<31 用这一层）")
    ok("windowSplashScreenBackground" not in base_code,
       "基础层不写 windowSplashScreen*（那是 31+ 的属性）")
    ok(re.search(r'<style name="Theme\.SOrders" parent="Theme\.SOrders\.Base">', v31_code) is not None,
       "values-v31/themes.xml 里 Theme.SOrders 同样继承 .Base（不抄基础项）")
    ok("windowSplashScreenBackground" in v31_code and "@color/splash_background" in v31_code,
       "v31 把启动画面底色指向 @color/splash_background")
    ok("windowSplashScreenAnimatedIcon" in v31_code
       and re.search(r'windowSplashScreenAnimatedIcon">@mipmap/ic_launcher<', v31_code) is not None,
       "v31 显式写启动画面图标 = @mipmap/ic_launcher")
    ok("statusBarColor" not in v31_code,
       "v31 不覆盖基础项（改状态栏只改 values/themes.xml 一处）")

    print("\n[5] 主题图标的形状与前景层逐字相同")
    def path_of(src: str) -> str:
        m = re.search(r'android:pathData="([^"]+)"', src)
        return m.group(1) if m else ""
    ok(path_of(read(MONO_XML)) != "" and path_of(read(MONO_XML)) == path_of(read(FG_XML)),
       "monochrome 与 foreground 的 pathData 完全一致（形状不会各说各的）")

    print("\n[6] 清单仍指向这套图标与主题")
    man = read(MANIFEST)
    ok('android:icon="@mipmap/ic_launcher"' in man, "清单的 android:icon = @mipmap/ic_launcher")
    ok('android:theme="@style/Theme.SOrders"' in man, "清单的 android:theme = @style/Theme.SOrders")

    print("\n[7] 通知栏小图标没被换成自适应图标")
    ok("android:tint=" in read(STAT_XML), "ic_stat_order 是单色剪影（带 tint）")
    ok("@mipmap" not in code_only(read(STAT_XML)), "ic_stat_order 自己不含 @mipmap（状态栏只取 alpha）")

    print(f"\n  {'✅' if not _bad else '❌'} {_total - len(_bad)}/{_total} 项通过")
    if _bad:
        print("\n  未通过：")
        for b in _bad:
            print(f"    - {b}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
