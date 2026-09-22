"""「分组一律白卡」的判据（2026-09-22 用户定成全局规范）。

## 用户原话（对着一屏"新增线路"说的）
> 「…只是用**线框**框起来的话太不美观了，而且也不够**醒目对比**，所以把他们改进这种
>  **白色的卡片样式**…**这就是个设计规范，包括以后也是这样子啊，所有都要这样子去改**」

## 这条为什么必须有机器的判据
这一屏的问题**在这一屏之前已经出现过一次**（「新增商品」："不是很好看，也太乱了"），
根因都是**三层框叠在一起**：描边输入框 → 外面再套描边卡片 → 每个字段再跟一句灰字。
两次的修法是同一个（白卡 + 无边框行 + "值即占位符"）。
而"又写一个 `OutlinedTextField`"这件事**从来不报错**：编译过、真机上看着"也能用"，
只是那一页又变回"一堆矩形框浮在灰底上"——只有人肉翻页面才会发现。

所以判据分两层：
1. **已按规范改过的页面**：`OutlinedTextField` 必须 **0 处**（文件清单写死在这里，
   搬走/改名都会红 —— 防"清单过期 → 判据空转 → 满屏绿灯"）；
2. **全库总数只许减不许增**：基线在 `_tools/qa/_form_panel_baseline.txt`。
   改好一页就 `--update` 把基线降下来；**涨了当场红**，并打印待改清单
   （清单是**算出来的**，不是手写的 —— 本仓库为"手写清单"栽过 5 次）。

⛔ 判据**不**管 `OutlinedButton`（"次操作"的既定形态）和搜索框（`SoTextField` / `SearchField`）：
一条"凡描边必红"的判据会把它们一起打红，然后下一个人只会把判据关掉。

⚠️ **总数这个数字把"紧凑控件"也算进去了**（数量步进器中间那个 96dp 的小框、
弹窗里的单字段等）：它们不是"表单分组里的一行"，所以**不要求**改成 `FormRows`，
但也没有被排除在计数之外 —— 一个口径简单、无法被绕过的数字，比一个"聪明的"过滤器可信。

用法：python _tools/qa/_check_form_panel_style.py
     python _tools/qa/_check_form_panel_style.py --update   # 改好一页之后把基线降下来
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
# 注释剥离**只有一份实现**（那个状态机是为了 `"image/*"` 这种字符串写的，抄一份必踩同一个坑）
from _check_product_card_single_source import strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DOC = ROOT / "docs/PROJECT_MAP/06_DESIGN_SYSTEM.md"
ROWS = AND / "ui/common/FormRows.kt"
BASELINE = Path(__file__).resolve().parent / "_form_panel_baseline.txt"

#: 已按规范改过的页面 —— 这里**一个描边输入框都不许有**，
#: 而且**这些行每一种都得真的出现**（只写"用了两个以上共用行"是不够的：
#: 把其中一个换回自己写的行时，剩下两个照样能满足"≥2"—— 反向验证当场抓出来的）。
CONVERTED = {
    "ui/dispatcher/ProductFormScreen.kt": (
        "新增/编辑商品（2026-09-21 第 1 期）",
        ["FormInputRow", "FormPickRow", "FormSwitchRow"],
    ),
    "ui/shipper/AddressScreen.kt": (
        "新增/编辑线路·联系人·地点（2026-09-22）",
        ["FormInputRow", "FormTextAreaRow", "FormPickRow", "FormActionRow", "FormSwitchRow"],
    ),
    "ui/dispatcher/OrderTemplateFormScreen.kt": (
        "新建/编辑预订单（2026-09-22 用户：「还可以新建一个订单」）",
        ["FormInputRow", "FormTextAreaRow", "FormPickRow", "FormActionRow"],
    ),
}

#: 表单那几种零件（少一个就红：判据不能因为"零件被删了"而空转）
ROW_KINDS = ["FormInputRow", "FormTextAreaRow", "FormPickRow", "FormActionRow", "FormSwitchRow"]

#: 分组白卡那个容器（**只有一处定义**：各页自己写一份就会"组标题字号/间距每页一个样"）
GROUP_KIND = "FormGroup"

#: 扫到的 .kt 文件数下限（防目录改名/搬走之后"一个文件都没扫到"也算过）
MIN_UI_FILES = 100

FIELD = "OutlinedTextField"


def read(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def code(p: Path) -> str:
    return strip_comments(read(p))


def scan() -> dict[str, int]:
    """**算出来的**清单：还有几个描边输入框、在哪些文件里（不手写）。"""
    out: dict[str, int] = {}
    for p in AND.rglob("*.kt"):
        n = len(re.findall(rf"\b{FIELD}\s*\(", code(p)))
        if n:
            out[str(p.relative_to(AND)).replace("\\", "/")] = n
    return out


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

    def report(self, title: str) -> int:
        print()
        print(f"===== {title} =====")
        print(f"  通过 {self.passes} 项，失败 {len(self.fails)} 项")
        for f in self.fails:
            print(f"    - {f}")
        return 1 if self.fails else 0


def main() -> int:
    update = "--update" in sys.argv
    c = Checker()
    print("「分组一律白卡」：表单分组用白卡 + 无边框行（2026-09-22）")

    ui_files = list(AND.rglob("*.kt"))
    c.ok(
        f"扫到的界面文件数 ≥ {MIN_UI_FILES}（防目录搬走 → 判据空转）",
        len(ui_files) >= MIN_UI_FILES,
        f"实际 {len(ui_files)}",
    )

    # ---- 1. 那几种共用行 + 分组白卡都在、各只有一处定义 ----
    for k in ROW_KINDS + [GROUP_KIND]:
        c.ok(
            f"{k} 只有一处定义（在 ui/common/FormRows.kt）",
            len(re.findall(rf"fun {k}\(", code(ROWS))) == 1
            and not [p.name for p in ui_files if p != ROWS and re.search(rf"fun {k}\(", code(p))],
            f"{k} 缺失或在别处也被定义了",
        )

    # ---- 2. 已改过的页面：一个描边输入框都不许有 + 该用的共用行一种都不能少 ----
    for rel, (why, need) in CONVERTED.items():
        p = AND / rel
        c.ok(f"{rel} 存在（{why}）", p.exists(), "文件被搬走/改名了")
        src = code(p)
        n = len(re.findall(rf"\b{FIELD}\s*\(", src))
        c.ok(f"{rel} 里一个描边输入框都没有（{why}）", n == 0, f"实际 {n} 处")
        missing = [k for k in need if not re.search(rf"{k}\(", src)]
        c.ok(f"{rel} 每一种共用行都还在用（{why}）", not missing, f"不见了：{missing}")
        c.ok(f"{rel} 的分组是白卡（SectionCard）", "SectionCard" in src or "FormGroup" in src)

    # ---- 3. 全库总数：只许减不许增（基线自算，不手写）----
    hits = scan()
    total = sum(hits.values())
    base = None
    if BASELINE.exists():
        m = re.search(r"\d+", BASELINE.read_text(encoding="utf-8"))
        base = int(m.group(0)) if m else None
    c.ok(
        "基线文件在、且是个数字",
        base is not None,
        f"{BASELINE.name} 缺失或没有数字（跑一次 `--update` 生成）",
    )
    if base is not None:
        c.ok(
            f"描边输入框总数没有涨（基线 {base}，现在 {total}）",
            total <= base,
            f"多了 {total - base} 处 —— 新页面又写描边框了？用 FormRows.kt 那五行",
        )
        # ⚠️ **改好了一页只提示、不报红**：这个仓库同时有好几个会话在改，
        #    别人顺手清理一页就会让"基线没跟着降"变红 —— 那种红**不是任何人的错**，
        #    红几次之后大家就会把整条检查关掉（本仓库踩过："永远红的检查 = 没有检查"）。
        #    所以这里只把进度说出来，硬判据只有上面那条"只许减不许增"。
        if total < base:
            print(
                f"  [提示] 已经有人改好了 {base - total} 处（现在 {total}）——"
                f" 建议跑 `python _tools/qa/_check_form_panel_style.py --update` 把基线降下来"
            )
    if update:
        BASELINE.write_text(
            f"{total}\n# 「分组一律白卡」的待改基线（只许减不许增）。\n"
            f"# 改好一页就跑 `python _tools/qa/_check_form_panel_style.py --update` 把它降下来。\n"
            f"# 生成时间见 git；文件清单由脚本自己算，不手写。\n",
            encoding="utf-8",
        )
        print(f"  [--update] 基线已写成 {total}")

    # ---- 4. 规范文档里必须写着这条 ----
    doc = read(DOC)
    c.ok(
        "设计规范里写着这条（否则下一个人还会用描边框当分组）",
        DOC.exists() and "分组一律白卡" in doc and "FormRows" in doc,
        "06_DESIGN_SYSTEM.md §5.0 里没记这条规范",
    )

    # ---- 5. 待改清单（算出来的，不是手写的）----
    print()
    print(f"  == 待改清单：还有 {total} 处描边输入框，分布在 {len(hits)} 个文件 ==")
    for rel, n in sorted(hits.items(), key=lambda kv: (-kv[1], kv[0]))[:12]:
        mark = "  ← 已改过（不该再有！）" if rel in CONVERTED else ""
        print(f"     {n:>3} 处  {rel}{mark}")
    if len(hits) > 12:
        print(f"     …… 还有 {len(hits) - 12} 个文件（总数 {total}）")
    print("  ⛔ 这些**不是**这一轮必须改完的**：规范从今天起对新页面生效；")
    print("     老页面按页面分批改（改完一页就 --update 降基线，进度看得见）。")

    return c.report("分组白卡 / 表单行 单一来源")


if __name__ == "__main__":
    sys.exit(main())
