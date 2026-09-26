#!/usr/bin/env python3
'''_check_reverse_verify_restore.py —— 反向验证的**还原契约**：不许把工作区改坏（R3-07）。

### 指南 §二十一 ② 的原话

```text
2. Reverse Verify 必须保证完整恢复
   最终应该机器证明：before snapshot = after restore snapshot
   不是：看起来差不多
```

R3-BOUNDARY-JUSTIFICATION: 这条**没法用边界消除**。140 份 `_reverse_verify_*.py` 各自**手写**了
「快照 → 注入 → 还原 → 比对」，每份都对，但**没有任何地方**保证所有份都对；
而这里出事的代价是最大的：一份漏了还原，接着跑的所有结论都建立在坏代码上（git status 也不一定看得出来）。
本判据把那份「契约」抽出来逐份核 —— 不是新增红线，是给已有 140 份各写一遍的东西立一个统一的验收。

### 判据（四组）
1. 发现到的脚本数 ≥ MIN_SCRIPTS（**扫描坏了先喊**，不许安静地扫到 0 份）；
2. ⭐ 每份的**代码**里都有三样东西（⛔ 只看代码、不看注释与文档字符串 ——
   41 份的注释里**故意**写着「⛔ 全程不碰 git checkout --」，按文本搜会把这 41 份全判红，
   那是本仓库栽过多次的「判据被文字误伤」）：
   · `read_bytes(` —— 快照是按**字节**取的；
   · `write_bytes(` —— 还原是按**字节**写回的；
   · 跑完**逐字节比对**过 —— 认形状不认变量名：`dirty(` / `dirty =` / `== raw` / `!= raw` / `bytes_identical`，
     或**一次重新读**出现在 `==`/`!=` 左侧（`if p.read_bytes() != originals[rel]`、`if Path(k).read_text() != v`）。
     ⛔ 2026-09-26 修：这条原来只认几个变量名，把 **36 份已经证明了的脚本**记成「没证明」（假缺口）。
3. ⭐ 每份的**代码**里都不许出现真的去执行 `git checkout` 的调用（注释里提它是允许的、而且是应该的）；
4. 有例外就必须在 EXCEPTIONS 里写清「为什么 + 什么时候删掉这一条」，且例外**只减不增**（与 HEAD 比）。

### ⛔ 它证不了什么

· 静态核的是**形状**，不是「这一次真的还原干净了」；后者由每份脚本自己跑完打印的
  「还原后判据全绿 / 无脏文件」来证（本判据不加 --live：那要几分钟，而且会改工作区）；
· 它不保证注入**语义正确**（那是 `_check_reverse_verify_anchors.py` 的活）。

用法：python _tools/qa/_check_reverse_verify_restore.py
'''
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
MIN_SCRIPTS = 130
#: **两级契约的两条棘轮**（⛔ 只增不减 —— 每加一份证明，就把下限抬上来）：
#: L1「按字节快照 + 按字节还原」——今天实测 102 份；
#: 重新读回来的内容参与 `==`/`!=` 比较 —— L2「逐字节证明」的**形状**（见下面 proof 那一段的长注释）。
READBACK_CMP = re.compile(r'(?:read_bytes|read_text)\s*\([^\n]*?\)\s*(?:==|!=)')
#: L3 用：`名 = …read_text(<不带 newline=>)` —— 抓住「读来的那串文本」叫什么名字。
SNAP_ASSIGN = re.compile(r'(\w+)\s*=\s*[^\n]*?read_text\(([^)]*)\)')

#: L3：**换行符会漂**的脚本上限（只减不增）。2026-09-26 实测 **34** 份：它们的快照用不带 `newline=` 的
#: `read_text()`、还原用 `write_text(newline="")` ⇒ CRLF 文件还原后变 LF（字节变了、git 看不见）。
#: L3：**换行符会漂**的脚本上限（只减不增）。2026-09-26 实测 **23** 份 —— ⚠️ 口径写清楚：
#:   判据是「**读来的文本会被写回去**」：`名 = …read_text(<不带 newline=>)` **且那个名字**出现在
#:   `write_text(...)` / `write_bytes(...)` 的实参里 ⇒ 那串 LF 会被原样写回，CRLF 文件就变成 LF。
#:   ⛔ 第一版口径太宽（只要文件里同时有裸 `read_text(` 与 `write_text(` 就算）→ 把
#:   **只是读来比对、根本不写回**的脚本也算成了风险（实测虚报 11 份）—— 判据读宽了与读窄了同样糟。
#: 收紧口径 + 两批共把 28 处改成字节级之后，实测 **6** 份（coverage_input / multi_request / fuzz_safety /
#: core_freeze / loop_e2e / place_and_picker —— 形状各不相同，要逐份看代码）。
MAX_L3 = 6

