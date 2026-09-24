#!/usr/bin/env python3
"""_pre_release.py —— 发布前的**一条命令**：先把退路备好，再谈上线。

报告 §3 的流程是：

    Pre-release → DB backup → Uploads backup → Git commit/tag → Deploy

而改造前的事实是：deploy 先发生，出了问题才"好像以前有个 mysqldump"。
本脚本把前三步压成一条命令，并且**把清单拉回本地**（_tools/backup/manifests/）——
生产机整个挂掉的时候，你至少还知道最后一份备份是什么、在哪、对不对。

用法：
    python _tools/backup/_pre_release.py --note "上线 0.2.5（订单拆分修复）"
    python _tools/backup/_pre_release.py --note "…" --tag v0.2.5     # 顺带打 git tag
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "_tools" / "ops"))
import _prodssh  # noqa: E402

MANIFEST_DIR = ROOT / "_tools" / "backup" / "manifests"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="发布前备份（库 + 上传文件 + 代码版本）")
    ap.add_argument("--note", required=True, help="这次发布是什么（会写进清单）")
    ap.add_argument("--tag", help="顺带打一个 git tag（如 v0.2.5）")
    ap.add_argument("--skip-uploads", action="store_true",
                    help="跳过上传文件（大；除非你确定这次不碰图片）")
    args = ap.parse_args(argv)

    dirty = [ln for ln in git("status", "--short").splitlines() if ln.strip()]
    commit = git("rev-parse", "HEAD")
    print("本地代码：" + commit[:12] + "（" + git("branch", "--show-current") + "）")
    if dirty:
        print("⚠️ 工作区有 " + str(len(dirty)) + " 个未提交改动 —— 备份记录的是**生产机上那份**代码的版本号；")
        print("   请确认这些改动是不是你打算发布的（未提交 = 清单里的 commit 与你以为的不一致）。")
        for ln in dirty[:10]:
            print("     " + ln)

    if args.tag:
        exists = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "refs/tags/" + args.tag],
                                cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if exists:
            print("⛔ tag " + args.tag + " 已存在（备份清单与代码版本必须一一对应，不覆盖）")
            return 3
        subprocess.run(["git", "tag", "-a", args.tag, "-m", args.note], cwd=ROOT, check=True)
        print("✅ 已打 tag：" + args.tag)

    kind = "pre_release"
    note = args.note.replace('"', "'")
    print("")
    print("开始生产机备份（kind=" + kind + "）…")
    script = "bash " + _prodssh.BACKUP_ROOT + "/bin/_backup.sh --kind " + kind + ' --note "' + note + '"'
    if args.skip_uploads:
        # pre_release 默认带上传文件；要跳过就退化成 daily + 在备注里写明 ——
        # 不许"悄悄少备一样还不说"（少的那一样往往正是唯一不可再生的）。
        script = ("bash " + _prodssh.BACKUP_ROOT + "/bin/_backup.sh --kind daily "
                  '--note "' + note + '（本次跳过上传文件）"')
    r = _prodssh.ssh_script(script, timeout=3600)
    out = r.stdout.decode("utf-8", "replace")
    print(out[-2000:])

    dest = ""
    for ln in out.splitlines():
        if ln.strip().startswith("{") and '"dir"' in ln:
            try:
                dest = json.loads(ln.strip())["dir"]
            except json.JSONDecodeError:
                pass
    if not dest:
        print("⛔ 没从输出里解析到备份目录 —— 备份可能没成功，**不要继续发布**")
        return 4

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    local = MANIFEST_DIR / (ts + "-" + kind + ".json")
    _prodssh.scp_from(dest + "/manifest.json", local)
    m = json.loads(local.read_text(encoding="utf-8"))
    print("✅ 清单已留档：" + local.relative_to(ROOT).as_posix())
    print("   库行数：" + json.dumps(m["db"]["rows"], ensure_ascii=False))
    print("   产物：" + "、".join(k + "=" + str(v["bytes"]) + "B" for k, v in m["artifacts"].items()))
    print("")
    print("回滚命令（万一）：")
    print("  ssh … 'bash " + _prodssh.BACKUP_ROOT + "/bin/_restore.sh --backup " + dest +
          " --target-db sorders --i-know'")
    print("  ⛔ 但恢复前**先**再备一份当前状态（_backup.sh --kind pre_release），否则覆盖掉的就再也回不来了。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
