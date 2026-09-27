#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反向验证：把「开发规范接线」这条判据**逐条弄坏**，看它**真的会红**。

### 为什么这块必须反向验证

`_check_dev_spec.py` 守的是**接线**（规范 ↔ 入口 ↔ 登记簿之间的那几根线），
而"接线类"判据最容易写成**看起来在检查、其实什么都不看**的东西：
把"文件存在"当接线、把目录里的文件名当已登记、把 `AGENTS.md` 里一句
"详见 xxx"当链接……每一种都能让判据永远绿，而线其实早就断了。

还有一条**正面**场景必须一起验：**写对了就必须能过**
（一条永远红的检查等于没有检查 —— 本项目 §15 的教训）。

### ⚠️ 这张表**必须保持"字面量形状"**（2026-09-27 实测踩到）

`_tools/qa/_check_reverse_verify_anchors.py` 会**静态**解析每一份反向验证脚本，
从形如「(标签, 目标文件, 被替换的原文, 替换成, …)」的**元组字面量**里把锚点抽出来，
每天核对"原文还在不在" —— 这样锚点腐烂**当天**就报红，不用等谁跑一次 50 分钟的全量。

**本文件第一版把注入写成 `s_xxx(sb)` 函数 + `sb.replace(...)` 方法调用，
结果被抽出来的是「0 条」** —— 锚点一条都没被核对（而"抽不出来"看起来是**绿的**：
没有锚点可核对 = 没有报错）。所以改成现在这张纯数据的表：

    (标签, 目标文件, 被替换的原文, 替换成, 期望是否变红, 跑哪条判据)

⛔ 别把「原文」那一格写成变量或函数返回值 —— 那样锚点又**静默不检查**了。
（本例与 `_reverse_verify_core_freeze.py` 的「0 条」是同一个成因；那份还没改，
记在这里，谁顺手谁改。）

⛔ 每条注入都用 `Sandbox` 按**字节**记住原样并还原 —— **不用 `git checkout --`**：
那会把未提交的真实改动一起抹掉（本项目实测抹掉过一个文件整轮的重构）。

用法：python _tools/qa/_reverse_verify_dev_spec.py    # 11 条场景全部成立 → 退出码 0
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

RUNNER = HERE / "_check_dev_spec.py"
REACH = HERE / "_check_doc_reachability.py"

SPEC = ROOT / "docs" / "DEVELOPMENT_SPEC.md"
AGENTS = ROOT / "AGENTS.md"
INDEX = ROOT / "docs" / "PROJECT_MAP" / "INDEX.md"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"
CHANGES_README = ROOT / "docs" / "changes" / "README.md"
CHANGES_TEMPLATE = ROOT / "docs" / "changes" / "_TEMPLATE.md"
GOV1 = ROOT / "docs" / "changes" / "GOV-0001.md"

#: 场景表 —— ⚠️ 形状是**机器契约**（见文件头）。每格含义：
#:   (标签, 目标文件, 被替换的原文, 替换成, 期望变红, 跑哪条判据)
#: 三个元素的写法表示"不注入"（第三格是布尔：期望是否变红）。
SCENARIOS = [
    ("（不注入：写对了就必须能过）", RUNNER, False),

    ("规范少一个编号小节标题", SPEC, "## 十四、", "## 十四.", True, RUNNER),
    ("规范少一个附录标题", SPEC, "## 附录 B · 一页速查卡", "## 附录乙 · 一页速查卡", True, RUNNER),
    ("项目地图导航行不再链规范（只剩一处链接）", INDEX,
     "| [**../DEVELOPMENT_SPEC.md**](../DEVELOPMENT_SPEC.md) | **开发规范 v1.0（⛔ 开工前必读）**：四种 ID",
     "| **../DEVELOPMENT_SPEC.md** | **开发规范 v1.0（⛔ 开工前必读）**：四种 ID", True, RUNNER),
    ("入口文件里的规范链接被指向不存在的路径", AGENTS,
     "](docs/DEVELOPMENT_SPEC.md)", "](docs/DEVELOPMENT_SPEC_GONE.md)", True, RUNNER),
    ("入口文件少了 GOV-xxxx 这个身份", AGENTS,
     "GOV-xxxx  开发治理", "XXX-xxxx  开发治理", True, RUNNER),
    ("声明页只说文件名、不再链规范", CLAIM,
     "](DEVELOPMENT_SPEC.md)", "](DEVELOPMENT_SPEC_没链.md)", True, RUNNER),
    ("登记簿 README 漏掉一个事项文件", CHANGES_README,
     "[GOV-0001.md](GOV-0001.md)", "GOV-0001.md", True, RUNNER),
    ("事项文件的内文 ID 与文件名不符", GOV1,
     "**ID**：`GOV-0001`", "**ID**：`GOV-0002`", True, RUNNER),
    ("模板少一个必填小节", CHANGES_TEMPLATE,
     "## ⑦ 测试", "## 测试", True, RUNNER),
    ("入口链接断掉 → 可达性判据也必须红（孤儿文档检测有牙）", AGENTS,
     "](docs/DEVELOPMENT_SPEC.md)", "](docs/DEVELOPMENT_SPEC_GONE.md)", True, REACH),
]


class Sandbox:
    """按字节记住原样，最后一次性还原（⛔ 不用 git checkout --）。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def replace(self, p: Path, old: str, new: str) -> None:
        if p not in self.saved:
            self.saved[p] = p.read_bytes()
        text = p.read_text(encoding="utf-8")
        assert text.count(old) == 1, p.name + ": 原文出现 " + str(text.count(old)) + " 次，无法唯一替换"
        p.write_bytes(text.replace(old, new).encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)
            if p.read_bytes() != raw:
                print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        self.saved.clear()


def run(script: Path) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    lock_reverse_verify()
    ok = 0
    failed: list[str] = []
    try:
        for i, case in enumerate(SCENARIOS, 1):
            if len(case) == 3:
                label, script, expect_red = case[0], case[1], case[2]
                target, old, new = None, None, None
            else:
                label, target, old, new, expect_red, script = case
            sb = Sandbox()
            try:
                if target is not None and old is not None and new is not None:
                    sb.replace(target, old, new)
                code, out = run(script)  # type: ignore[arg-type]
            finally:
                sb.restore()
            red = code != 0
            good = red if expect_red else (not red)
            print(("✅" if good else "❌") + " [" + str(i) + "/" + str(len(SCENARIOS)) + "] "
                  + ("应红" if expect_red else "应通过") + " · " + label
                  + " → 实际 exit=" + str(code))
            if good:
                ok += 1
            else:
                failed.append(label)
                print("     输出尾部：\n" + "\n".join(out.strip().splitlines()[-6:]))
    finally:
        unlock_reverse_verify()

    print("")
    if failed:
        print("❌ 反向验证 " + str(ok) + "/" + str(len(SCENARIOS)) + " —— 这些场景没有按预期反应：")
        for f in failed:
            print("   - " + f)
        print("")
        print("   ⚠️ 先分清是**判据漏了**还是**注入没生效**（锚点腐烂）：")
        print("      注入没生效 → 改锚点；判据漏了 → 改判据。⛔ 两件事的修法相反，别搞反。")
        return 1
    print("✅ 反向验证 " + str(ok) + "/" + str(len(SCENARIOS))
          + "：每一条破坏都让判据**真的红了**，而正常情况下它是绿的。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
