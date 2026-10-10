'''红线：**取消不是失败** —— 被打断的取数不许把取消写进页面级 error（BUG-0026）。

## 为什么要有它
真机上（emulator-5558，2026-10-10）司机端停在「进行中」点一次刷新、0.25 秒内派单员把单派给这个司机，
屏幕被顶成 4 行：「进行中」/ `StandaloneCoroutine was cancelled` / 「重试」/ 底部四个 Tab
（证据原文 `_tmp/test_round3/evidence_ta04_before.txt`）。机制是**两件事叠起来**：
1. `load()` 里 `loadJob?.cancel()` 之后，被取消的那一趟**仍然会跑完它的 catch** ——
   `CancellationException` 正是 `Exception` 的子类，于是「取消」被当成业务失败写进页面级 error；
2. 取数不在主线程上返回（OkHttp 的回调从网络线程续回主线程），那个 catch 于是**排在新一趟的
   `error = null` 之后**落地 —— 页面级 error 一旦有值，渲染门（`DriverOrdersScreen.kt` 的
   `vm.error != null`）就把整个列表顶掉。
交错探针 `_tmp/test_round3/probe_out.txt` 里只有 P2（取数挂在别的调度器上）看得见这一格。

## 判据（三条行为契约，缺一条都等于没修）
1. **取消不是失败**：取消分支接在通用 `catch (e: Exception)` **之前**，且把取消**重抛**出去。
2. **真失败照旧**：通用 catch 仍然写页面级 error，错误页与「重试」的接线不许被这次改动改差。
3. **只有当前那一趟能写状态**：成功路径、失败路径、`finally`（加载态）三处都按世代号让开。
   ⚠️ 为什么不用「这个 Job 是不是 loadJob」来判：`viewModelScope.launch` 在
   `Dispatchers.Main.immediate` 下可能**当场内联**执行，那一刻 `loadJob` 还指着**旧** Job。

## 判据不是「看名字在不在」
- 扫的是**剥掉注释后的代码**（`strip_comments`）：本单的修法说明里**写着**那句异常串与
  `CancellationException` —— 不剥注释的话，「取消分支存在吗」这类判据会被自己的注释骗过。
- 断言**只扫 `load()` 这一段**（从 `fun load()` 到下一个同缩进的 `fun `）：同一个文件里
  `periodHasData` / `ack` 也有 catch，全文件扫会把它们算进来。

配套：python _tools/qa/_reverse_verify_cancellation_not_error.py（13 种破坏方式全被抓）

R4-BOUNDARY-JUSTIFICATION: 这一单**只改核心区的一条既有取数链路**（DriverOrdersViewModel.load 的异常分支），
没有加扩展点：不新增端点、不动接口、错误页与「重试」的接线原样保留。边界解决不了 ——
CancellationException **正是 Exception 的子类**，所以「取消」在类型系统里与「失败」不可区分，
编译器、lint、契约都拦不住 catch (e: Exception) 把它一起收走；更难的是**时序**：取数从网络线程
续回主线程，那个 catch 会排在新一趟的 error = null 之后才落地。两件事叠起来的后果是
一次正常的刷新把整个列表顶成 4 行错误页。所以必须有一条机器判据（剥注释后只扫 load() 那一段）
钉住「取消分支在前且重抛、失败路径照旧、三处写状态都让世代号」，并有 13 种破坏方式的反向验证。

用法：python _tools/qa/_check_cancellation_not_error.py
'''
from __future__ import annotations

import re
import sys
from pathlib import Path

