#!/usr/bin/env python3
'''_check_dep_declaration.py —— 依赖**声明**与**本机实际装的版本**必须对得上（R3-07d · 指南 §二十二）。

### 为什么要有它

`backend/requirements*.txt` 是**开区间**（`cryptography>=42,<44`）—— 开区间不等于没有约束：
它声明了「这个项目跑在哪个版本区间里」。而**开区间最典型的腐烂方式**是：
声明写完就没人再看，实际环境早就飘到区间外面去了，**两边都不报错**。

2026-09-26 实测就抓到一个：本机（跑出 1018 passed 的那个环境）装的是 `cryptography 48.0.0`，
而 `requirements.txt` 写着 `cryptography>=42,<44` —— **差了 5 个大版本**。
后果不是「少装一个包」，而是：① 读文档的人以为项目跑在 43 上；② 新机器按这份文件装会**降级**；
③ 生产上到底是哪个版本，没有任何地方说得清（R3-05 才能核）。

### 判据（四组）
1. 三份 requirements 都能解析，且声明条数 ≥ MIN_DECLS（解析器坏了先喊，不许安静地一条都不查）；
2. ⭐ 每条声明都要在本机实际安装的版本上**成立**（版本号取自 `importlib.metadata`，不读我们自己写的表）；
3. ⭐ 不成立的必须登记在 EXCEPTIONS 里，每条写清「为什么」+「什么时候删掉这一条」；
4. 棘轮：例外条数 ≤ EXCEPTION_RATCHET（只减不增），且**没有化石**（键必须还是当前真出现的违反）。

### ⛔ 它证不了什么
- 它只比「本机环境」与「声明」，**不证**生产上是哪个版本（那要上机器跑 `pip freeze`，见 R3-05）；
- CI 是**运行时解析**开区间（`pip install -r requirements-all.txt`），所以 CI 绿也不代表版本固定；
- 它不判断「该不该 pin」—— 那是 `docs/DEPENDENCY_DECISION.md` 里的产品决策，要用户拍板。

用法：python _tools/qa/_check_dep_declaration.py [--check]
'''
from __future__ import annotations

import io
import sys
from importlib import metadata
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'ai'))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
FILES = ('backend/requirements.txt', 'backend/requirements-dev.txt')

MIN_DECLS = 20
#: 棘轮：例外**只减不增**。加一条就必须在同一次改动里说清为什么，并且这个数要一起改。
#: 2026-09-26 从 0 提到 1（下面唯一那条 cryptography）。**拍板之后要降回 0**。
EXCEPTION_RATCHET = 1
NEED_IN_REASON = '什么时候删掉这一条'

#: 允许存在的「声明与实测不符」：键 = `包名 声明`，值 = 为什么 + 什么时候删掉这一条。
EXCEPTIONS: dict[str, str] = {
    'cryptography cryptography>=42,<44':
        '2026-09-26 实测：本机（跑出 1018 passed 的那个环境）装的是 48.0.0，比声明的上限高 5 个大版本；'
        '而这个上限是 **f20b93a「初始提交 v0.01」（2026-04-09）** 留下来的，仓库里找不到任何理由。'
        '⛔ 不自己改声明也不自己降环境：那是产品决策（改上限＝将来新机器装到 48；降环境＝本机与 CI 都要重装），'
        '要用户拍板（指南 §二十二）。证据与三个选项写在 docs/DEPENDENCY_DECISION.md。'
        ' **什么时候删掉这一条**：R3-07d 拍板后 —— 要么把声明改成 `cryptography>=42,<49`（删这一条），'
        '要么把本机装到 43.x（同样删这一条）。两条都不做就不许删。',
}


def declared_lines(path: Path) -> list[str]:
    out: list[str] = []
    for raw in io.open(path, encoding='utf-8').read().splitlines():
        line = raw.split('#')[0].strip()
        if not line or line.startswith('-r '):
            continue
        out.append(line)
    return out