MIN_L1 = 135
#: ⛔ L2：2026-09-26 实测 **94** 份。两次变化都要记清楚（⛔ 不是「缺口改小了」）：
#:   · 88：原先记的「69 份缺口」里有 **14 份是判据自己读窄了**（只认变量名 `original`/`raw`，
#:     认不出 `originals[rel]` / `v` 这些写法）—— 那 14 份**本来就在证明**；
#:   · 94：又给 6 份补上「还原当场核对」（geocode / card_claim / ctx_budget / cost_history /
#:     image_refs / billing —— 各自跑过一遍，全绿，证明没污染源码树）；
#:   · 106：再补 12 份（local_reads / read_caps / sun_theme / undo / catalog_and_scope /
#:     concurrency_guards / cost_basis / input_guards / place_and_picker / product_guards /
#:     report_guards / soft_delete —— 同样逐份跑过，全绿）。
#: 剩下 37 份仍是真缺口。棘轮只增不减 —— 每补一份就把这个数抬上来。
MIN_L2 = 106

#: 做不到那三样、但有正当理由的 —— 键是相对路径，值是「为什么 + 什么时候删掉这一条」。
EXCEPTIONS: dict[str, str] = {
    '_tools/ai/_reverse_verify_all.py': (
        '**批处理调度器**：它自己不注入任何东西，只是按域/按改动文件去**跑别的反向验证脚本**，'
         '所以既不需要快照也不需要还原。它要守的是另一件事（超时、并发、汇总）。'
         '**什么时候删掉这一条**：如果哪天它自己也改成注入式（比如为了自检注入锁），这条就删。'
    ),
    '_tools/ai/_reverse_verify_root_clean.py': (
         '它验的是**工作区干不干净**：写一个探针文件 → 断言「有它在」→ 删掉 → 断言「没它在」。'
         '它注入的不是源码，是**一个临时探针**，而且自己删掉 —— 没有「还原源码」这回事。'
         '**什么时候删掉这一条**：如果它改成往源码里注入（那时它必须按本契约快照+还原+比对）。'
    ),
}

DOCSTRING = re.compile(r'(""".*?"""|\'\'\'.*?\'\'\')', re.S)
COMMENT = re.compile(r'#[^\n]*')
def runs_git_checkout(src: str) -> bool:
    '''**真的去执行** `git checkout` 吗。

    ⛔ 用 AST 看**调用实参**，不能用正则搜文本：反向验证脚本自己就把
    `["git", "checkout", "--", …]` 当**字符串数据**写着（那是注入内容，不是调用）——
    正则会把这种脚本全判红（本仓库的老账：判据被文字误伤）。
    '''
    import ast

    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    CALLS = {'run', 'check_output', 'check_call', 'call', 'Popen', 'system'}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, 'attr', None) or getattr(node.func, 'id', None)
        if name not in CALLS:
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Constant) and sub.value == 'checkout':
                    return True
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str) \
                        and 'checkout' in sub.value and 'git' in sub.value:
                    return True
    return False