#: ⛔ stdout 与 stderr 都按 UTF-8 写（本机 Windows 的 stderr 默认是 GBK，红了的原因是乱码就白红了）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / 'android' / 'app' / 'src' / 'main' / 'java' / 'com' / 'tapmoay' / 'sorders'
VM = ANDROID / 'ui' / 'driver' / 'DriverOrdersViewModel.kt'
SCREEN = ANDROID / 'ui' / 'driver' / 'DriverOrdersScreen.kt'
ORDER_DOC = ROOT / 'docs' / 'changes' / 'BUG-0026.md'
CHANGES_README = ROOT / 'docs' / 'changes' / 'README.md'
LEDGER = ROOT / 'docs' / 'TEST_BUG_LEDGER.md'

#: 同类点位（同一指纹：`loadJob?.cancel()` + 通用 catch 写页面级 error + 收集实时推送）。
#: 本单**只动司机端那一处** —— 其余四处要在变更单里点名说明「为什么不动」。
PEERS = (
    'DispatcherOrdersViewModel.kt',
    'DispatcherPoolViewModel.kt',
    'ShipperOrdersViewModel.kt',
    'ReturnRequestsViewModel.kt',
)

RE_CANCEL_CATCH = re.compile(r'catch\s*\(\s*\w+\s*:\s*CancellationException\s*\)')
RE_GENERIC_CATCH = re.compile(r'catch\s*\(\s*\w+\s*:\s*Exception\s*\)')
RE_ANY_CATCH = re.compile(r'catch\s*\(')
RE_GUARD = re.compile(r'if\s*\(\s*mySeq\s*!=\s*loadSeq\s*\)\s*return@launch')
RE_GUARD_EQ = re.compile(r'if\s*\(\s*mySeq\s*==\s*loadSeq\s*\)')


def load_block(code: str) -> str:
    '''只取 `fun load()` 那一段（到下一个同缩进的 `fun ` 为止）。'''
    at = code.find('fun load()')
    if at < 0:
        return ''
    nxt = re.search(r'\n    fun ', code[at:])
    return code[at: at + nxt.start()] if nxt else code[at:]


def branch(block: str, head: re.Pattern, after: str = '') -> str:
    '''某个 catch/finally 的正文（到下一个 catch/finally 之前）。'''
    at = 0
    if after:
        pos = block.find(after)
        at = pos + len(after) if pos >= 0 else 0
    m = head.search(block, at)
    if not m:
        return ''
    rest = block[m.end():]
    nxt = re.search(r'(catch\s*\(|finally\s*\{)', rest)
    return rest[: nxt.start()] if nxt else rest


