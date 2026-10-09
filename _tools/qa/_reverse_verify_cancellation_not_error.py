#!/usr/bin/env python3
"""反向验证 _tools/qa/_check_cancellation_not_error.py 真的会红（BUG-0026 / 台账 TA-04）。

## 为什么是这一份
这一单修的是一个**时序**：被取消的那一趟取数不许写页面级 error，而且「谁能让页面动」只能由
当前那一趟说了算。时序型修法最典型的失效方式就是「看名字在不在」——
取消分支写是写了、可它排在通用 catch 之后；世代号写是写了、可它在挂起点之后才取；
success / catch / finally 三处只改了两处。这些都必须让判据当场红，而且红的必须是**那一条**判据。

## 13 种破坏（每一种都必须让判据当场红，且报出对应那条标签）

| # | 注入 | 现实里谁会这么改 |
| --- | --- | --- |
| ① | 取消分支整段被摘掉（回到病灶） | 「catch 一个 Exception 就够了」 |
| ② | 取消分支不重抛、改成写页面级 error | 「反正都是异常，报一下省事」 |
| ③ | 取消分支挪到通用 catch 之后 | 顺序看着无所谓，其实等于没加 |
| ④ | import 被删（取消分支只剩裸名字） | 「编译器能过就行」 |
| ⑤ | 世代号字段被删（退回按 Job 同一性判） | 「loadJob 不就是当前那一趟吗」 |
| ⑥ | 取号不再钉在挂起点之前 | 「号在 launch 里取更整齐」 |
| ⑦ | 成功路径的世代守卫被删 | 「回来晚一点而已，数据还是好数据」 |
| ⑧ | 通用 catch 里的世代守卫被删 | 同上，只是失败那一路 |
| ⑨ | finally 的世代判断被删（无条件收加载态） | 「loading 总得有人关掉」 |
| ⑩ | loadJob?.cancel() 被删 | 「取消就是这一单的罪魁，删掉它」 |
| ⑪ | 通用 catch 不再用 toApiException | 「把原始异常串打出来好排查」 |
| ⑫ | fun load() 被收成 private | 「不许外部乱调」 |
| ⑬ | 变更单不再点名同类点位 | 「这单只改司机端，别的不用提」 |

⚠️ 与仓库里其它 _reverse_verify_*.py 同一套纪律：按字节备份 / 还原、跑完逐文件核对哈希、
全程不碰 git checkout --（那会在真有改动时抹掉工作）。注入只落在**本单自己的两个文件**上
（DriverOrdersViewModel.kt 与 docs/changes/BUG-0026.md），别的会话正在改的文件一律不碰
（尤其 DriverOrdersScreen.kt、docs/TEST_BUG_LEDGER.md、docs/changes/README.md：
它们的工作树里有别人的在飞改动）。

用法：python _tools/qa/_reverse_verify_cancellation_not_error.py
      python _tools/qa/_reverse_verify_cancellation_not_error.py --list
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import lock_reverse_verify, unlock_reverse_verify  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_cancellation_not_error.py"

VM = "android/app/src/main/java/com/tapmoay/sorders/ui/driver/DriverOrdersViewModel.kt"
DOC = "docs/changes/BUG-0026.md"

CANCEL_BLOCK = (
    "            } catch (e: CancellationException) {\n"
    "                // **取消不是失败**（BUG-0026）：这一趟是被新一次取数 / 实时推送打断的。\n"
    "                // `CancellationException` 是 `Exception` 的子类 —— 不先接住并原样抛出去的话，\n"
    "                // 下面那个通用 catch 会把 `StandaloneCoroutine was cancelled` 当成业务失败\n"
    "                // 写进页面级 [error]，渲染门（`DriverOrdersScreen.kt` 的 `vm.error != null`）\n"
    "                // 当场把整个列表顶掉（真机证据：_tmp/test_round3/evidence_ta04_before.txt）。\n"
    "                throw e\n"
)

GENERIC_BLOCK = (
    "            } catch (e: Exception) {\n"
    "                // 只有**当前**这一趟才写错误页：过期那趟失败了，也不许把新一趟已经拿到的结果\n"
    "                // 盖成一张错误页。\n"
    "                if (mySeq != loadSeq) return@launch\n"
    "                error = toApiException(e).message\n"
)

#: (说明, 相对路径, 被替换的原文, 换成什么, 必须报红的那条判据标签, 命中次数)
CASES: list[tuple[str, str, str, str, str, int | str]] = [
    (
        "① 取消分支整段被摘掉（回到病灶：取消被通用 catch 吃掉）",
        VM, CANCEL_BLOCK, "",
        "load() 里有取消分支 catch (… : CancellationException)", 1,
    ),
    (
        "② 取消分支不重抛、改成写页面级 error",
        VM,
        "                throw e\n            } catch (e: Exception) {",
        "                error = toApiException(e).message\n            } catch (e: Exception) {",
        "取消分支把取消**重抛**出去（throw）", 1,
    ),
    (
        "③ 取消分支挪到通用 catch 之后（顺序反了）",
        VM, CANCEL_BLOCK + GENERIC_BLOCK, GENERIC_BLOCK + CANCEL_BLOCK,
        "取消分支排在通用 catch 之前", 1,
    ),
    (
        "④ import 被删（取消分支只剩裸名字）",
        VM,
        "import kotlinx.coroutines.CancellationException\n",
        "",
        "CancellationException 是按 import（或全限定名）用的", 1,
    ),
    (
        "⑤ 世代号字段被删（退回按 Job 同一性判）",
        VM,
        "    private var loadSeq = 0\n",
        "",
        "有取数世代号字段（private var loadSeq = 0）", 1,
    ),
    (
        "⑥ 取号不再钉在挂起点之前（这一行被删/被挪进 launch 体内）",
        VM,
        "        val mySeq = ++loadSeq\n        // ⚠️ **在挂起点之前**把",
        "        // ⚠️ **在挂起点之前**把",
        "世代号在**挂起点之前**取（++loadSeq 在 viewModelScope.launch 之前）", 1,
    ),
    (
        "⑦ 成功路径的世代守卫被删",
        VM,
        "                if (mySeq != loadSeq) return@launch\n                // ⚠️ 这两句**必须相邻**",
        "                // ⚠️ 这两句**必须相邻**",
        "成功路径：写 orders 之前先按世代号让开", 1,
    ),
    (
        "⑧ 通用 catch 里的世代守卫被删",
        VM,
        "                if (mySeq != loadSeq) return@launch\n                error = toApiException(e).message",
        "                error = toApiException(e).message",
        "失败路径：写 error 之前先按世代号让开", 1,
    ),
    (
        "⑨ finally 的世代判断被删（无条件收加载态）",
        VM,
        "                if (mySeq == loadSeq) {\n                    loading = false\n                    refreshing = false\n                }\n",
        "                loading = false\n                refreshing = false\n",
        "finally（加载态）也按世代号让开", 1,
    ),
    (
        "⑩ loadJob?.cancel() 被删（「取消就是罪魁」）",
        VM,
        "        loadJob?.cancel()\n        // 世代号必须在**挂起点之前**取",
        "        // 世代号必须在**挂起点之前**取",
        "旧取数仍然会被打断（loadJob?.cancel() 还在）", 1,
    ),
    (
        "⑪ 通用 catch 不再用 toApiException（原始异常串上屏）",
        VM,
        "                error = toApiException(e).message\n",
        "                error = e.message.orEmpty()\n",
        "通用 catch 仍然把失败写进页面级 error", 1,
    ),
    (
        "⑫ fun load() 被收成 private",
        VM,
        "    fun load() {\n        loadJob?.cancel()",
        "    private fun load() {\n        loadJob?.cancel()",
        "load() 仍然是 public（错误页的「重试」要能调它）", 1,
    ),
    (
        "⑬ 变更单不再点名同类点位",
        DOC,
        "ReturnRequestsViewModel.kt",
        "（不点名）",
        "变更单点名了 4 个同类点位（说明本单只动司机端）", "all",
    ),
]


class Sandbox:
    "按字节记账的注入台：每条注入都从最初那份字节重来，末尾逐字节还原并读回校验。"

    def __init__(self) -> None:
        self.saved: dict[Path, bytes] = {}
        self.digests: dict[Path, str] = {}

    def _snapshot(self, path: Path) -> None:
        if path not in self.saved:
            raw = path.read_bytes()
            self.saved[path] = raw
            self.digests[path] = hashlib.sha256(raw).hexdigest()

    def apply(self, rel: str, old: str, new: str, count: int | str = 1) -> None:
        path = ROOT / rel
        if not path.is_file():
            raise ValueError("文件不在：" + rel)
        self._snapshot(path)
        raw = self.saved[path]
        crlf = b"\r\n" in raw  # 本仓库混着 CRLF/LF：按原样还原，不猜
        text = raw.decode("utf-8").replace("\r\n", "\n")
        found = text.count(old)
        if count == "all":
            if found < 1:
                raise ValueError("锚点一处都没命中：" + rel)
            text = text.replace(old, new)
        else:
            if found != 1:
                raise ValueError(f"锚点命中 {found} 次（要求 1 次）：" + rel)
            text = text.replace(old, new, 1)
        out = text.replace("\n", "\r\n") if crlf else text
        path.write_bytes(out.encode("utf-8"))

    def restore(self) -> None:
        for path, raw in self.saved.items():
            path.write_bytes(raw)

    def verify(self) -> list[str]:
        bad: list[str] = []
        for path, digest in self.digests.items():
            now = hashlib.sha256(path.read_bytes()).hexdigest()
            if now != digest:
                bad.append(path.relative_to(ROOT).as_posix())
        return bad


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(ROOT),
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="只列注入表，不改任何文件")
    args = ap.parse_args()
    if args.list:
        for i, case in enumerate(CASES, 1):
            print(f"{i:>2}. {case[0]}")
        return 0

    lock_reverse_verify()
    sb = Sandbox()
    total = bad = 0
    try:
        code, out = run_check()
        if code != 0:
            print("❌ 前提不成立：判据本来就是红的，先把它修绿再做反验。")
            print("\n".join(out.splitlines()[-12:]))
            return 1
        green = [ln for ln in out.splitlines() if ln.startswith("✅")]
        print("前提：判据当前是绿的 —— " + (green[-1] if green else "（没有读到汇总行）"))
        print("")
        for case in CASES:
            why, rel, old, new, want, count = case
            total += 1
            sb.restore()
            try:
                sb.apply(rel, old, new, count)
            except ValueError as ex:
                bad += 1
                print(f"  ❌ 注入失败：{why} —— {ex}")
                continue
            code, out = run_check()
            if code != 0 and ("[!!]   " + want) in out:
                print(f"  ✅ 红了：{why}")
            else:
                bad += 1
                flagged = [ln.strip() for ln in out.splitlines() if ln.startswith("  [!!]")]
                print(f"  ❌ 没红 / 红错了判据：{why}")
                print("     判据实际报的：" + ("；".join(flagged[:4]) if flagged else "（一条都没报）"))
    finally:
        sb.restore()
        unlock_reverse_verify()

    left = sb.verify()
    print("")
    if left:
        bad += 1
        print("❌ 没有逐字节还原：" + "、".join(left))
    print("=" * 60)
    if bad:
        print(f"❌ {total - bad}/{total} 成立（{bad} 条不成立）")
        return 1
    print(f"✅ {total}/{total} 都红了：每一种弄坏都被判据当场抓住，源码已逐字节还原。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
