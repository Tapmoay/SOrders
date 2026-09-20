# -*- coding: utf-8 -*-
"""红线：Android 的文本输入框必须走 `core/InputRules`（电话只数字 / 金额至多两位小数）。

### 为什么这条检查存在（2026-09-19 用户反馈）
用户原话：「我在下单的时候，它不是要填电话号码吗？这个电话号码只能填数字，而且必须填正确的格式，
它是不能填字母和文字的。包括其他类似的这样子都要做相应的限制」。

这不是"用户没想到"的问题 —— 改之前查了生产库，`orders.contact_dongjia_phone` 里
真有 `嘿嘿` `嘻嘻` `问问` `刚刚好` 四类中文值（6 行），`shipper_contacts` 里有一条 `222`；
金额框用的是 `it.filter { c -> c.isDigit() || c == '.' }`，能敲出 `1.2.3`，
`toDoubleOrNull()` 得到 null、界面小计变 ¥0.00，全靠后端 422 兜底。

### 这条检查在防什么
规则本身只有一处实现（`android/.../core/InputRules.kt`）。**但"规则有了"不等于"每个框都用了"** ——
本项目栽过 5 次的正是这一类：检查只扫手写清单，新加的第 6 个框不在清单里。
所以这里**自己扫** Android 源码：

1. 把所有文本输入框的**调用**抠出来（带括号配对，不是按行猜）；
2. 认得出是"电话类"或"金额类"的（按 label/placeholder 里的关键词），**必须**出现
   `InputRules.phone*` / `InputRules.mobile*` / `InputRules.money*`；
3. 任何文本输入框的 `onValueChange` 里**不许手写数字过滤**（`isDigit()` / `c == '.'`）——
   那就是规则的一份副本，改的时候一定漏掉一个；
4. 数量判据：算出来的框数低于下限 = **解析器失配**（源码风格变了），不是"项目里没框了"。
   没有这条的话，正则一旦失配，这条检查会安静地变成"全绿"。

### 两个必须踩住的坑（第一版就是错的）
1. **注释必须先抠掉再判断**。写在 `OutlinedTextField(` 与 `)` 之间的中文注释里会出现
   「电话只让数字进来（规则唯一实现在 InputRules.kt）」这种字眼 ——
   不抠注释的话，一个**根本没接线**的框会因为注释里提到了 `InputRules` 而判为"已接线"
   （假绿，比没有检查更糟）。抠注释时**长度必须保持不变**（注释换成等长空格），
   否则后面按偏移算出来的行号全错。
2. **认类别看"标题"，不看整个调用体**。已经改好的框，体内就有 `InputRules.phoneInput`；
   拿整个调用体去找关键词，等于用答案判答案。

### 例外必须写理由
`label` 里带"电话"却不是电话输入的（搜索引擎框、备注框、"手机号 / 用户名"登录框），
要进 `EXCLUDED` 并写明为什么 —— 包括登录框那条**故意**不收数字的理由（用户名可以是字母）。
`EXCLUDED` 的键还得是**真实存在**的框，防止理由变成化石。

用法：
    python _tools/qa/_check_input_rules.py            # 检查
    python _tools/qa/_check_input_rules.py --list     # 只列清单（看它到底在查什么）
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import refuse_if_injecting, repo_root  # noqa: E402

ROOT = repo_root()
UI_DIR = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders" / "ui"

#: 文本输入框的构造器名（`SoTextField` 是本项目自己的 iOS 风输入框，也必须有过滤）。
FIELD_NAMES = ("OutlinedTextField", "SoTextField", "BasicTextField", "TextField")

#: 数量判据（清单自己算 → 先钉"算出来有多少"）。
MIN_FIELDS_SCANNED = 25
MIN_CLASSIFIED = 12
MIN_PHONE_FIELDS = 6
MIN_MONEY_FIELDS = 8

#: 关键词 → 该走哪条规则。**只在本框自己的标题里找**。
#: 「钱」「提成」也在列：`这一单的钱 ¥` / `提成 %` 就是金额框，别因为没有"金额"两个字就漏掉。
PHONE_KEYS = ("电话", "手机号")
MONEY_KEYS = ("金额", "单价", "售价", "价格", "成本", "运费", "工资", "费率", "百分比", "钱", "提成")

#: 走哪条规则 → 调用文本里必须出现的东西（任一即可）。
#: 金额类接受 `moneyInput` **或** `priceInput`：两者是同一条规则的两个精度
#: （金额 2 位 = 库里 `Numeric(12,2)`；单价 4 位 = 库里 `Numeric(14,4)`）。
#: ⚠️ **本检查分不出"这个框该 2 位还是 4 位"** —— `一车价格 ¥`（运费模板费，库里 2 位）
#: 与 `默认售价`（商品单价，库里 4 位）在标题文字上没法区分。所以精度由**调用点**
#: 按自己那一列的精度选（并在注释里写明依据），本检查只保证"走的是同一处规则"。
REQUIRED = {
    "phone": ("InputRules.phoneInput", "InputRules.mobileInput"),
    "money": ("InputRules.moneyInput", "InputRules.priceInput"),
}

#: 故意**不**走 InputRules 的框：键 = "相对路径::框的标题"，值 = 为什么。
#: 键必须命中一个**真实存在**的框，否则报错（防化石）。
EXCLUDED: dict[str, str] = {
    "android/app/src/main/java/com/tapmoay/sorders/ui/login/LoginScreen.kt::手机号 / 用户名": (
        "登录框收的是**用户名**，用户名可以是字母（auth.py 的 username 一路到后端都合法）。"
        "给它加数字过滤会把用字母用户名的人挡在登录页外面 —— 这是本检查里唯一一条"
        "**业务上必须放开**的例外，不是「忘了改」。"
    ),
    "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ReportCenter.kt::解决说明（如：已电话联系司机重新派单）": (
        "异常处理说明的**备注框**，标题里那两个字只是举例文案（已电话联系司机重新派单）。"
        "里面要能写中文句子。"
    ),
    "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/AddressScreen.kt::搜线路：收货人 / 电话 / 地址": (
        "地址与联系人页的**搜索框**（搜线路/联系人），关键词里带「电话」而已。"
    ),
    "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/DriverBillingRulesScreen.kt::规则名称（如：挂车计件 / 小型车月薪+提成）": (
        "这是计费**规则的名称**（自由文本，要能写「月薪+提成」这种名字），"
        "命中关键词只因为它出现在举例文案里。这一条是「提成」进关键词表的代价："
        "多认一个名字框，换来两个真正该管的框（提成比例 ×2）被认出来 —— 划算，所以留着。"
    ),
    "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/UsersManageScreen.kt::计费规则（他怎么算钱就看这一项）": (
        "司机编辑弹窗里的**只读下拉框**（`onValueChange = {}`，选规则用的），根本打不了字 ——"
        "标题里那个「费」是「计费规则」这个词自带的。2026-09-21 起这一格是"
        "「他怎么算钱」的**唯一入口**（老的两个框已删），所以标题必须留着那两个词。"
    ),
}


def _read(p: Path) -> str:
    return io.open(p, encoding="utf-8", errors="replace").read()


def _strip_comments(src: str) -> str:
    """把 `//` 与 `/* */` 注释换成**等长空格**（行号靠偏移算，长度不能变）。"""
    out = list(src)
    i, n = 0, len(src)
    in_str = in_char = False
    while i < n:
        ch = src[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
        elif in_char:
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                in_char = False
        elif ch == '"':
            in_str = True
        elif ch == "'":
            in_char = True
        elif ch == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out[i] = " "
                i += 1
            continue
        elif ch == "/" and i + 1 < n and src[i + 1] == "*":
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
            if i + 1 < n:
                out[i + 1] = " "
            i += 2
            continue
        i += 1
    return "".join(out)


def _call_at(src: str, open_paren: int) -> str:
    """从 `(` 开始做括号配对，返回整个调用文本（含函数名与前面的缩进行首）。"""
    start = src.rfind("\n", 0, open_paren)
    start = 0 if start < 0 else start + 1
    depth, i = 0, open_paren
    in_str = in_char = False
    while i < len(src):
        ch = src[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif in_char:
            if ch == "\\":
                i += 1
            elif ch == "'":
                in_char = False
        elif ch == '"':
            in_str = True
        elif ch == "'":
            in_char = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    return src[start:]


def _titles(call: str) -> list[str]:
    """框里的标题/占位文字。

    两条路都要走：
    1. 常规写法 `label = { Text("…") }` / `placeholder = "…"`；
    2. `placeholder = when (tab) { 0 -> "搜线路：收货人 / 电话 / 地址" … }` 这种**表达式**写法 ——
       只看第 1 条的写法会把它整段漏掉（`AddressPickerSheet` 的搜索框就是这样，
       第一版检查确实没认出来）。所以第 2 条退一步：取 `placeholder =` 后面那一小段里的
       字符串字面量。宁可多认几个（多认的会进 EXCLUDED 并写明理由），不可漏认。
    """
    out: list[str] = []
    for m in re.finditer(r'label\s*=\s*\{\s*Text\(\s*"([^"]*)"', call):
        out.append(m.group(1))
    for m in re.finditer(r'placeholder\s*=\s*"([^"]*)"', call):
        out.append(m.group(1))
    for m in re.finditer(r"placeholder\s*=\s*", call):
        tail = call[m.end() : m.end() + 240]
        if tail.lstrip().startswith('"'):
            continue  # 第 1 条已经收过了
        for s in re.finditer(r'"([^"]*)"', tail):
            out.append(s.group(1))
    return out


def _classify(titles: list[str]) -> str | None:
    blob = " ".join(titles)
    if not blob:
        return None
    if any(k in blob for k in PHONE_KEYS):
        return "phone"
    if any(k in blob for k in MONEY_KEYS):
        return "money"
    return None


def collect_fields() -> list[dict]:
    """扫 `ui/` 下所有文本输入框调用 → 一条一条的清单。"""
    fields: list[dict] = []
    for path in sorted(UI_DIR.rglob("*.kt")):
        raw = _read(path)
        src = _strip_comments(raw)
        for name in FIELD_NAMES:
            for m in re.finditer(r"\b" + name + r"\s*\(", src):
                head = src[max(0, m.start() - 4) : m.start()]
                if re.search(r"\bfun\s+$", head):
                    continue  # `fun XxxTextField(` 是定义，不是调用
                call = _call_at(src, m.end() - 1)
                titles = _titles(call)
                fields.append(
                    {
                        "file": path.relative_to(ROOT).as_posix(),
                        "line": raw[: m.start()].count("\n") + 1,
                        "call": call,
                        "titles": titles,
                        "kind": _classify(titles),
                        "readonly": "readOnly = true" in call,
                        "title": (titles[0] if titles else ""),
                    }
                )
    return fields


def _key(f: dict) -> str:
    return f["file"] + "::" + f["title"]


#: 「下单的人不许改价」：这几个文件属于**下单链路**，里面的输入框标题不得出现价格字样。
#:
#: 用户 2026-09-19 的原话：「它这个选的商品页面它是不能改订单价的不然那货主他想改多少就改多少」。
#: 单价只有一个来源 —— 商品定价（`products.default_unit_price` / `price_rules.special_unit_price`），
#: 由派单员在「商品管理 / 批发商定价」里维护。下单页**曾经有一个「单价（元）」输入框**，
#: 删掉之后没有任何东西拦着它回来，而这里改错的是钱、且不会有任何提示，所以钉成红线。
NO_PRICE_EDIT_FILES: dict[str, str] = {
    "android/app/src/main/java/com/tapmoay/sorders/ui/common/ProductPicker.kt":
        "选品弹层（货主与代理下单共用）",
    "android/app/src/main/java/com/tapmoay/sorders/ui/shipper/OrderCreateScreen.kt":
        "下单页（货主与代理下单共用，含行编辑弹窗）",
}

#: 价格字样的关键词（出现在下单链路的输入框标题里就是违规）
PRICE_TITLE_KEYS = ("单价", "价格", "售价", "金额")


def _hand_filter(call: str) -> str | None:
    """调用里手写的数字过滤（规则的一份副本）。

    ⚠️ **不能只看 `onValueChange =`**：本项目大量用位置参数
    （`SoTextField(vm.qty, { vm.qty = it.filter { c -> c.isDigit() } }, placeholder = "数量")`），
    第一版只扫 `onValueChange` 之后的那段，于是 `InventoryScreen`/`DispatcherLedgerScreen`
    的数量框**全都没被认出来**。所以这里扫整个调用体 ——
    一个文本框的调用里出现 `filter { … isDigit }`，不管写在哪个参数上都该报出来。
    """
    if re.search(r"\.filter\s*\{[^}]*isDigit", call):
        return "isDigit()"
    if re.search(r"\.filter\s*\{[^}]*==\s*'\.'", call):
        return "c == '.'"
    return None


def main() -> int:
    if refuse_if_injecting("输入框规则检查"):
        return 1

    fields = collect_fields()
    classified = [f for f in fields if f["kind"]]
    phones = [f for f in classified if f["kind"] == "phone"]
    moneys = [f for f in classified if f["kind"] == "money"]

    print(
        f"扫到文本输入框 {len(fields)} 个；认得出类别的 {len(classified)} 个"
        f"（电话类 {len(phones)} / 金额类 {len(moneys)}）；书面排除 {len(EXCLUDED)} 条"
    )

    if "--list" in sys.argv:
        for kind, label in (("phone", "电话类"), ("money", "金额类")):
            print("\n---- " + label + " ----")
            for f in classified:
                if f["kind"] != kind:
                    continue
                ok = any(r in f["call"] for r in REQUIRED[kind])
                print(f"  [{'OK ' if ok else '!! '}] {f['file']}:{f['line']}  「{f['title']}」")
        print("\n---- 其余输入框（标题里没有关键词，不在本检查范围）----")
        for f in fields:
            if not f["kind"]:
                print(f"  · {f['file']}:{f['line']}  「{f['title'] or '(无标题)'}」")
        return 0

    errs: list[str] = []

    if len(fields) < MIN_FIELDS_SCANNED:
        errs.append(
            f"只扫到 {len(fields)} 个文本输入框（下限 {MIN_FIELDS_SCANNED}）——"
            f"是解析器失配了，不是项目里的输入框变少了。修本脚本的 FIELD_NAMES/_call_at。"
        )
    if len(phones) < MIN_PHONE_FIELDS or len(moneys) < MIN_MONEY_FIELDS:
        errs.append(
            f"认得出类别的框太少（电话 {len(phones)}，下限 {MIN_PHONE_FIELDS}；"
            f"金额 {len(moneys)}，下限 {MIN_MONEY_FIELDS}）——"
            f"多半是标题的写法变了（例如 label 换成了变量），"
            f"**不是项目里没有电话框了**。修本脚本的 _titles。"
        )

    for f in classified:
        if _key(f) in EXCLUDED:
            continue
        need = REQUIRED[f["kind"]]
        if not any(r in f["call"] for r in need):
            what = "电话" if f["kind"] == "phone" else "金额"
            errs.append(
                f"{f['file']}:{f['line']} 的「{f['title']}」看标题是{what}输入，"
                f"却没有走 InputRules（需要出现 {' 或 '.join(need)}）。\n"
                f"    → 改它的 onValueChange 走 InputRules（唯一实现在 "
                f"android/app/src/main/java/com/tapmoay/sorders/core/InputRules.kt），"
                f"或在本脚本 EXCLUDED 里写一条「为什么不适用」的理由。"
            )

    for f in fields:
        if f["readonly"]:
            continue
        hit = _hand_filter(f["call"])
        if hit:
            errs.append(
                f"{f['file']}:{f['line']} 的输入框在 onValueChange 里手写了数字过滤（{hit}）——\n"
                f"    那是 InputRules 的一份副本，改的时候一定漏掉一个。换成 InputRules.*Input。"
            )

    live = {_key(f) for f in classified}
    for k in sorted(EXCLUDED):
        if k not in live:
            errs.append(f"EXCLUDED 里的 {k} 已经不是一个真实存在的输入框了（理由变成化石）——请同步。")

    # 下单链路不许出现可改价的输入框（用户 2026-09-19 的规则）
    for rel, what in sorted(NO_PRICE_EDIT_FILES.items()):
        hits = [
            f for f in fields
            if f["file"] == rel and not f["readonly"]
            and any(k in " ".join(f["titles"]) for k in PRICE_TITLE_KEYS)
        ]
        for f in hits:
            errs.append(
                f"{f['file']}:{f['line']} 的「{f['title']}」是{what}里的**价格输入框** —— 下单的人不许改价。\n"
                f"    → 单价只能来自商品定价（商品管理 / 批发商定价维护）。"
                f"要展示就把输入框换成只读文字（`Text`），不要留一个能敲的框。"
            )
        if not any(f["file"] == rel for f in fields):
            errs.append(
                f"{rel} 里一个输入框都没扫到 —— {what}的路径变了或解析器失配，"
                f"「下单页不许改价」这条判据现在是空转的。请更新 `NO_PRICE_EDIT_FILES`。"
            )

    if errs:
        print("\n❌ 输入框规则检查没通过：\n")
        for e in errs:
            print("  · " + e + "\n")
        return 1

    print(
        f"✅ {len(classified)} 个电话/金额输入框全部走 InputRules"
        f"（另 {len(EXCLUDED)} 条书面排除），没有任何框手写数字过滤，"
        f"下单链路 {len(NO_PRICE_EDIT_FILES)} 个文件里没有价格输入框"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