def code_only(src: str) -> str:
    '''去掉文档字符串与注释 —— ⛔ 判据锚**代码**，不锚文字（41 份的注释里就写着那句禁令）。'''
    return COMMENT.sub('', DOCSTRING.sub('', src))


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(['git', *args], cwd=str(ROOT), capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def head_exception_count() -> int | None:
    code, out = git('show', 'HEAD:_tools/qa/_check_reverse_verify_restore.py')
    if code != 0 or not out.strip():
        return None
    m = re.search(r'EXCEPTIONS: dict\[str, str\] = \{(.*?)^\}', out, re.S | re.M)
    if not m:
        return None
    body = m.group(1).strip()
    return 0 if not body else body.count('\n') + 1


def main() -> int:
    files = sorted((ROOT / '_tools').rglob('_reverse_verify_*.py'))
    if len(files) < MIN_SCRIPTS:
        print('❌ 只扫到 ' + str(len(files)) + ' 份反向验证脚本（下限 ' + str(MIN_SCRIPTS) + '）——'
              ' 扫描坏了，这条判据现在什么都不在查')
        return 1

    fails: list[str] = []
    l1 = 0
    l2 = 0
    l3 = 0
    l3_files: list[str] = []
    no_l2: list[str] = []
    for path in files:
        rel = str(path.relative_to(ROOT)).replace(chr(92), '/')
        src_raw = path.read_text(encoding='utf-8', errors='replace')
        code = code_only(src_raw)
        if runs_git_checkout(src_raw):
            fails.append(rel + '：代码里真的执行了 git checkout（会把未提交的工作一起抹掉）')
            continue
        # ⛔ 2026-09-26 新增（实测事故）：**搬家时只换 `path` / 文本、不换字节快照**的写法。
        #    后果：还原把**老文件**的字节写进了新文件 —— 实测 `_reverse_verify_report_guards.py` 把
        #    `services/reports_service.py`（1176B 的壳）盖到了 `reports/turnover_query.py` 上，
        #    而且它自己那句「还原后与快照不一致就记账」拿的还是**同一份错字节** ⇒ 恒等、静默通过。
        #    形状判据（代码级）＋ 那 4 份脚本各自加了「注入前的不变量」：快照必须属于要改的那个文件。
        if re.search(r'path\s*,\s*original\s*=\s*\w+\s*,\s*\w+', code):
            fails.append(rel + '：写了 `path, original = _c, _t` —— 字节快照没跟着搬家，还原会把'
                         + '**老文件**的字节写进新文件（2026-09-26 实测事故）；分别赋值并同时更新 *_bytes')

        # ---- L1：快照 + 还原（两种都算，仓库里两种形状都在用）----
        #   ① 字节级：read_bytes + write_bytes（新写的脚本基本是这种）；
        #   ② 文本级：read_text + write_text(..., newline="") —— `newline=""` 不做换行翻译，
        #      对 UTF-8 文件与字节级等价（本仓库那条「不许用 PowerShell 往返」的纪律就是它）。
        byte_ok = 'read_bytes(' in code and 'write_bytes(' in code
        text_ok = ('read_text(' in code and 'write_text(' in code and 'newline=' in code)
        # `io.open(..., newline="")` / `p.open("w", ..., newline=...)` 也是安全的（不做换行翻译）
        io_ok = 'open(' in code and 'newline=' in code
        if byte_ok or text_ok or io_ok:
            l1 += 1
        elif rel not in EXCEPTIONS:
            fails.append(rel + '：没有快照/还原（read_bytes+write_bytes 或 read_text+write_text(newline=)）')
            continue
        # ---- L2：跑完**比对**证明一模一样（文本级比对也算，只要真的比了）----
        # ⛔ 2026-09-26 修（R3-07b）：这一格原来只认几个**变量名**（`dirty(` / `== raw` / `!= raw` / `!= original` …），
        #    而仓库里大量脚本写的是
        #        dirty = [rel for rel in touched if (ROOT / rel).read_bytes() != originals[rel]]
        #    —— `dirty` 是**列表变量**不是函数、比的是 `originals[rel]` 不是 `original`。
        #    于是 **36 份明明已经逐字节证明了的脚本被记成「没证明」**，报出来一个**假缺口**。
        #    本仓库的老账：「判据读得比事实窄」与「判据被文字误伤」是同一类毛病 —— 都会让缺口变成假的。
        #    现在改成认**形状**：一次**重新读**（read_bytes/read_text）出现在 `==`/`!=` 的左侧即算证明。
        #    ⚠️ 只认「读回在左」这一个方向（宁可少算、不虚报）：反向那种写法（`mutated == p.read_text()`）
        #       常常是在判「注入有没有生效」，不是判「还原没还原」，认了就会虚报。
        proof = ('dirty(' in code or 'dirty =' in code or '== raw' in code or '!= raw' in code
                 or 'bytes_identical' in code
                 or '!= src' in code or '!= orig' in code or '!= original' in code or '!= before' in code
                 or READBACK_CMP.search(code) is not None
                 # sha256(读回字节) 比对也是证明（`_reverse_verify_role_parity.py` 就是这么做的）
                 or ('sha256(' in code and 'read_bytes(' in code))
        # ---- L3：**换行符安全**（2026-09-26 实测事故后新加的一格）----
        # 事故：一整轮 `_check_all.py` 从绿变红，唯一动过的东西是 12 份反向验证的**注入+还原**；
        #   `git status` 干净，但 `docs/PROJECT_MAP/09A_HINT_CATALOG.md` 的 `source_hash` （它对
        #   `backend/app/**/*.py` + `android/app/src/main/**/*.kt` 取**原始字节**哈希）与现算不一致 ——
        #   也就是说**有文件的字节被改了，而 git 看不见**。机制：
        #     · 快照用 `read_text()`（**不带 newline=**）→ 通用换行解码，CRLF 在内存里已经变成 LF；
        #     · 还原用 `write_text(..., newline="")` → 不做翻译，把那串 LF **原样写回** ⇒
        #       一个 CRLF 文件还原后变成 LF：内容「看起来」一样，字节不一样，git（autocrlf）也不报。
        #   ⛔ 连 L2 的「文本级证明」都看不出来：`read_text() != original` 两边都被归一成 LF，恒等。
        #    正确的写法是**两边都带 `newline=""`**（`read_text(..., newline="")` + `write_text(..., newline="")`），
        #    那对 UTF-8 文件与字节级等价（本仓库那条「不许用 PowerShell 往返」的纪律就是它）。
        # 这一格只**数**、只**减**：给定棘轮 MAX_L3，涨了才红。
        risky: list[str] = []
        for _name, _args in SNAP_ASSIGN.findall(code):
            if 'newline' in _args:
                continue
            if re.search(r'write_(?:text|bytes)\s*\([^)]*\b' + re.escape(_name) + r'\b', code):
                risky.append(_name)
        if risky:
            l3 += 1
            l3_files.append(rel + '（' + '、'.join(sorted(set(risky))) + '）')
        if proof:
            l2 += 1
        else:
            no_l2.append(rel)

    # L3：**换行符会漂**的那一类（⛔ 只减不增 —— 修一份就把 MAX_L3 降一格）
    if l3 > MAX_L3:
        fails.append('换行符会漂的脚本从 ' + str(MAX_L3) + ' 涨到 ' + str(l3) + ' 份 —— 这一格只减不增；'
                     + '新写的脚本请两边都带 newline=""（见 proof 上面那段事故记录）')

    if l1 < MIN_L1:
        fails.append('L1（按字节还原）只有 ' + str(l1) + ' 份（下限 ' + str(MIN_L1) + '）—— 棘轮只增不减，别往回退')
    if l2 < MIN_L2:
        fails.append('L2（逐字节**证明**还原）只有 ' + str(l2) + ' 份（下限 ' + str(MIN_L2) + '）—— 棘轮只增不减')
    prev = head_exception_count()
    if prev is not None and len(EXCEPTIONS) > prev:
        fails.append('例外从 ' + str(prev) + ' 条涨到 ' + str(len(EXCEPTIONS)) + ' 条 —— 只减不增')
    for rel, why in EXCEPTIONS.items():
        if len(why) < 12 or '什么时候' not in why:
            fails.append('例外 ' + rel + ' 没写清「为什么 + 什么时候删掉这一条」')
        if not (ROOT / rel).exists():
            fails.append('例外 ' + rel + ' 指向一个不存在的脚本（化石）')

    print('反向验证还原契约：扫到 ' + str(len(files)) + ' 份 / 例外 ' + str(len(EXCEPTIONS)) + ' 条')
    print('  L1 按字节快照+还原：' + str(l1) + ' 份（下限 ' + str(MIN_L1) + '）')
    print('  L3 换行符会漂的脚本：' + str(l3) + ' 份（上限 ' + str(MAX_L3) + '，只减不增）')
    if l3_files:
        print('     ' + '、'.join(x.split('/')[-1].split('（')[0] for x in l3_files[:6]) + (' …' if len(l3_files) > 6 else ''))
    print('  L2 逐字节**证明**还原：' + str(l2) + ' 份（下限 ' + str(MIN_L2) + '）'
          + '  ← 差 ' + str(len(no_l2)) + ' 份还没证明（R3-07 要补的缺口，棘轮只增不减）')
    print('  ⛔ 另外核：**没有**任何一份在代码里真的执行 git checkout')
    if no_l2:
        print('  还没证明的（前 8 份）：' + '、'.join(x.split('/')[-1] for x in no_l2[:8]))
    if fails:
        print()
        for f in fails[:30]:
            print('  ❌ ' + f)
        if len(fails) > 30:
            print('  … 还有 ' + str(len(fails) - 30) + ' 条')
        print()
        print('❌ ' + str(len(fails)) + ' 条不成立')
        return 1
    print()
    print('  ✅ 4 组判据全部通过。⛔ 但它**不等于**「每一份都证明了还原」——')
    print('     L2 只有 ' + str(l2) + '/' + str(len(files)) + ' 份有机器证明，剩下 ' + str(len(no_l2))
          + ' 份是「按原文写回、但没比对」。这条缺口记在 docs/R3_PROGRESS.md，棘轮只增不减。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

