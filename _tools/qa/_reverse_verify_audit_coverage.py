"""反向验证「写业务数据必须留审计日志」这条红线**真的会红**（R14-1）。

## 为什么这条要反向验证
它的判据是"模块里有没有 `write_log(`"，有一类**看起来在查、其实没查**的失效方式：
- 正则不匹配实际写法（`write_log(` 换行、别名导入）；
- 豁免表被当成"万能口子"——顺手把一个新模块写进 REASONS 就绕过了判据；
- 清单空转（`api/v1/` 里一个模块都扫不到）。

所以三种破坏各注入一次：**把日志拿掉**、**把模块塞进豁免表**、**把扫描目录指错**。

用法：python _tools/qa/_reverse_verify_audit_coverage.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_audit_coverage.py"
CHECK_SRC = CHECK

CASES: list[tuple[str, str, object]] = [
    (
        "挂账单位的审计日志又被拿掉（真机抓到的那一条）",
        "backend/app/api/v1/arrears.py",
        lambda s: s.replace("    write_log(\n", "    _noop(\n"),
    ),
    (
        "运费模板的审计日志又被拿掉",
        "backend/app/api/v1/freight_templates.py",
        lambda s: s.replace("    write_log(\n", "    _noop(\n"),
    ),
    (
        "豁免表被当成万能口子（把一个**已经写了日志**的模块也塞进去）",
        "_tools/qa/_check_audit_coverage.py",
        lambda s: s.replace(
            "REASONS: dict[str, str] = {\n",
            "REASONS: dict[str, str] = {\n"
            '    "arrears.py": "注入：假装这里不需要日志",\n',
            1,
        ),
    ),
    (
        "豁免表里的模块其实还在写日志（假豁免＝看表的人以为它没留痕）",
        "_tools/qa/_check_audit_coverage.py",
        lambda s: s.replace(
            "REASONS: dict[str, str] = {\n",
            "REASONS: dict[str, str] = {\n"
            '    "stats.py": "注入：假装报表模块不写日志",\n',
            1,
        ),
    ),
    (
        "豁免理由写成占位符（把闸门糊过去）",
        "_tools/qa/_check_audit_coverage.py",
        lambda s: s.replace(
            '"files.py": "只解析上传的表格（不落库、不改任何业务数据）",',
            '"files.py": "无",',
            1,
        ),
    ),
    (
        "扫描目录指错（一个模块都扫不到 → 判据空转）",
        "_tools/qa/_check_audit_coverage.py",
        lambda s: s.replace('API = ROOT / "backend/app/api/v1"', 'API = ROOT / "backend/app/api/v1/nope"', 1),
    ),
]


def run_check(target: Path | None = None) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(target or CHECK)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    fails: list[str] = []
    code, out = run_check()
    if code != 0:
        print("❌ 前提不成立：源码完好时这条红线就没过")
        print(out[-1000:])
        return 1
    print("✅ 前提：源码完好时红线是绿的")

    # 快照/还原一律按**字节**：文本往返会把 CRLF 变成 LF，于是"还原了"其实变了字节
    # （本项目栽过"注入把守卫留在源码里"，所以收尾要逐字节核对，不是"看起来没痕迹"）。
    touched = sorted({rel for _l, rel, _m in CASES})
    originals = {rel: (ROOT / rel).read_bytes() for rel in touched}

    for label, rel, mutate in CASES:
        path = ROOT / rel
        original_bytes = originals[rel]
        mutated = mutate(original_bytes.decode("utf-8"))
        if mutated == original_bytes.decode("utf-8"):
            fails.append(f"{label}：注入没生效（锚点变了，请更新本脚本）")
            print(f"  [SKIP] {label}")
            continue
        tmp: Path | None = None
        try:
            if path == CHECK_SRC:
                # 改的是红线脚本自己：写一份副本跑，避免"检查自己在被改的状态下运行"
                tmp = path.with_suffix(".py.injected")
                tmp.write_bytes(mutated.encode("utf-8"))
                code, out = run_check(tmp)
            else:
                path.write_bytes(mutated.encode("utf-8"))
                code, out = run_check()
        finally:
            if tmp is not None and tmp.exists():
                tmp.unlink()
            path.write_bytes(original_bytes)
        if code != 0:
            print(f"  [OK] {label} → 红线报红")
        else:
            fails.append(f"{label}：注入之后红线**仍然全绿**（判据没牙）")
            print(f"  [MISS] {label} → 仍然全绿")

    # 还原检查：逐字节
    dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
    if dirty:
        fails.append("跑完没逐字节还原：" + "、".join(dirty))
        for rel in dirty:
            (ROOT / rel).write_bytes(originals[rel])
        print("⚠️  已强制还原：" + "、".join(dirty))
    else:
        print(f"✅ 还原检查：{len(touched)} 个被碰过的文件与运行前逐字节一致")

    print()
    if fails:
        print("❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"✅ {len(CASES)} 条注入都证明这条红线真的在检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
