#!/usr/bin/env python3
"""反向验证 `_tools/qa/_check_ci_workflows.py` 真的抓得住那几类错误。

## 为什么 CI 工作流的判据也需要反向验证
报告 §5 的判据是"CI 有没有真的接管检查体系"，而 **workflow 是一份不会在自己身上跑的清单**——
它写错了只会在 GitHub 上红，本机 `_check_all.py` 照样全绿。所以这条红线的价值全在"它真的会红"上；
一条永远绿的 workflow 检查比没有更糟（它会让人以为 CI 已经接管了）。

## 破坏清单（每一种都必须让红线当场红，且报出**对应**那条判据）

⚠️ 下面这张表只列到 ⑧（后来的用例直接写在 `CASES` 里，没再往表里补），
⑨~⑮ 见 `CASES` 与其上方的逐条注释。其中 ⑮ 是 2026-09-25 第 56 轮**实测踩到**的那一次：
「模拟器没起来」那一支当时写的是 `exit 0`，于是 job 报 success、日志却在说"这次没有跑"。
| # | 注入 | 现实里谁会这么干 |
| --- | --- | --- |
| ① | 快闸里塞一个 `cd frontend` 的作业 | 前端归档后又把 H5 的构建步骤加回来（**它就是 2026-09-25 被人工删掉的那个作业的形状**） |
| ② | 某个 step 加 `working-directory: frontend` | 同一个坑的另一种写法（不写 `cd`，写 step 级工作目录） |
| ③ | `pull_request.branches` 只留 `main` | 「挂 main 就行了」→ CI 一次都不跑真正的开发分支 |
| ④ | gradle 任务名的 flavor 拼错 | 抄旧文档里的任务名 |
| ⑤ | `run:` 里引用一个不存在的检查脚本 | 检查改名/搬走之后 CI 没跟着改 |
| ⑥ | PR 闸里删掉 `_check_all.py` | 「本机跑跑就行」→ 检查体系又只剩人在本机跑 |
| ⑦ | 并行 pytest 丢了 `--dist loadfile` | 有人觉得"默认分发也一样"（实测默认分发 2 failed / 1013 passed） |
| ⑧ | 跑检查的 job 删掉 `pip install` | 加新 job 时照抄了最像的那个 —— 而它恰好是全仓唯一不装依赖的那个（2026-09-25 CI 实测：8 个检查直接 `ModuleNotFoundError`，本机却全绿） |

⚠️ 与仓库里其它 `_reverse_verify_*.py` 同一套纪律：按**字节**备份/还原、跑完逐文件核对、
⛔ 全程不碰 `git checkout --`。

用法：python _tools/qa/_reverse_verify_ci_workflows.py
      python _tools/qa/_reverse_verify_ci_workflows.py --list
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_ci_workflows.py"
GATE = ".github/workflows/gate.yml"
PARALLEL = ".github/workflows/test-parallel.yml"

CASES: list[tuple[str, str, str, str, str]] = [
    (
        "① 快闸里又冒出一个 `cd frontend` 的作业（H5 归档后加回来）",
        GATE,
        "      - name: 语法（后端全部 .py 能编译）\n"
        "        run: python -m compileall -q backend/app backend/scripts\n",
        "      - name: 打前端 H5 包\n"
        "        run: |\n"
        "          cd frontend\n"
        "          npm ci\n"
        "      - name: 语法（后端全部 .py 能编译）\n"
        "        run: python -m compileall -q backend/app backend/scripts\n",
        "指到不存在的目录",
    ),
    (
        "② 不写 cd，改在 step 上加 `working-directory: frontend`（同一个坑的另一种写法）",
        GATE,
        "      - name: 核心区冻结（动核心必须先在 AI_WORK_CLAIM 里声明）\n"
        "        run: python _tools/qa/_check_core_freeze.py --check\n",
        "      - name: 核心区冻结（动核心必须先在 AI_WORK_CLAIM 里声明）\n"
        "        run: python _tools/qa/_check_core_freeze.py --check\n"
        "        working-directory: frontend\n",
        "指到不存在的目录",
    ),
    (
        "③ PR 闸只挂 main（代码落在 p/new 上，CI 从此一次都不跑）",
        GATE,
        "  pull_request:\n    branches: [main, develop, p, new]\n",
        "  pull_request:\n    branches: [main]\n",
        "没挂",
    ),
    (
        "④ gradle 任务名里的 flavor 拼错（夜闸会红，而没人看夜闸）",
        GATE,
        "        run: gradle -p android :app:testPhoneDebugUnitTest --no-daemon --stacktrace",
        "        run: gradle -p android :app:testZzzDebugUnitTest --no-daemon --stacktrace",
        "在 build.gradle.kts 里没有",
    ),
    (
        "⑤ run: 里引用一个不存在的检查脚本（脚本改名/搬走，CI 没跟着改）",
        GATE,
        "      - name: 密钥自检（仓库是公开的）\n"
        "        run: python _tools/qa/_check_secrets.py --check\n",
        "      - name: 密钥自检（仓库是公开的）\n"
        "        run: python _tools/qa/_check_secrets.py --check\n\n"
        "      - name: 一条不存在的检查\n"
        "        run: python _tools/qa/_check_this_file_does_not_exist.py --check\n",
        "有路径在仓库里找不到",
    ),
    (
        "⑥ PR 闸里删掉 `_check_all.py`（「本机跑跑就行」→ 检查体系又只剩人在本机跑）",
        GATE,
        "      - name: 全部静态检查\n        run: python _tools/qa/_check_all.py\n",
        "      - name: 全部静态检查\n        run: python _tools/qa/_check_secrets.py --check\n",
        "PR 闸里没有 _check_all.py",
    ),
    (
        "⑦ 并行 pytest 丢了 --dist loadfile（默认分发会把一个文件的用例拆到不同 worker）",
        # ⚠️ 2026-09-25：锚点从 gate.yml 的**全量用例**挪到这里 —— 那一条已经改成**顺序跑**
        #    （去掉了 -n auto：并行分发下整套用例会偶发红，见 test-parallel.yml 顶部那段），
        #    而这条判据管的是「**还并行**的那几处必须带 loadfile」。
        PARALLEL,
        '          pytest -n auto --dist loadfile -m "fast or smoke or unit" -v --tb=short',
        '          pytest -n auto -m "fast or smoke or unit" -v --tb=short',
        "没带 --dist loadfile",
    ),
    # ---- ⑩ 安卓端到端必须真的被接管，且三种结局分得开（2026-09-25 补）----
    (
        "⑩ 判据只扫 run:（漏掉 with.script —— 端到端脚本恰好在 emulator-runner 的 script 里）",
        "_tools/qa/_check_ci_workflows.py",
        '        if isinstance(w, dict) and isinstance(w.get("script"), str):\n            parts.append(w["script"])',
        '        pass  # 注入：只扫 run:',
        "没有任何 job 执行它",
    ),
    (
        "⑪ 「起不来模拟器」那条注解被撤掉（跳过变成静默绿）",
        GATE,
        '            echo "::warning title=安卓端到端这次没跑::这台 runner 上没能起模拟器',
        '            echo "安卓端到端这次没跑：这台 runner 上没能起模拟器',
        "没把跳过做成可见的",
    ),
    (
        "⑫ 带理由跳过那条注解被撤掉",
        GATE,
        '            echo "::warning title=安卓端到端带理由跳过::$(grep -m1',
        '            echo "带理由跳过：$(grep -m1',
        "没把跳过做成可见的",
    ),
    (
        "⑬ SKIP: 判定没了（脚本给的理由不再被读出来）",
        GATE,
        "grep -m1 '^SKIP:'",
        "grep -m1 '^NOPE:'",
        "没把跳过做成可见的",
    ),
    (
        "⑭ 跑挂不再报红（那它接管了什么）",
        GATE,
        '          echo "::error title=安卓端到端没跑通::rc=$rc',
        '          echo "安卓端到端没跑通 rc=$rc',
        "没把失败报成红",
    ),
    (
        "⑧ 跑检查的 job 删掉 `pip install`（裸 Python 上检查会成片 ModuleNotFoundError，而本机看不出来）",
        # ⚠️ 锚点必须带上后面那句注释才唯一 —— gate.yml 里有 4 个 job 都写了同样的「装依赖」三步，
        #    只锚那三步的话 `apply` 会因为"出现 4 次"直接 SKIP（那种 SKIP 会被记成 MISS）。
        GATE,
        "      - name: 装依赖\n"
        "        run: |\n"
        "          cd backend\n"
        "          pip install -r requirements-all.txt\n"
        "      # ⚠️ 这里**故意**不写死条数：条数由脚本自己数（写死的话每加一个检查都要改 CI，\n",
        "      # ⚠️ 这里**故意**不写死条数：条数由脚本自己数（写死的话每加一个检查都要改 CI，\n",
        "却没装依赖",
    ),
    (
        "⑮ 「模拟器没起来」那一支改回 exit 0（注解还在、job 却是绿的 —— 实测踩到的就是这一次）",
        # ⚠️ 锚点必须**连着上一行的 echo**：单独的 `exit 1` 在 gate.yml 里出现多次，
        #    只锚它的话 apply 会因为"不止一次"直接 SKIP（那种 SKIP 会被记成 MISS）。
        GATE,
        '            echo "::error title=安卓端到端没跑通::连 /tmp/e2e.rc 都没有'
        ' —— 模拟器压根没起来（先看上面有没有 ProbeKVM / boot timeout）。⛔ 「没跑」不等于「通过」：省掉这一行，这个作业就只是一块永远绿的装饰牌子。"'
        + chr(10) + "            exit 1",
        '            echo "::error title=安卓端到端没跑通::连 /tmp/e2e.rc 都没有'
        ' —— 模拟器压根没起来（先看上面有没有 ProbeKVM / boot timeout）。⛔ 「没跑」不等于「通过」：省掉这一行，这个作业就只是一块永远绿的装饰牌子。"'
        + chr(10) + "            exit 0",
        "仍然 exit 0",
    ),
    (
        "⑯ 模拟器 script 又被拆成多行（那个 action 逐行 `sh -c`：set/变量/续行全静默失效）",
        # ⚠️ 锚点取 `script: >` 那一行 + 紧随其后的正文行：只锚 `script: >` 会太短，
        #    而整段正文太长且含 `>`（YAML 折叠标量），分段锚更稳。
        GATE,
        # ⚠️ 锚点里必须**带上哨兵**：2026-09-25 第 58 轮给脚本开头加了 `echo 9 > /tmp/e2e.rc;`，
        #    不带它这条锚点就 0 次命中（RV 会报 SKIP，而 SKIP 记成 MISS）—— 实测踩到过一次。
        #    ⛔ 替换文本也要**保留哨兵**（只是挪到自己一行），否则第 16、17 条会一起红，
        #    那就证明不了"红的是 16 条"。
        # ⚠️ 锚点要**短且不受行内顺序影响**：第 58 轮里这行被改过三次（压成一行 → 加哨兵 → 调整
        #    「装包/体检」顺序），每次都把长锚点打成 0 次命中（RV 报 SKIP，而 SKIP 记成 MISS）。
        #    现在只锚 `script: >` + 缩进，把"变成两行"这件事本身做出来就够了。
        "          script: >\n            ",
        "          script: |\n            echo 9 > /tmp/e2e.rc\n            ",
        "的模拟器 script 是多行的",
    ),
    (
        "⑰ 脚本开头那个哨兵被拿掉（脚本中途挂掉时会被归因成「模拟器没起来」）",
        GATE,
        # ⚠️ 同理：只锚哨兵本身（它在 gate.yml 里只出现一次），不锚它后面跟了什么。
        "echo 9 > /tmp/e2e.rc; ",
        "",
        "没在脚本开头写哨兵",
    ),
    (
        "⑱ 体检排到了装包前面（`--check-env` 查的就是「App 装没装」→ 恒 SKIP、永远跑不到流程）",
        GATE,
        "; adb install -r android/app/build/outputs/apk/phone/debug/*.apk > /tmp/e2e.log 2>&1;",
        "; python _tools/e2e/_flow_login_nav_order.py --check-env --serial 5554 > /dev/null 2>&1; adb install -r android/app/build/outputs/apk/phone/debug/*.apk > /tmp/e2e.log 2>&1;",
        "的顺序反了",
    ),
    (
        "⑲ 端到端的后端绑回 127.0.0.1（模拟器里的 App 连不上，而体检那一步仍然是绿的）",
        # ⚠️ 锚点带 `e2e-api.log`：read-roles 那个作业也起了 uvicorn（写 probe-api.log），
        #    不带这个后缀就会"出现两次"直接 SKIP。
        GATE,
        "          nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/e2e-api.log 2>&1 &",
        "          nohup python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/e2e-api.log 2>&1 &",
        "没绑 0.0.0.0",
    ),
    (
        "⑳ 预授运行时权限被拿掉（全新安装会弹系统权限窗挡住流程，本地复现不出来）",
        GATE,
        "adb shell pm grant com.tapmoay.sorders android.permission.ACCESS_FINE_LOCATION >> /tmp/e2e.log 2>&1; adb shell pm grant com.tapmoay.sorders android.permission.ACCESS_COARSE_LOCATION >> /tmp/e2e.log 2>&1; adb shell pm grant com.tapmoay.sorders android.permission.POST_NOTIFICATIONS >> /tmp/e2e.log 2>&1; adb shell pm grant com.tapmoay.sorders android.permission.READ_MEDIA_IMAGES >> /tmp/e2e.log 2>&1; ",
        "",
        "没有预授运行时权限",
    ),
    (
        "㉑ 业务数据没播（只有账号 → 选品页是空的 → 下单那一段卡住，而前两段全绿）",
        GATE,
        "          python -m scripts.seed_ci_e2e --base http://127.0.0.1:8000\n",
        "",
        "只造了账号、没造商品",
    ),
]

CRLF = chr(13) + chr(10)


class Sandbox:
    """按**字节**记账的注入沙箱：每次注入前先还原上一轮，跑完再逐字节核对。"""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}

    def apply(self, rel: str, old: str, new: str) -> None:
        p = ROOT / rel
        if not p.exists():
            raise ValueError("找不到 " + rel)
        self.saved.setdefault(p, p.read_bytes())
        raw = p.read_bytes()
        crlf = CRLF.encode("utf-8") in raw
        text = raw.decode("utf-8")
        if crlf:
            text = text.replace(CRLF, chr(10))
        if text.count(old) != 1:
            raise ValueError(rel + " 里锚点出现 " + str(text.count(old)) + " 次（要恰好一次）")
        text = text.replace(old, new, 1)
        p.write_bytes((text.replace(chr(10), CRLF) if crlf else text).encode("utf-8"))

    def restore(self) -> None:
        for p, raw in self.saved.items():
            p.write_bytes(raw)

    def dirty(self) -> list[str]:
        return [str(p.relative_to(ROOT)) for p, raw in self.saved.items() if p.read_bytes() != raw]


def run_check() -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(CHECK), "--check"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(ROOT))
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for i, (name, rel, _o, _n, want) in enumerate(CASES, 1):
            print(f"{i}. {name}\n      {rel}   ← 期望被「{want}」抓到")
        return 0

    bad = 0
    sb = Sandbox()
    lock_reverse_verify()
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：源码完好时这条红线就没过")
            print(out[-1500:])
            return 1
        last = [ln for ln in out.splitlines() if ln.strip()][-1]
        print("✅ 前提：源码完好时红线是绿的 —— " + last.strip())
        for label, rel, old, new, want in CASES:
            sb.restore()
            try:
                sb.apply(rel, old, new)
                code, out = run_check()
            except ValueError as exc:
                print("  [SKIP] " + label + " —— " + str(exc))
                bad += 1
                continue
            finally:
                sb.restore()
            # ⛔ 必须命中**那一条**判据（这条红线打印的是 `  BAD ⛔ <说明>`）
            hit = code != 0 and ("BAD " in out) and (want in out)
            if hit:
                print("  [OK] " + label + " → 红线报红并命中「" + want + "」")
            else:
                bad += 1
                why = "红线居然还是绿的" if code == 0 else "退出了，但没报出「" + want + "」"
                print("  [MISS] " + label + " → " + why)
                for ln in [x.strip() for x in out.splitlines() if x.strip().startswith("BAD")][:5]:
                    print("       红线实际报的：" + ln)
        sb.restore()
        code, out = run_check()
        ok = code == 0
        print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
        bad += 0 if ok else 1
    finally:
        sb.restore()
        unlock_reverse_verify()

    dirty = sb.dirty()
    if dirty:
        bad += 1
        print("⛔ 跑完没逐字节还原：" + "、".join(dirty))
    total = len(CASES) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立")
        return 1
    print(f"✅ {total}/{total} 全部成立：CI 工作流的每一类错误都会被对应的判据抓到")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
