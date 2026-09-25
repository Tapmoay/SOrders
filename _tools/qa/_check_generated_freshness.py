#!/usr/bin/env python3
'''_check_generated_freshness.py —— 每个机器生成物都要能回答「我是哪一版代码的产物」（R3-07）。

### 指南 §二十一 ③ 的原话

```text
Generated Artifact Freshness（例如 Endpoint Index / AI Catalog / Capability Snapshot / Acceptance Report）
必须有：source hash / generated_at / source commit
这样才能回答：这个文档究竟对应哪一版代码？
```

R3-BOUNDARY-JUSTIFICATION: 这一条**没法用边界消除** —— 它管的是「产物」与「源码」之间的一致性，
而产物不是代码的一部分、改它不影响任何一行程序的运行。四个生成器各自都有 `--check`，
但**没有一个地方**回答「这四个产物分别对应哪一版源码、它们是不是同一版」。
本判据就是那个地方：真源表在 `_airepo.GENERATED_ARTIFACTS`（生成器读同一份），
判据**自己重算指纹**，不信任产物里写的那串。

### 判据（五组）
1. 登记表里每个产物都存在（`_airepo.GENERATED_ARTIFACTS`，⛔ 不许在别处再写一份清单）；
2. ⭐ 每个产物都声明了 `source_hash`，且与**判据现算**的指纹逐字相同；
   ⛔ 算不出指纹（glob 一个文件都没匹配上）＝**报错**，不是放过 —— 那才是「安静的检查」；
3. ⭐ 登记表里那条 `check_cmd` 真的跑得起来、且**退出码为 0**（内容级新鲜：产物 == 现在生成的结果）；
4. `source_commit` / `generated_at`（能力快照带这两个）：提交必须真的存在于本仓库，
   时刻必须是合法 ISO 且**不在未来**；
5. 反空转：产物数 ≥ MIN_ARTIFACTS、逐个都核过、`source_hash` 真比过的条数 ≥ MIN_HASHED。

### ⛔ 它证不了什么（写在前面）

· 它证的是「产物与源码一致」与「来源可追溯」，**不证**「产物里的数字是对的」——
  那是各产物自己的判据（`_check_endpoint_index_fresh.py` / `_check_hints.py` /
  `_check_capability_unification.py` / `_check_live_doc_counts.py`）的活；
· `generated_at` 只核**格式与合理性**，不比新旧：真正回答「哪一版代码」的是 `source_hash`。

用法：python _tools/qa/_check_generated_freshness.py
'''
from __future__ import annotations

import datetime as _dt
import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '_tools' / 'ai'))
from _airepo import GENERATED_ARTIFACTS, source_fingerprint  # noqa: E402

MIN_ARTIFACTS = 4
MIN_HASHED = 4
HASH_RE = re.compile(r'sha256:[0-9a-f]{64}')


def _run_check(cmd: str) -> tuple[int, str]:
    proc = subprocess.run(cmd, shell=True, cwd=str(ROOT), capture_output=True, text=True,
                          encoding='utf-8', errors='replace')
    return proc.returncode, ((proc.stdout or '') + (proc.stderr or '')).strip()


def _glob_hits(globs: tuple[str, ...]) -> int:
    n = 0
    for pattern in globs:
        n += len([p for p in ROOT.glob(pattern) if p.is_file()])
    return n


def main() -> int:
    fails: list[str] = []
    checked = 0
    hashed = 0

    if len(GENERATED_ARTIFACTS) < MIN_ARTIFACTS:
        fails.append('登记表里只有 ' + str(len(GENERATED_ARTIFACTS)) + ' 个产物（下限 '
                      + str(MIN_ARTIFACTS) + '）—— 产物清单被掏空了？')

    for spec in GENERATED_ARTIFACTS:
        path = ROOT / spec.path
        label = spec.key + '（' + spec.path + '）'
        if not path.exists():
            fails.append('产物不存在：' + label + ' —— 重跑 ' + spec.generator)
            continue
        checked += 1
        text = path.read_text(encoding='utf-8', errors='replace')

        # ---- ① 指纹 ----
        hits = _glob_hits(spec.sources)
        if hits == 0:
            fails.append(label + ' 的真源 glob 一个文件都没匹配上（指纹是空集的）—— 判据在空转，先修 sources')
            continue
        want = source_fingerprint(spec.sources)
        found = HASH_RE.findall(text)
        if spec.marker not in text:
            # ⛔ 光有那串 sha256 不够：**标记名**也要在 —— 否则判据只能靠「文件里出现过 64 位十六进制」去猜，
            #    那是「恰好对上」不是「说清楚了」。（反向验证第 ③ 条就是这么逼出来的。）
            fails.append(label + ' 里没有 source_hash 标记 —— 产物得自己说清它是哪一版源码的指纹（重跑 '
                          + spec.generator + '）')
        elif not found:
            fails.append(label + ' 里没有 source_hash 值 —— 它答不了「我是哪一版代码的产物」（重跑 '
                          + spec.generator + '）')
        elif want not in found:
            fails.append(label + ' 的 source_hash 与现算指纹不一致（产物里 ' + found[0][:24]
                          + ' / 现算 ' + want[:24] + '）—— 源码变了而产物没重跑')
        else:
            hashed += 1

        # ---- ② 生成器自己说它没过期 ----
        code, out = _run_check(spec.check_cmd)
        if code != 0:
            tail = [ln for ln in out.splitlines() if ln.strip()][-1:] or ['(无输出)']
            fails.append(label + ' 的 --check 不通过：' + tail[0][:140])

        # ---- ③ source_commit / generated_at（带这两个字段的产物）----
        commit = re.search(r'"source_commit":\s*"([^"]+)"', text)
        if commit:
            sha = commit.group(1)
            if sha != 'unknown':
                proc = subprocess.run(['git', 'cat-file', '-e', sha + '^{commit}'], cwd=str(ROOT),
                                      capture_output=True, text=True)
                if proc.returncode != 0:
                    fails.append(label + ' 声明的 source_commit ' + sha + ' 不是本仓库里的提交（编的？）')
        stamp = re.search(r'"generated_at":\s*"([^"]+)"', text)
        if stamp:
            raw = stamp.group(1)
            try:
                when = _dt.datetime.strptime(raw, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=_dt.timezone.utc)
            except ValueError:
                fails.append(label + ' 的 generated_at 不是 ISO（UTC, 秒级）：' + raw)
            else:
                if when > _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=5):
                    fails.append(label + ' 的 generated_at 在未来：' + raw)

    if hashed < MIN_HASHED:
        fails.append('真正比对过指纹的产物只有 ' + str(hashed) + ' 个（下限 ' + str(MIN_HASHED) + '）—— 判据在空转')

    print('生成物新鲜度：' + str(checked) + ' 个产物 / ' + str(hashed) + ' 个指纹比对过'
          + '（真源表：_airepo.GENERATED_ARTIFACTS）')
    for spec in GENERATED_ARTIFACTS:
        print('  · ' + spec.key + '  ← ' + spec.generator)
    if fails:
        print()
        for f in fails:
            print('  ❌ ' + f)
        print()
        print('❌ ' + str(len(fails)) + ' 条不成立')
        return 1
    print()
    print('  ✅ 5 组判据全部通过：每个产物都声明了真源指纹且与现算一致、生成器自己说没过期、'
          '来源可追溯（提交/时刻合法）。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