def main() -> int:
    check_mode = '--check' in sys.argv[1:]
    try:
        from packaging.requirements import Requirement
        from packaging.version import Version
    except ImportError as exc:  # pragma: no cover
        print('❌ 算不出真值：本机没有 packaging（' + str(exc) + '）—— 它是判据的依赖，先装它')
        return 1

    passed: list[str] = []
    failures: list[str] = []

    def want(ok: bool, good: str, bad: str) -> None:
        (passed if ok else failures).append(('OK  ' if ok else 'BAD ') + (good if ok else bad))

    decls: list[tuple[str, str, str]] = []  # (文件, 原始声明, 包名)
    for rel in FILES:
        path = ROOT / rel
        if not path.exists():
            want(False, '', rel + ' 不存在（依赖声明被搬走了？来改这个脚本的 FILES）')
            continue
        for line in declared_lines(path):
            try:
                req = Requirement(line)
            except Exception as exc:  # noqa: BLE001
                want(False, '', rel + ' 里这行解析不了：' + line + '（' + str(exc) + '）')
                continue
            decls.append((rel, line, req.name))

    want(len(decls) >= MIN_DECLS,
         '解析出 ' + str(len(decls)) + ' 条依赖声明（下限 ' + str(MIN_DECLS) + '）',
         '只解析出 ' + str(len(decls)) + ' 条依赖声明（下限 ' + str(MIN_DECLS) + '）—— 解析器坏了？')

    violations: list[tuple[str, str]] = []  # (键, 人话)
    for rel, line, name in decls:
        req = Requirement(line)
        try:
            installed = Version(metadata.version(name))
        except metadata.PackageNotFoundError:
            violations.append((name + ' ' + line, rel + '：`' + line + '` —— 本机**没装**这个包'))
            continue
        except Exception as exc:  # noqa: BLE001
            violations.append((name + ' ' + line, rel + '：`' + line + '` —— 版本号读不出来：' + str(exc)))
            continue
        if not req.specifier.contains(installed, prereleases=True):
            violations.append((name + ' ' + line,
                               rel + '：声明 `' + line + '`，本机实际是 **' + str(installed) + '**（不在区间里）'))

    # ④ 棘轮 + 防化石：登记下来的例外必须还是**当前真出现**的违反。
    keys_now = {k for k, _ in violations}
    fossils = [k for k in EXCEPTIONS if k not in keys_now]
    thin = [k for k, why in EXCEPTIONS.items() if NEED_IN_REASON not in why]
    unregistered = [(k, msg) for k, msg in violations if k not in EXCEPTIONS]

    want(len(EXCEPTIONS) <= EXCEPTION_RATCHET,
         '例外条数 ' + str(len(EXCEPTIONS)) + ' ≤ 棘轮 ' + str(EXCEPTION_RATCHET),
         '例外条数 ' + str(len(EXCEPTIONS)) + ' 超过棘轮 ' + str(EXCEPTION_RATCHET)
         + ' —— 棘轮是「只减不增」的：新加例外必须同时改这个数并说明为什么')
    want(not fossils, '例外表里没有化石',
         '例外表里这些键已经不再是当前的违反了（化石）：' + ' / '.join(fossils)
         + ' —— 声明/环境已经对上了，把这一条删掉')
    want(not thin, '例外每条都写了「' + NEED_IN_REASON + '」',
         '例外表里这些条没写「' + NEED_IN_REASON + '」：' + ' / '.join(thin)
         + ' —— 例外没有退出条件就会永远留在那儿')
    want(not unregistered,
         '声明的 ' + str(len(decls)) + ' 条在本机全部成立（或已在例外表里）',
         '这些声明在本机**不成立**且没有登记：' + ' ; '.join(msg for _k, msg in unregistered))

    for k, why in sorted(EXCEPTIONS.items()):
        if k in keys_now:
            print('  ⚠️  已登记的例外：' + k + ' —— ' + why)

    print('依赖声明对账：' + str(len(passed)) + ' 通过 / ' + str(len(failures)) + ' 失败'
          + '（声明 ' + str(len(decls)) + ' 条，例外 ' + str(len(EXCEPTIONS)) + ' 条）')
    if not check_mode:
        for n in passed:
            print('  ✅ ' + n[4:])
    for f in failures:
        print('  ' + f)
    if failures:
        print()
        print('  ⛔ 口径：判的是「本机环境」与「声明的版本区间」是否对得上（生产要看 R3-05）。')
        print('  ⛔ 该不该 pin 是产品决策：见 docs/DEPENDENCY_DECISION.md。')
        return 1
    print('  ✅ 每条依赖声明都在本机实际装的版本上成立（不成立的都已登记并写了退出条件）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