def main() -> int:
    c = Checker()

    if not VM.exists():
        print('❌ 找不到 ' + str(VM) + ' —— 病灶文件被改名或删了？')
        return 1
    code = strip_comments(read(VM))
    block = load_block(code)
    screen = strip_comments(read(SCREEN)) if SCREEN.exists() else ''

    # ── 0. 反空转：切片段/剥注释坏了必须先喊（否则下面全绿是假的）──────────
    c.section('0. 反空转')
    c.ok('切出了 load() 这一段（长度 >= 200 字符）', len(block) >= 200,
         '找不到 `fun load()`？文件被改名或方法被搬走了。长度过短说明切片段的正则坏了。')
    c.ok('load() 段里至少两个 catch（取消分支 + 通用分支）', len(RE_ANY_CATCH.findall(block)) >= 2,
         '只有一个 catch 的话，下面「取消排在通用之前」这条会**空过**。')

    # ── 1. 契约 1：取消不是失败 ───────────────────────────────────────────
    c.section('1. 取消不是失败（契约 1）')
    cancel = RE_CANCEL_CATCH.search(block)
    generic = RE_GENERIC_CATCH.search(block)
    c.ok('load() 里有取消分支 catch (… : CancellationException)', cancel is not None,
         '修法：在通用 catch **之前**加 `catch (e: CancellationException) { throw e }`。'
         '少了它，被取消的那一趟会把 `StandaloneCoroutine was cancelled` 写进页面级 error。')
    c.ok('取消分支排在通用 catch 之前', bool(cancel and generic and cancel.start() < generic.start()),
         '顺序反了等于没加：`CancellationException` 是 `Exception` 的子类，'
         '通用 catch 会先把取消吃掉。')
    br = branch(block, RE_CANCEL_CATCH)
    c.ok('取消分支把取消**重抛**出去（throw）', 'throw' in br,
         '取消只能原样抛出（协程的取消靠它传播）；吞掉它就等于把取消改成了「正常结束」。')
    c.ok('取消分支里不写页面级 error', 'error' not in br,
         '把取消写进 error 就是这一单的原始 bug —— 渲染门会拿它顶掉整个列表。')
    c.ok('CancellationException 是按 import（或全限定名）用的',
         'import kotlinx.coroutines.CancellationException' in code
         or 'kotlinx.coroutines.CancellationException' in block,
         '裸名字靠别的 import 撞对了也能编译，但下一个人会分不清是哪一族的取消异常。')

    # ── 2. 契约 2：真失败照旧（错误页与「重试」不许改差）──────────────────
    c.section('2. 真失败照旧显示错误页（契约 2）')
    c.ok('通用 catch 仍然把失败写进页面级 error', 'error = toApiException(e).message' in block,
         '网络/HTTP 失败必须照旧显示错误页 —— 这一条是「不许改差」的那一半。')
    # ⚠️ 必须扫**声明那一行的修饰符**：load_block() 是从 `fun load()` 这个子串切起的，
    #    写成 `private fun load()` 时那三个字落在块外 —— 只看块会把收成 private 放过（反验 ⑫ 抓到过）。
    m_decl = re.search(r'(?m)^[ \t]*([^\n{]*?)fun\s+load\s*\(\s*\)', code)
    mods = m_decl.group(1) if m_decl else ''
    c.ok('load() 仍然是 public（错误页的「重试」要能调它）',
         m_decl is not None and re.search(r'\b(private|internal|protected)\b', mods) is None,
         '「重试」走的就是 `vm.load()`；把它收成 private，错误页就救不回来了。')
    c.ok('DriverOrdersScreen 的错误页渲染门还在', 'vm.error != null -> ErrorView' in screen,
         '渲染门被删掉就等于「真失败也不显示」—— 修 bug 不许把这条行为一起改掉。')
    c.ok('错误页的「重试」仍然接到 vm.load()', 'onRetry = { vm.load() }' in screen,
         '接错方法的话，用户点「重试」不会有任何反应。')
    err_at = screen.find('vm.error != null')
    tab_at = screen.find('vm.ordersTab != vm.tab')
    c.ok('错误页排在「栏位还没对齐」那条 loading 之前',
         err_at >= 0 and (tab_at < 0 or err_at < tab_at),
         '顺序反了的话 ErrorView 会被 LoadingBox 顶掉（渲染门的注释里写着这条）。')

    # ── 3. 契约 3：只有当前那一趟能写状态 ─────────────────────────────────
    c.section('3. 只有当前那一趟能写状态（契约 3）')
    c.ok('有取数世代号字段（private var loadSeq = 0）',
         re.search(r'private\s+var\s+loadSeq\s*=\s*0', code) is not None,
         '没有世代号就只能靠「Job 是不是 loadJob」判，而 Main.immediate 下 launch 体可能当场内联执行，'
         '那一刻 loadJob 还指着**旧** Job。')
    up_at = block.find('val mySeq = ++loadSeq')
    launch_at = block.find('viewModelScope.launch')
    c.ok('世代号在**挂起点之前**取（++loadSeq 在 viewModelScope.launch 之前）',
         up_at >= 0 and launch_at >= 0 and up_at < launch_at,
         '挪进 launch 体内的话，两趟的取号顺序会跟着调度器变 —— 那正是这一单要修掉的那类不确定性。')
    fetch_at = block.find('val fetched = ')
    orders_at = block.find('orders = fetched')
    g1 = RE_GUARD.search(block)
    c.ok('成功路径：写 orders 之前先按世代号让开',
         g1 is not None and fetch_at >= 0 and orders_at >= 0 and fetch_at < g1.start() < orders_at,
         '过期那趟手里的数据属于上一栏/上一次条件 —— 它晚回来（没被取消）也不许把新结果顶掉。')
    gb = branch(block, RE_GENERIC_CATCH)
    c.ok('失败路径：写 error 之前先按世代号让开', RE_GUARD.search(gb) is not None,
         '过期那趟的失败不许把新一趟已经拿到的结果盖成错误页。')
    fb = branch(block, re.compile(r'finally\s*\{'))
    c.ok('finally（加载态）也按世代号让开', RE_GUARD_EQ.search(fb) is not None,
         '过期那趟的 finally 会把新一趟的转圈一起关掉（探针里 A 就把 B 的 loading 收成了 false）。')
    c.ok('旧取数仍然会被打断（loadJob?.cancel() 还在）',
         'loadJob?.cancel()' in block,
         '为了消掉这条 bug 而删掉取消，等于让刷新越点越慢（旧请求全都还在跑）。')

    # ── 4. 边界与登记（同类点位没有顺手改、台账已回填）────────────────────
    c.section('4. 边界与登记')
    order_doc = read(ORDER_DOC) if ORDER_DOC.exists() else ''
    c.ok('变更单 docs/changes/BUG-0026.md 存在', bool(order_doc),
         '修法、契约、证据与「不碰什么」都写在那份变更单里。')
    c.ok('变更单点名了 4 个同类点位（说明本单只动司机端）',
         all(p in order_doc for p in PEERS) and '同类点位' in order_doc,
         '同一指纹在 ui/ 下还有 4 处（派单员两处、货主一处、退货申请一处）—— '
         '本单动哪几处、为什么不动其余的，必须在变更单里说清，否则下一个人以为只有司机端有这个问题。')
    ta04 = [ln for ln in read(LEDGER).splitlines() if ln.strip().startswith('| TA-04')] if LEDGER.exists() else []
    c.ok('台账总表 TA-04 行的状态已写成「已修复 …」',
         bool(ta04) and '已修复' in ta04[0],
         '测试台账是这一单的来源（方向 A 的 TA-04）—— 状态不回收，下一轮还会照着它复现。')
    # ⚠️ 只扫 **TA-04 自己的详情块**：别的条目早就补过「补充（…，已修复）」那一行，
    #    整文件扫的话这一条会**空过**（改了 TA-04 也算绿）。
    ledger_txt = read(LEDGER) if LEDGER.exists() else ''
    ta04_block = ''
    _at = ledger_txt.find('### TA-04')
    if _at >= 0:
        _after = ledger_txt.find('\n### TA-', _at + 5)
        ta04_block = ledger_txt[_at: _after if _after >= 0 else len(ledger_txt)]
    c.ok('TA-04 的详情块补了「补充（…，已修复）」那一行',
         '，已修复）：' in ta04_block,
         '详情块里要有提交号与改法一句话，回查才有落点（只认 TA-04 自己那一块）。')
    c.ok('docs/changes/README.md 里有 BUG-0026 的表行',
         CHANGES_README.exists() and 'BUG-0026.md' in read(CHANGES_README),
         '登记簿少了这一行，_check_dev_spec.py 的「登记簿对账」那一条会红。')

    # ── 汇总 ─────────────────────────────────────────────────────────────
    print('\n' + '=' * 60)
    if c.fails:
        print('❌ ' + str(len(c.fails)) + ' 项未通过（通过 ' + str(c.n_ok) + ' 项）：')
        for label, _ in c.fails:
            print('   - ' + label)
        return 1
    print('✅ 全部 ' + str(c.n_ok) + ' 项通过：取消被重抛（不写页面级 error）、真失败照旧显示错误页、'
          '成功/失败/加载态三处都只让当前那一趟写状态。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
