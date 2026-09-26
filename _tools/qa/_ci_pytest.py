# -*- coding: utf-8 -*-
"""CI 上跑全量后端用例，并把**失败摘要**发成 CI 注解。

## 为什么需要它（不是"多一层包装"）

这个仓库是**公开**的 —— Actions 的日志**匿名读不到**（要登录才能看）。
所以"CI 红了"这件事在本地只表现为一句 `Process completed with exit code 1`，
**看不到红在哪一条**。R3 为这个已经栽过（`test-parallel.yml` 因此加了"把摘要发成注解"）。

⚠️ R4 实测又栽了一次，而且方式更隐蔽：照抄 `test-parallel.yml` 的写法
（`pytest ... 2>&1 | tee 日志 || { grep FAILED 日志; }`）之后，
**注解里只有那一句"失败摘要如下"，摘要本身一条都没有** —— 因为那个日志文件是空的。
排查诊断管道本身花掉的时间，比排查被测代码还多。

所以这里换一条**不依赖 stdout 落盘**的路：`--junitxml`。
它是 pytest 自己写的结构化成败记录，**与终端输出有没有被吃掉无关**。

## 它做什么

1. 在 `backend/` 里跑 `pytest -q --tb=short --junitxml=<临时文件>`；
2. 解析 XML，把每条失败/报错**逐条**发成 `::error::` 注解（带文件:行 与断言摘要）；
3. 附上终端的最后若干行（有就发，没有也不影响上面那条）；
4. 用例全过 → 退出 0；有失败 → 退出 1（⛔ 不许把"没跑"当成"通过"）。

用法：python _tools/qa/_ci_pytest.py        （CI 的 gate.yml「跑全量用例」那一步）
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
MAX_ANNOTATIONS = 40


def annotation(text: str) -> None:
    """发一条 CI 注解（换行会被 GitHub 截断，压成一行）。"""
    print("::error::" + text.replace(chr(10), " ").replace(chr(13), " ")[:600])


def failures_from(xml_path: Path) -> list[str]:
    """从 junit xml 里抠出失败/报错（⛔ 不靠终端输出，那条路实测是空的）。"""
    if not xml_path.exists():
        return ["⛔ junit xml 没有生成（" + str(xml_path) + "）—— 失败原因读不出来，先看这一步的日志"]
    try:
        tree = ET.parse(str(xml_path))
    except ET.ParseError as exc:
        return ["⛔ junit xml 解析失败：" + str(exc)[:160] + "（多半是用例把进程跑挂了）"]
    out: list[str] = []
    for case in tree.iter("testcase"):
        bad = list(case.findall("failure")) + list(case.findall("error"))
        if not bad:
            continue
        node = bad[0]
        where = (case.get("classname") or "") + "::" + (case.get("name") or "")
        text = (node.get("message") or node.text or "").strip()
        line = (node.get("line") or "").strip()
        out.append("FAILED " + where.lstrip(":") + (" [行 " + line + "]" if line else "") + " —— " + text[:200])
    return out


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "junit.xml"
        cmd = [sys.executable, "-m", "pytest", "-q", "--tb=short", "--junitxml=" + str(xml_path)]
        print("跑：" + " ".join(cmd) + "（在 " + str(BACKEND) + " 里）")
        proc = subprocess.run(cmd, cwd=str(BACKEND), capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        out = (proc.stdout or "") + (proc.stderr or "")
        problems = failures_from(xml_path)
        print(out[-4000:])
        if proc.returncode == 0 and not problems:
            print("✅ 全部用例通过")
            return 0
        annotation("后端用例失败：共 " + str(len(problems)) + " 条；退出码 " + str(proc.returncode)
                   + "（明细下面逐条发）")
        for line in problems[:MAX_ANNOTATIONS]:
            annotation(line)
        if len(problems) > MAX_ANNOTATIONS:
            annotation("（还有 " + str(len(problems) - MAX_ANNOTATIONS) + " 条没发出来）")
        tail = [ln for ln in out.splitlines() if ln.strip()][-12:]
        if tail:
            annotation("终端尾部：" + " ｜ ".join(tail))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())