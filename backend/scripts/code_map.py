"""生成「签名地图」：把代码压成"文件 → 符号 + 签名"的清单。

用途：给 agent 一张全仓结构快照，替代"读全部源文件"。
实测参考（本项目 backend，118 文件 / 490,805 字符）：
    全量源码 ≈ 145k tokens  →  签名地图 ≈ 12.9k tokens（压缩约 11×，按 token 比）
且文件召回 100%——它不做检索，所以没有"漏掉某个文件"的假阴性风险。

⚠️ token 估算口径：源码里中文只占约 4%，所以 `chars/3.5` 与中文口径差别不大（+4%）；
   但**文档类内容中文占 25~47%，`chars/3.5` 会低估 1.3~1.7 倍**。
   本脚本用 `CJK×0.7 + 其余×0.28`（见 `est_tokens`）。

用法（在 backend/ 下）：
    python -m scripts.code_map .
    python -m scripts.code_map . --out map_full.txt

配套：文档引用校验用 `python -m scripts.check_refs <文档>`（见 check_refs.py）。
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys

SKIP_DIRS = {
    "__pycache__", ".git", ".venv", "venv", ".pytest_cache", "node_modules",
    ".gradle", "build", "dist", ".idea", ".mypy_cache", ".ruff_cache",
    "graft", ".graft", "uploads", "_agent",
}

_CJK = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


def est_tokens(text: str) -> float:
    """估算 token 数——**中文和英文不能用一个系数**。

    ⚠️ 这里踩过坑：一直用 `chars / 3.5`（英文经验值：约 3.5 字符/token）。
    但中文在主流 BPE 分词器里约 **0.7 token/字**（常见词会被并成一个 token），
    于是对中文文档会**系统性低估 1.2~1.7 倍**，而"预算是否合规"的结论全建立在这个数上。

    分两段估：CJK 及全角标点 ×0.7，其余（ASCII/代码/空白）×0.28（≈3.5 字符/token）。
    这是启发式，用来判断**量级与相对比例**，不是精确值。
    """
    n_cjk = len(_CJK.findall(text))
    n_other = len(text) - n_cjk
    return n_cjk * 0.7 + n_other * 0.28


def _sig(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """把函数定义压成一行签名。"""
    a = node.args
    parts = [arg.arg for arg in a.posonlyargs + a.args]
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")
    parts.extend(arg.arg for arg in a.kwonlyargs)
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)
    ret = ""
    if node.returns is not None:
        try:
            ret = " -> " + ast.unparse(node.returns)
        except Exception:
            pass
    # 只保留有信息量的装饰器（路由动词 / 校验器 / property）
    deco = ""
    for d in node.decorator_list:
        try:
            short = ast.unparse(d).split("(")[0].split(".")[-1]
        except Exception:
            continue
        if short in ("get", "post", "put", "patch", "delete", "property",
                     "staticmethod", "classmethod", "field_validator",
                     "model_validator", "lru_cache"):
            deco += " @" + short
    return f"{node.name}({', '.join(parts)}){ret}{deco}"


def _doc_line(node: ast.AST) -> str:
    """取 docstring 首行，作为该符号的一句话说明。"""
    d = ast.get_docstring(node)  # type: ignore[arg-type]
    if not d:
        return ""
    line = d.strip().splitlines()[0].strip()
    return ("  # " + line[:70]) if line else ""


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):     # Windows 控制台默认 GBK
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(
        prog="python -m scripts.code_map",
        description="生成签名地图（文件 → 符号 + 签名）")
    ap.add_argument("dir", nargs="?", default=".", help="要扫描的代码目录")
    ap.add_argument("--out", help="输出文件（省略则只打印统计）")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.dir)
    if not os.path.isdir(root):
        print(f"error: 目录不存在: {root}", file=sys.stderr)
        return 2

    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(os.path.join(dirpath, fn))
    files.sort()

    out: list[str] = []
    n_sym = 0
    src_text_parts: list[str] = []
    for path in files:
        rel = os.path.relpath(path, root).replace("\\", "/")
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError as exc:
            out.append(f"{rel}\n  <读取失败: {exc}>")
            continue
        src_text_parts.append(raw)
        try:
            tree = ast.parse(raw)
        except SyntaxError as exc:
            out.append(f"{rel}\n  <解析失败: {exc}>")
            continue

        lines: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                n_sym += 1
                lines.append(f"  def {_sig(node)}{_doc_line(node)}")
            elif isinstance(node, ast.ClassDef):
                n_sym += 1
                bases = ""
                try:
                    if node.bases:
                        bases = "(" + ", ".join(ast.unparse(b) for b in node.bases) + ")"
                except Exception:
                    pass
                lines.append(f"  class {node.name}{bases}{_doc_line(node)}")
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        n_sym += 1
                        lines.append(f"    def {_sig(sub)}")
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id.isupper():
                        lines.append(f"  {tgt.id} = ...")
        if lines:
            out.append(rel + "\n" + "\n".join(lines))

    text = "\n".join(out)
    src_text = "\n".join(src_text_parts)
    src_chars = len(src_text)          # ⚠️ 用字符数，不是 os.path.getsize（那是 UTF-8 字节数，中文会差 3 倍）

    print(f"文件数        : {len(files)}")
    print(f"符号数        : {n_sym}")
    print(f"签名地图       : {len(text)} chars  ≈ {est_tokens(text):,.0f} tokens")
    print(f"全量源码       : {src_chars} chars  ≈ {est_tokens(src_text):,.0f} tokens")
    if text:
        print(f"压缩比        : {est_tokens(src_text) / max(est_tokens(text), 1):.1f}x  "
              f"（按 token 比；按字符比 {src_chars / len(text):.1f}x）")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"已写出        : {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
