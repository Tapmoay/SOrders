#!/usr/bin/env python3
"""_check_backup.py —— 备份/恢复/演练这套东西的**静态判据**（进 _check_all.py 自动跑）。

### 为什么这套脚本需要"自己的检查"
报告 §18 规则 5：**任何自动化工具都必须自己可验证**。
本项目在这件事上栽过不止一次，而且形状都一样 —— "写在文档里的规矩没人执行"。
备份这套东西尤其危险：它平时**没有任何反馈**（备份成功是静默的），
等到真要用它的时候才发现"少备了一样"或者"恢复脚本默认往生产库上写"。

所以这里钉的是**恢复现场才会暴露的**那几条：
  1. 恢复脚本**默认不许**碰生产库（要碰必须 --i-know）；
  2. 演练必须真起服务、真打接口，且**端口/Redis/工作目录三样都隔离**
     （不隔离的话，演练本身就会污染生产：推事件给真实客户端、压缩生产图片）；
  3. 演练签出来的 token 必须用**演练专用密钥**（沿用生产密钥 = 顺手造了一把真钥匙）；
  4. 备份必须当场校验（gzip -t / sha256 / 行数）且失败留 .FAILED 标记；
  5. 口令只走 MYSQL_PWD，任何脚本里都不许有内联口令；
  6. 生产主机/密钥只许出现在 _tools/ops/_prodssh.py 一处。

用法：
    python _tools/backup/_check_backup.py --check     # 非零退出＝有问题
    python _tools/backup/_check_backup.py             # 打印细节
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

#: 规则条数下限：判据自己也会腐烂（glob 写错、文件改名），低于这个数说明检查空转了。
MIN_RULES = 20


def read(name: str) -> str:
    p = HERE / name
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def find_bash() -> str | None:
    """本机/CI 上的 bash。Windows 开发机走 Git for Windows 的那个。"""
    found = shutil.which("bash")
    if found:
        return found
    for cand in (r"C:\Program Files\Git\bin\bash.exe",
                 r"C:\Program Files\Git\usr\bin\bash.exe"):
        if Path(cand).exists():
            return cand
    return None


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")           # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    check_mode = "--check" in sys.argv

    failures: list[str] = []
    passed: list[str] = []
    notes: list[str] = []

    def want(cond: bool, ok: str, bad: str) -> None:
        (passed if cond else failures).append(ok if cond else bad)

    # ---------------------------------------------------------- 1. 文件齐不齐
    for f in ("_backup.sh", "_restore.sh", "_drill.sh", "_install.py",
              "_pre_release.py", "_drill_local.py", "README.md"):
        want((HERE / f).exists(), "存在 " + f, "⛔ 缺文件：" + f)
    prodssh = ROOT / "_tools" / "ops" / "_prodssh.py"
    want(prodssh.exists(), "存在 _tools/ops/_prodssh.py", "⛔ 缺 _tools/ops/_prodssh.py")

    backup, restore, drill = read("_backup.sh"), read("_restore.sh"), read("_drill.sh")

    # ---------------------------------------------------------- 2. bash -n（真语法检查）
    bash = find_bash()
    if bash:
        for name, src in (("_backup.sh", backup), ("_restore.sh", restore), ("_drill.sh", drill)):
            if not src:
                continue
            r = subprocess.run([bash, "-n", str(HERE / name)], capture_output=True)
            want(r.returncode == 0, "bash -n 通过 " + name,
                 "⛔ bash -n 失败 " + name + "：" + r.stderr.decode("utf-8", "replace")[:200])
    else:
        notes.append("⚠️ 本机没有 bash —— **语法检查这一组没有执行**（其余结构性判据照跑）")

    # ---------------------------------------------------------- 3. 结构性判据
    for name, src in (("_backup.sh", backup), ("_restore.sh", restore), ("_drill.sh", drill)):
        if not src:
            continue
        want(src.startswith("#!/usr/bin/env bash"), name + " 有 shebang", name + " 缺 shebang")
        want("set -euo pipefail" in src, name + " 用 set -euo pipefail",
             name + " 没有 set -euo pipefail（失败会被吞掉）")

    # 3a. 备份：当场校验 + 失败留痕 + 口令走环境变量
    want("trap" in backup and ".FAILED" in backup,
         "_backup.sh 失败会留 .FAILED 标记", "⛔ _backup.sh 没有失败标记（半个备份会被当成好的）")
    want("gzip -t" in backup, "_backup.sh 当场 gzip 校验", "⛔ _backup.sh 不校验产物")
    want("manifest.json" in backup and "SHA256SUMS" in backup,
         "_backup.sh 写清单与校验和", "⛔ _backup.sh 不写 manifest/SHA256SUMS")
    want("MYSQL_PWD" in backup, "_backup.sh 口令走 MYSQL_PWD",
         "⛔ _backup.sh 不用 MYSQL_PWD（口令会进 ps）")
    want('case "$BACKUP_ROOT" in' in backup and "/opt/*)" in backup,
         "_backup.sh 保留期清理限定在 /opt 下", "⛔ _backup.sh 的删除没有路径护栏")
    want("|| true" in backup,
         "_backup.sh 的 find 容忍目录不存在（否则 set -e 会把好备份判成失败）",
         "⛔ _backup.sh 的 dirs=$(find …) 在目录不存在时会让整次备份判失败")

    # 3b. 恢复：默认不碰生产库
    want("--i-know" in restore, "_restore.sh 有 --i-know 门", "⛔ 恢复生产库没有显式确认门")
    want(".FAILED" in restore, "_restore.sh 拒绝带 .FAILED 的备份",
         "⛔ _restore.sh 不检查 .FAILED")
    want("sha256sum -c" in restore, "_restore.sh 校验 SHA256SUMS", "⛔ _restore.sh 不校验产物")
    want("sorders_drill_*" in restore, "_restore.sh 的 DROP 只认演练库",
         "⛔ _restore.sh 的 DROP 没有库名护栏")

    # 3c. 演练：真启动 + 三样隔离 + 专用密钥
    want("_restore.sh" in drill, "_drill.sh 走 _restore.sh 恢复", "⛔ 演练没走恢复脚本")
    want("app.models.enums" in drill,
         "_drill.sh 的判据取自生产代码的枚举（不是手写）",
         "⛔ 演练里的枚举是手写的 —— 一定会漂移")
    want("trap cleanup EXIT" in drill, "_drill.sh 有收尾 trap", "⛔ 演练失败会留下垃圾")
    want(re.search(r"PORT=80\d\d", drill) is not None and "PORT=8000" not in drill,
         "演练端口与生产 8000 隔离", "⛔ 演练用了生产端口")
    want(re.search(r"REDIS_PORT=6\d{3}", drill) is not None and "REDIS_PORT=6379" not in drill,
         "演练起独立 Redis（pub/sub 不串到生产）", "⛔ 演练 Redis 没有隔离")
    want("JWT_SECRET_KEY=$DRILL_SECRET" in drill,
         "演练用独立 JWT 密钥", "⛔ 演练沿用生产 JWT 密钥（签出来的令牌对生产有效）")
    want("RUN_DIR" in drill and "cd \"$RUN_DIR\"" in drill,
         "演练有独立工作目录（data_retention 的相对路径不会碰生产图片）",
         "⛔ 演练没换工作目录")
    want(drill.count("--- ") >= 3, "演练有分阶段输出", "⛔ 演练的阶段标记不见了")
    for phase in ("--- ②", "--- ③", "--- ④"):
        want(phase in drill, "演练包含阶段 " + phase, "⛔ 演练缺阶段 " + phase)
    want('DRILL=' in drill, "演练输出机器可判的结论行", "⛔ 演练没有 DRILL= 结论行")
    # ⚠️ 实测踩到过的坑，留一条回归判据：find 用了 -exec 就不再默认打印，
    #    `find … ! -exec test … \;` 会**一个结果都不输出** → "明明有备份却说找不到"。
    for name, src in (("_backup.sh", backup), ("_restore.sh", restore), ("_drill.sh", drill)):
        want("-exec" not in src or "-print" in src,
             name + " 的 find -exec 没有漏掉 -print",
             "⛔ " + name + " 里用了 find -exec 却没 -print（find 会静默不输出）")

    # ---------------------------------------------------------- 4. 口令/常量单点
    secret_pat = re.compile(r"mysql\s+[^\n]*-p[^ \n$]")
    for f in HERE.glob("*.py"):
        src = f.read_text(encoding="utf-8", errors="replace")
        want(secret_pat.search(src) is None, f.name + " 无内联口令",
             "⛔ " + f.name + " 里出现命令行内联口令")
    # ⚠️ 跳过检查脚本自己：它**必须**写出这两个字面量才搜得到别人有没有写（判据自身的文本不算违规）。
    for f in [p for p in list(HERE.glob("*.sh")) + list(HERE.glob("*.py"))
              if p.name != "_check_backup.py"]:
        src = f.read_text(encoding="utf-8", errors="replace")
        want("8.145.40.22" not in src and "id_ed25519_sorders" not in src,
             f.name + " 不含生产主机/密钥（走 _prodssh）",
             "⛔ " + f.name + " 硬编码了生产主机或密钥路径 —— 应改为 import _prodssh")

    # 3d. 演练库授权：应用账号只有 sorders.* 时演练必然 1044（第一次真跑就撞上）
    inst = read("_install.py")
    want("DRILL_GRANT_SQL" in inst and "DRILL_SELFTEST" in inst
         and "GRANT ALL PRIVILEGES" in inst and "sorders_drill_" in inst,
         "_install.py 给演练库授权并当场自检",
         "⛔ _install.py 没有演练库授权/自检（演练会在建库时 Access denied）")

    # ---------------------------------------------------------- 5. 数量判据（防检查空转）
    want((HERE / "_check_backup.py").exists(), "检查脚本存在", "⛔ 检查脚本不存在")
    total = len(passed) + len(failures)
    want(total >= MIN_RULES, "判据条数 " + str(total) + " ≥ " + str(MIN_RULES),
         "⛔ 只跑了 " + str(total) + " 条判据（< " + str(MIN_RULES) + "）—— 检查可能空转了")

    print("备份体系静态判据：" + str(len(passed)) + " 通过 / " + str(len(failures)) + " 失败")
    for n in notes:
        print("  " + n)
    if check_mode and failures:
        for f in failures:
            print("  " + f)
        return 1
    if not check_mode:
        for f in passed:
            print("  ✅ " + f)
    if failures:
        for f in failures:
            print("  " + f)
        return 1
    print("  ✅ 全部通过（含恢复演练的隔离与门禁）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
