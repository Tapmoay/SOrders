#!/usr/bin/env python3
"""check_doc_claims.py —— 校验文档里的「声称」是否与代码一致（引用校验的第 2/3 层）。

为什么还需要这个脚本：
    `check_refs.py` 只校验**文件路径存在**。实测一份 168 处引用的文档，
    路径校验 100% 通过，同期的语义复核却找出 **9 处错误**——全是"文件存在但说法不对"。
    路径校验抓不到任何一处。本脚本补上两层：

    第 2 层 · 锚点身份：文档写 `file.py` L123 处，真的是它声称的那个符号吗？
    第 3 层 · 语义断言：文档声称的字段名/数量/取值，真的存在于源码吗？

当前实现的检查项（按需扩充——**每发现一类新的"声称"，就来这里加一条断言**）：
    A. 锚点身份  —— 从 08_CODE_LOCATOR.md 抓 `path` L### ，确认该行不是空行/明显错位（人工复核辅助）
    B. 模型字段  —— 03_BACKEND_DETAILS.md 的数据模型表，逐字段到 app/models/ 的 ORM 里核对
    C. 层规模    —— 03 里关于各层文件数/行数的声称，实际数一遍

用法（在 backend/ 下）：
    python -m scripts.check_doc_claims                 # 跑全部检查
    python -m scripts.check_doc_claims --check fields  # 只跑某一项
退出码：0 = 全部一致；1 = 有不一致（可接 CI）。
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)                      # …/backend
REPO = os.path.dirname(BACKEND)                      # 仓库根
APP = os.path.join(BACKEND, "app")
DOCS = os.path.join(REPO, "docs", "PROJECT_MAP")


# ─────────────────────────── 通用 ───────────────────────────

def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _strip_parens(s: str) -> str:
    """去掉括号内容（里面常带 ⚠️ 说明，会干扰字段名解析）。"""
    out, depth = [], 0
    for ch in s:
        if ch in "（(":
            depth += 1
        elif ch in "）)":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def _model_columns(fname: str) -> tuple[set[str], set[str]]:
    """返回 (mapped_column 属性名, 全部类属性名)。"""
    path = os.path.join(APP, "models", fname)
    if not os.path.isfile(path):
        return set(), set()
    try:
        tree = ast.parse(_read(path))
    except SyntaxError:
        return set(), set()
    cols, attrs = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for st in node.body:
            if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                attrs.add(st.target.id)
                try:
                    src = ast.unparse(st.value) if st.value else ""
                except Exception:
                    src = ""
                if "mapped_column" in src:
                    cols.add(st.target.id)
    return cols, attrs


# ─────────────────────────── 检查 A：锚点身份 ───────────────────────────

def check_anchors(verbose: bool) -> tuple[int, int, list[str]]:
    """08_CODE_LOCATOR.md 的 `path` L### 锚点：确认行号落在文件内且非空行。

    为什么只做"非空 + 在范围内"而不做"必须是 def 行"：08 的锚点是**混合类型**——
    def 行、装饰器行、赋值行、常量行都有（危险区要的正是赋值行）。
    想校验"是不是声称的那个符号"需要逐条声明锚点类型，那是人工工作，
    本脚本只拦住最硬的两类错误：**越界**与**指向空行**。
    """
    doc = os.path.join(DOCS, "08_CODE_LOCATOR.md")
    if not os.path.isfile(doc):
        return 0, 0, []
    path_tok = re.compile(r"^[A-Za-z0-9_\-./]+\.(?:py|kt|md)$")
    l_after = re.compile(r"^\s*[（(]?\s*(?:\*\*)?L(\d+)")
    checked, bad = 0, []
    for lineno, line in enumerate(_read(doc).splitlines(), 1):
        parts = line.split("`")
        for i in range(1, len(parts), 2):
            tok = parts[i].strip()
            if not path_tok.match(tok):
                continue
            nxt = parts[i + 1] if i + 1 < len(parts) else ""
            m = l_after.match(nxt)
            if not m:
                continue
            ln = int(m.group(1))
            cands = [tok] if tok.startswith(("backend/", "android/", "docs/")) else [f"backend/{tok}"]
            full = next((os.path.join(REPO, c.replace("/", os.sep)) for c in cands
                         if os.path.isfile(os.path.join(REPO, c.replace("/", os.sep)))), None)
            if full is None:
                # 裸文件名/缩写路径交给 check_refs.py，这里不重复报
                continue
            src = _read(full).splitlines()
            checked += 1
            if ln > len(src):
                bad.append(f"08:{lineno}  `{tok}` L{ln} 越界（文件仅 {len(src)} 行）")
            elif not src[ln - 1].strip():
                bad.append(f"08:{lineno}  `{tok}` L{ln} 指向空行")
    return checked, 0, bad


# ─────────────────────────── 检查 B：模型字段 ───────────────────────────

def check_fields(verbose: bool) -> tuple[int, int, list[str]]:
    """03_BACKEND_DETAILS.md 的「数据模型」表：逐字段到 ORM 里核对。

    这类错误（字段名写错但文件名对）路径校验 100% 放行，照着改会 AttributeError，
    或者更糟——静默查不到列。实测一次抓出 3 处，其中 1 处是真错
    （文档写 `image`，模型里是 `image_url`）。
    """
    doc = os.path.join(DOCS, "03_BACKEND_DETAILS.md")
    if not os.path.isfile(doc):
        return 0, 0, []
    checked, bad = 0, []
    for lineno, line in enumerate(_read(doc).splitlines(), 1):
        if not line.startswith("| ") or line.startswith("| 表 |") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        fname_m = re.search(r"([a-z_]+\.py)", cells[1])
        if not fname_m:
            continue
        fname = fname_m.group(1)
        cols, attrs = _model_columns(fname)
        if not cols:
            continue
        cleaned = _strip_parens(cells[2]).split("⚠️")[0]
        prev = ""
        for seg in cleaned.split("/"):
            raw = seg.strip()
            wildcard = "*" in raw
            tok = re.match(r"([a-z_][a-z0-9_]*)", raw.replace("*", "").replace("`", "").strip())
            if not tok:
                continue
            name = tok.group(1)
            if name in ("JSON", "TEXT", "in", "out"):
                continue
            checked += 1
            if wildcard and any(c.startswith(name) for c in cols):
                continue
            if name in cols:
                prev = name
                continue
            # 缩写段（`period_from/to` 里的 `to`）→ 用上一段的前缀补全
            if prev and "_" in prev and (prev.rsplit("_", 1)[0] + "_" + name) in cols:
                prev = prev.rsplit("_", 1)[0] + "_" + name
                continue
            bad.append(f"03:{lineno}  `{fname}` 声称的字段 `{name}` 不存在"
                       + ("（同名属性存在但不是列）" if name in attrs else ""))
            prev = name
    return checked, 0, bad


# ─────────────────────────── 检查 C：层规模声称 ───────────────────────────

def check_layer_sizes(verbose: bool) -> tuple[int, int, list[str]]:
    """核对"某层 N 文件 M 行""某目录 N 文件"这类数量声称——**扫描全部文档**。

    ⚠️ 踩过：第一版只读 03，结果 `ui/dispatcher/，29 文件` 这条写在 08 里的声称
       根本没人守——负向测试（把它改成 30）竟然全绿，才发现校验器压根没看那个文件。
       **校验器"没看"和"看过了没问题"在输出上必须能区分。**
    """
    bad, checked = [], 0

    def count(sub: str) -> tuple[int, int]:
        d = os.path.join(APP, sub)
        f = n = 0
        for dp, dn, fs in os.walk(d):
            dn[:] = [x for x in dn if x != "__pycache__"]
            for x in fs:
                if x.endswith(".py"):
                    f += 1
                    n += len(_read(os.path.join(dp, x)).splitlines())
        return f, n

    real = {s: count(s) for s in ("api/v1", "services")}
    android = os.path.join(REPO, "android", "app", "src", "main", "java",
                           "com", "tapmoay", "sorders")

    docs = ([os.path.join(DOCS, f) for f in sorted(os.listdir(DOCS)) if f.endswith(".md")]
            if os.path.isdir(DOCS) else [])
    for doc in docs:
        name = os.path.basename(doc)
        text = _read(doc)

        # 「api/v1/ 24 文件 4,511 行 vs services/ 22 文件 2,656 行」
        for sub, (rf, rn) in real.items():
            for m in re.finditer(re.escape(sub) + r"[`/]*\s*(\d+)\s*文件\s*([\d,]+)\s*行", text):
                checked += 2
                if int(m.group(1)) != rf:
                    bad.append(f"{name} 声称 {sub} {m.group(1)} 文件，实际 {rf}")
                if int(m.group(2).replace(",", "")) != rn:
                    bad.append(f"{name} 声称 {sub} {m.group(2)} 行，实际 {rn}")

        # Android 侧目录文件数：「ui/dispatcher/，29 文件」
        for m in re.finditer(r"`(ui/[a-z_]+/)`[，,]\s*(\d+)\s*文件", text):
            sub, claimed = m.group(1), int(m.group(2))
            d = os.path.join(android, sub.replace("/", os.sep).rstrip(os.sep))
            checked += 1
            if not os.path.isdir(d):
                bad.append(f"{name} 声称 {sub} 有 {claimed} 文件，但目录不存在")
                continue
            real_n = len([f for f in os.listdir(d) if f.endswith(".kt")])
            if real_n != claimed:
                bad.append(f"{name} 声称 {sub} {claimed} 个 .kt，实际 {real_n} 个")

    if verbose:
        print(f"    扫描 {len(docs)} 份文档；实测 api/v1 {real['api/v1']} / services {real['services']}")
    return checked, 0, bad


# ─────────────────────────── 检查 D：逐文件行数/端点声称 ───────────────────────────

_CLAIM_RES = (
    # `path.py`（123 行）
    re.compile(r"`([A-Za-z0-9_\-./]+\.py)`（([\d,]+)\s*行"),
    # `path.py` 共 **123 行 / 23 个端点**  /  `path.py` 单文件 **123 行**
    re.compile(r"`([A-Za-z0-9_\-./]+\.py)`[^\n`]{0,12}?\*\*([\d,]+)\s*行(?:\s*/\s*(\d+)\s*个端点)?"),
)

_SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", ".pytest_cache", "node_modules", "build", "dist"}
_INDEX: dict | None = None


def _index() -> dict:
    """建索引：精确相对路径 / 路径后缀 / 裸文件名 → 真实文件。

    ⚠️ 这个索引是必需的，不是优化。第一版只试了 `backend/<rel>` 与 `<rel>` 两种拼法，
       结果 `api/v1/reports.py`、`data_retention.py` 这类**文档里省略了中段的写法全部解析失败，
       而失败被静默跳过** —— 校验器报"全部一致"，实际上有 4 处声称根本没查。
       **"校验器跳过了没查"和"校验通过"必须在输出上能区分**，否则是虚假安全感。
    """
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    by_rel, by_suffix, by_base = {}, {}, {}
    for dp, dn, fs in os.walk(REPO):
        dn[:] = [d for d in dn if d not in _SKIP_DIRS and not d.startswith(".")]
        for f in fs:
            if not f.endswith(".py"):
                continue
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, REPO).replace("\\", "/")
            by_rel[rel] = full
            parts = rel.split("/")
            for i in range(len(parts)):
                by_suffix.setdefault("/".join(parts[i:]), []).append(full)
            by_base.setdefault(f, []).append(full)
    _INDEX = {"rel": by_rel, "suffix": by_suffix, "base": by_base}
    return _INDEX


def _resolve(rel: str) -> tuple[str | None, str]:
    """返回 (真实路径, 解析方式)。解析不到时方式为 '未解析'——**必须计入跳过数**。"""
    idx = _index()
    key = rel.replace("\\", "/").lstrip("./")
    if key in idx["rel"]:
        return idx["rel"][key], "精确"
    hits = idx["suffix"].get(key)
    if hits:
        # 后缀可能匹配多处（models/x.py 与 api/v1/x.py），取最短路径，并标记为有歧义
        hits = sorted(hits, key=len)
        return hits[0], ("后缀" if len(hits) == 1 else "后缀歧义")
    hits = idx["base"].get(os.path.basename(key))
    if hits:
        return sorted(hits, key=len)[0], "裸名"
    return None, "未解析"


def check_file_sizes(verbose: bool) -> tuple[int, int, list[str]]:
    """文档里 `path.py`（N 行）/ `path.py` 共 **N 行 / M 个端点** 这类声称，逐个实际数一遍。

    行数是最容易随口写、也最容易在重构后腐烂的一类数字。
    ⚠️ 只匹配「路径 + 紧跟的行数」这种无歧义写法——宽松匹配会把正文里引用的
       **代码注释原文**（如"已被 307 行的路由覆盖"）也算进来，造成假阳性。
    ⚠️ **解析不到路径的声称会单独报出来**，不再静默跳过（见 `_index()` 的说明）。
    """
    bad, checked, skipped, resolved = [], 0, 0, []
    for docname in sorted(os.listdir(DOCS)):
        if not docname.endswith(".md") or docname.startswith("9") or docname.startswith("10"):
            continue
        docpath = os.path.join(DOCS, docname)
        for lineno, line in enumerate(_read(docpath).splitlines(), 1):
            for pat_idx, pat in enumerate(_CLAIM_RES):
                for m in pat.finditer(line):
                    rel = m.group(1)
                    nlines = m.group(2)
                    neps = int(m.group(3)) if (pat_idx == 1 and m.lastindex and m.group(3)) else None
                    full, how = _resolve(rel)
                    if full is None:
                        skipped += 1
                        bad.append(f"{docname}:{lineno}  无法解析引用 `{rel}`（这条**没被校验**，请改成可解析的写法）")
                        continue
                    resolved.append((docname, lineno, rel, how))
                    src = _read(full).splitlines()
                    checked += 1
                    if len(src) != int(nlines.replace(",", "")):
                        bad.append(f"{docname}:{lineno}  声称 {rel} {nlines} 行，实际 {len(src)} 行")
                    if neps is not None:
                        checked += 1
                        real_eps = len(re.findall(
                            r"^\s*@router\.(get|post|put|patch|delete)\(", _read(full), re.M))
                        if real_eps != neps:
                            bad.append(f"{docname}:{lineno}  声称 {rel} {neps} 个端点，实际 {real_eps} 个")
    if verbose and resolved:
        amb = [r for r in resolved if "歧义" in r[3]]
        if amb:
            print(f"    ⚠️ 有歧义的路径引用 {len(amb)} 处（取最短匹配）: "
                  + ", ".join(f"{d}:{l} {r}" for d, l, r, _ in amb))
    if skipped:
        print(f"    ⚠️ 跳过 {skipped} 处（引用无法解析 → 未校验）")
    return checked, skipped, bad


# ─────────────────────────── 检查 E：权限点/端点计数声称 ───────────────────────────

_ROUTE_RE = re.compile(r"^\s*@(?:router|application)\.(get|post|put|patch|delete)\(", re.M)
_REQ_PERM_RE = re.compile(r"Depends\(require_permission\(\s*Permission\.([A-Z_]+)")
_INLINE_PERM_RE = re.compile(r"role_has_permission\([^,]+,\s*Permission\.([A-Z_]+)")


def _permission_enum() -> set[str]:
    p = os.path.join(APP, "core", "rbac.py")
    if not os.path.isfile(p):
        return set()
    try:
        tree = ast.parse(_read(p))
    except SyntaxError:
        return set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Permission":
            return {t.id for st in node.body if isinstance(st, ast.Assign)
                    for t in st.targets if isinstance(t, ast.Name)}
    return set()


def _counts() -> dict:
    """数一遍端点与权限点用量——这就是 `gen_endpoint_index.py` 生成 08A 时算的东西，
    这里用**独立的正则实现**重算一次，用来核对文档里引用的数字。"""
    files = []
    for rel in ("main.py",):
        files.append(os.path.join(APP, rel))
    v1 = os.path.join(APP, "api", "v1")
    for x in sorted(os.listdir(v1)):
        if x.endswith(".py"):
            files.append(os.path.join(v1, x))

    endpoints = with_req = 0
    req_perms: set[str] = set()
    inline_perms: set[str] = set()
    for f in files:
        if not os.path.isfile(f):
            continue
        txt = _read(f)
        endpoints += len(_ROUTE_RE.findall(txt))
        hits = _REQ_PERM_RE.findall(txt)
        with_req += len(hits)
        req_perms.update(hits)
        inline_perms.update(_INLINE_PERM_RE.findall(txt))
    all_perms = _permission_enum()
    used = req_perms | inline_perms
    return {
        "endpoints": endpoints,
        "endpoints_with_require_permission": with_req,
        "all_permissions": len(all_perms),
        "permissions_used": len(used),
        "permissions_via_depends": len(req_perms),
        "permissions_unused": len(all_perms - used),
    }


def check_counts(verbose: bool) -> tuple[int, int, list[str]]:
    """核对"多少个端点/多少权限点"这类计数声称——**扫描全部文档 + 入口文件**。

    这类数字**有信息量但不该手写**——它们是"代码的当前状态"，一改代码就漂。
    正确处理不是删掉（丢信息），而是**写成断言让机器守住**（漂了就红）。
    ⚠️ 第一版只扫 02，于是 AGENTS.md / 03 / 08 里的同一个数字**没人守**——
       同一个事实写在几处，校验就必须覆盖几处，否则"改了这处忘了那处"照样发生。
    """
    c = _counts()
    bad, checked = [], 0

    # 每条规则 = (正则, [(捕获组序号, 真值键, 人类可读的称呼), ...])
    # ⚠️ 组序号写死，不做动态推断——用计数器推组号会让同一个正则在多条规则里复用时错位，
    #    把正确的数字报成错误。**规则表要能一眼看懂，不要图省事。**
    RULES: list[tuple[str, list[tuple[int, str, str]]]] = [
        (r"全部\s*(\d+)\s*个权限点的归属",
         [(1, "all_permissions", "权限点总数")]),
        (r"(\d+)\s*个权限点里只有\s*(\d+)\s*个被端点引用",
         [(1, "all_permissions", "权限点总数"),
          (2, "permissions_used", "被端点引用的权限点数")]),
        (r"(\d+)\s*个走签名",
         [(1, "permissions_via_depends", "走签名的权限点数")]),
        (r"（共\s*(\d+)\s*个端点）",
         [(1, "endpoints_with_require_permission", "挂了 require_permission 的端点数")]),
        (r"(\d+)\s*个端点里只有\s*(\d+)\s*个挂了",
         [(1, "endpoints", "端点总数"),
          (2, "endpoints_with_require_permission", "挂了 require_permission 的端点数")]),
        (r"声明了但没有任何端点引用的权限点：(\d+)\s*/\s*(\d+)",
         [(1, "permissions_unused", "未使用权限点数"),
          (2, "all_permissions", "权限点总数")]),
        (r"(\d+)\s*个端点\s*/\s*URL→handler", [(1, "endpoints", "端点总数")]),
        (r"（(\d+)\s*个端点，按文件分组）", [(1, "endpoints", "端点总数")]),
    ]

    targets: list[str] = []
    if os.path.isdir(DOCS):
        targets += [os.path.join(DOCS, f) for f in sorted(os.listdir(DOCS)) if f.endswith(".md")]
    entry = os.path.join(REPO, "AGENTS.md")
    if os.path.isfile(entry):
        targets.append(entry)

    for doc in targets:
        name = os.path.relpath(doc, REPO).replace("\\", "/")
        text = _read(doc)
        for pat, groups in RULES:
            for m in re.finditer(pat, text):
                for gi, key, label in groups:
                    claimed = int(m.group(gi))
                    checked += 1
                    if claimed != c[key]:
                        bad.append(f"{name} 声称{label} {claimed}，实际 {c[key]}")

    if verbose:
        print(f"    实测：端点 {c['endpoints']}（其中挂 require_permission "
              f"{c['endpoints_with_require_permission']}）/ 权限点 {c['all_permissions']}"
              f"（走签名 {c['permissions_via_depends']}，合计被引用 {c['permissions_used']}，"
              f"未使用 {c['permissions_unused']}）")
    return checked, 0, bad


def check_call_sites(verbose: bool) -> tuple[int, int, list[str]]:
    """核对"某函数被调用 N 处""某写法共 N 处"这类**调用点计数**。

    为什么单独一类：这类数字**最容易凭印象写，而且错得最隐蔽**——文件名是对的、
    函数名是对的，只有数字不对，路径校验和符号校验都发现不了。
    实测一次抓出 2 处真错：
      · `enrich_order_out` 文档写"20 个调用点（orders.py 19 处 + freight_settlement.py）"，
        实际 18 处全在 orders.py；`freight_settlement.py` 那行是 **`# noqa: F401` 的死导入**。
      · `ledger_to_out` 文档写"6 个调用点"，实际 4 处。
    """
    c = _counts()
    syntax = _syntax_counts()
    bad, checked = [], 0

    # (正则, 真值键, 称呼)  —— 组 1 = 文档声称的数字
    RULES: list[tuple[str, str, str]] = [
        (r"全后端共\s*\*\*(\d+)\s*处\*\*\s*`OrderStatus`\s*赋值",
         "order_status_assign", "OrderStatus 赋值处数"),
        (r"全后端\s*`OrderStatus`\s*赋值共\s*\*\*(\d+)\s*处\*\*",
         "order_status_assign", "OrderStatus 赋值处数"),
        (r"手写\s*`ALTER TABLE`，共\s*(\d+)\s*处",
         "alter_table", "手写 ALTER TABLE 处数"),
        (r"全后端只有\s*\*\*(\d+)\s*处\*\*\s*写\s*`CashFlow`",
         "cashflow_writes", "CashFlow 写入处数"),
        (r"`[^`]*enrich_order_out`[^\n]{0,80}\*\*(\d+)\s*处调用\*\*",
         "enrich_calls", "enrich_order_out 调用处数"),
        (r"`[^`]*ledger_to_out`[^\n]{0,80}\*\*(\d+)\s*处调用\*\*",
         "ledger_calls", "ledger_to_out 调用处数"),
    ]

    docs = ([os.path.join(DOCS, f) for f in sorted(os.listdir(DOCS)) if f.endswith(".md")]
            if os.path.isdir(DOCS) else [])
    truth = dict(c)
    truth.update(syntax)

    for doc in docs:
        name = os.path.basename(doc)
        text = _read(doc)
        for pat, key, label in RULES:
            for m in re.finditer(pat, text):
                checked += 1
                if int(m.group(1)) != truth.get(key, -1):
                    bad.append(f"{name} 声称{label} {m.group(1)}，实际 {truth.get(key)}")

    if verbose:
        print("    实测：" + " / ".join(f"{k}={v}" for k, v in syntax.items()))
    return checked, 0, bad


def _syntax_counts() -> dict[str, int]:
    """数几类"写法出现的处数"——与文档里的"共 N 处"对照。"""
    def walk(pat: str, sub: str | None = None) -> int:
        root = os.path.join(APP, sub) if sub else APP
        n = 0
        for dp, dn, fs in os.walk(root):
            dn[:] = [d for d in dn if d != "__pycache__"]
            for f in fs:
                if f.endswith(".py"):
                    for line in _read(os.path.join(dp, f)).splitlines():
                        if re.search(pat, line):
                            n += 1
        return n

    return {
        # 状态赋值：`xxx.status = OrderStatus.YYY`（排除类定义/枚举定义）
        "order_status_assign": walk(r"\.status\s*=\s*OrderStatus\.\w+"),
        # 手写迁移
        "alter_table": walk(r"ALTER\s+TABLE"),
        # CashFlow 构造（排除 models 里的 class 定义）
        "cashflow_writes": walk(r"(?<!class )CashFlow\("),
        # 调用点：只数 `函数名(` 且不是 `def 函数名(`
        "enrich_calls": walk(r"(?<!def )enrich_order_out\s*\("),
        "ledger_calls": walk(r"(?<!def )ledger_to_out\s*\("),
    }


def check_markdown(verbose: bool) -> tuple[int, int, list[str]]:
    """结构体检：表格列数一致性 / 代码段内裸竖线 / 标题跳级 / 空标题 / 代码块配对。

    为什么算"断言校验"：**渲染错位不会报错、不会崩，只是静静显示成另一张表**。
    读的人以为"文档就是这么写的"，agent 可能把错位的列当成真实字段——
    而 `check_refs` 看路径、其它检查看数字，**没有一项会碰到表格结构**。
    实测一次抓出 **10 处真实破损**（`kind=shipper|member`、`direction(IN|OUT)`、
    `status(DRAFT|CONFIRMED|PAID|CANCELLED)` 这类枚举里的裸竖线把单元格劈开了）。

    ⚠️ 本检查器自己也踩过两个假阳性（都已修）：
       ① 用 `` `[^`]*\\|[^`]*` `` 找裸竖线 → 从第一个反引号跨到最后一个，
          把**表格分隔符**当成代码段内容，报了 400+ 条假阳性。
          正解：按反引号切段，只看奇数下标。
       ② 没跳过 ``` 围栏 → 代码块里的 `# 注释` 被当成 h1，后续正常的 ### 被判"标题跳级"。
    """
    bad, checked = [], 0

    targets: list[str] = []
    if os.path.isdir(DOCS):
        targets += [os.path.join(DOCS, f) for f in sorted(os.listdir(DOCS)) if f.endswith(".md")]
    entry = os.path.join(REPO, "AGENTS.md")
    if os.path.isfile(entry):
        targets.append(entry)

    def cells(row: str) -> int:
        return row.replace("\\|", "\x00").count("|")

    for p in targets:
        name = os.path.relpath(p, REPO).replace("\\", "/")
        raw = _read(p).splitlines()

        # 剥掉代码块（保留行号），结构类检查只看块外内容
        code: list[str] = []
        inside = False
        for l in raw:
            if l.lstrip().startswith("```"):
                inside = not inside
                code.append("")
            else:
                code.append("" if inside else l)

        fences = sum(1 for l in raw if l.lstrip().startswith("```"))
        checked += 1
        if fences % 2:
            bad.append(f"{name} 代码块未闭合（``` 出现 {fences} 次）")

        # 表格列数一致性
        i = 0
        while i < len(code):
            if code[i].lstrip().startswith("|"):
                j, blk = i, []
                while j < len(code) and code[j].lstrip().startswith("|"):
                    blk.append((j + 1, code[j]))
                    j += 1
                body = [(ln, l) for ln, l in blk
                        if not re.match(r"^\s*\|[\s:\-|]+\|\s*$", l)]
                if len(body) > 1:
                    checked += len(body) - 1
                    base = cells(body[0][1])
                    for ln, l in body[1:]:
                        if cells(l) != base:
                            bad.append(f"{name}:{ln} 表格列数不一致（表头 {base} 个分隔符，本行 {cells(l)}）")
                i = j
            else:
                i += 1

        # 代码段内裸竖线（按反引号切段，只看奇数下标 = 代码段内部）
        for ln, l in enumerate(code, 1):
            if not l.lstrip().startswith("|"):
                continue
            parts = l.split("`")
            for k in range(1, len(parts), 2):
                if re.search(r"(?<!\\)\|", parts[k]) and not re.search(r"\\\|", parts[k]):
                    bad.append(f"{name}:{ln} 代码段内裸竖线会把表格劈开: `{parts[k][:36]}`")
                    break

        # 标题跳级 / 空标题
        prev = 0
        for ln, l in enumerate(code, 1):
            if re.match(r"^#{1,6}\s*$", l):
                bad.append(f"{name}:{ln} 空标题")
                continue
            m = re.match(r"^(#{1,6})\s", l)
            if m:
                lvl = len(m.group(1))
                checked += 1
                if prev and lvl > prev + 1:
                    bad.append(f"{name}:{ln} 标题跳级 {prev}→{lvl}: {l[:36]}")
                prev = lvl

    if verbose:
        print(f"    扫描 {len(targets)} 份文档")
    return checked, 0, bad


CHECKS = {"anchors": check_anchors, "fields": check_fields,
          "sizes": check_layer_sizes, "files": check_file_sizes,
          "counts": check_counts, "calls": check_call_sites,
          "markdown": check_markdown}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")     # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        prog="python -m scripts.check_doc_claims",
        description="校验文档里的断言是否与代码一致（引用校验的第 2/3 层）")
    ap.add_argument("--check", nargs="*", default=None,
                    help=f"只跑指定检查：{', '.join(CHECKS)}")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    names = args.check or list(CHECKS)

    # ⚠️ 拼错的检查项名必须**报错退出**，不能"警告一下然后报通过"。
    #    否则 `--check ancohors` 会输出"文档断言与代码一致 ✅"——**一个字都没查，却是绿的**。
    #    这与本脚本要防的那类错误同构：把"没看"显示成"没问题"。
    unknown = [n for n in names if n not in CHECKS]
    if unknown:
        print(f"error: 未知检查项 {unknown}；可用：{', '.join(CHECKS)}", file=sys.stderr)
        return 2
    if not names:
        print("error: 没有可跑的检查项（扫描范围为空）", file=sys.stderr)
        return 2

    total_checked, all_bad = 0, []
    for name in names:
        fn = CHECKS[name]
        n, _, bad = fn(not args.quiet)
        total_checked += n
        all_bad.extend(bad)
        if not args.quiet:
            print(f"  {name:10s} 核对 {n:4d} 项  —  {len(bad)} 处不一致")

    print(f"\n合计核对 {total_checked} 项")
    if all_bad:
        print(f"\n不一致 {len(all_bad)} 处：")
        for b in all_bad:
            print("  • " + b)
        print("\n⚠️ 这类错误 check_refs.py 查不出来（文件路径都是对的）。修完重跑。")
        return 1
    if total_checked == 0:
        # 0 项也报"一致"是另一种假绿：说明规则一条都没匹配上（文档改了措辞、或扫描范围不对）
        print("⚠️ 核对 0 项——**没有任何断言被执行**。这不算通过：\n"
              "   通常是文档措辞变了导致正则不再匹配，或扫描范围不对。请检查规则表。",
              file=sys.stderr)
        return 1
    print("文档断言与代码一致 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
