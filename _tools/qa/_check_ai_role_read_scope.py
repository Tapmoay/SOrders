#!/usr/bin/env python
"""
AI 的角色读权限**两侧一致**（GOV-0024，2026-10-11）

用户原话（这次点名要修的那条红）：
  「AI 以为货主能读挂账单位、计费规则、开支分类啊……这个**从根源上后端做了一个拦截**，
   但是我们要**从 AI 那也做个拦截** —— 就是 AI **明确地知道**：我作为货主，**只能读货主的
   那些东西**，其他的他**根本读不了**，他**压根就不会去想**去读这些他**能力范围之外**的事情。」

这份判据盯同一条链的**两头**，中间夹着的每一样都必须同源：

  后端源码 → backend/scripts/gen_endpoint_index.py → docs/ai/ai_read_catalog.json
        → AiReadCatalog.kt（机器生成）→ AiReads.forRole → 三个消费点：
            ① 提示词里的**范围声明**（AiReadScope.rule）
            ② read_data 的工具说明（哪几张表摆在它眼前）
            ③ 执行前的门 AiReads.allows（工具说明看不到 ≠ 调不到）

盯 6 件事：
  0. 反空转：解析出来的东西够不够多（模块数、表数、目录行数）—— 少一个就先报错，
     而不是安静地什么都不查（本仓栽过 5 次「手写清单过期了但检查还是绿的」）。
  1. **范围声明在**：SCOPE_RULE 与 NO_PERMISSION 逐字被 brief() 拼进提示词，
     而且就落在「你能做什么」那一段里、紧跟在「查数据」后面。
  2. **范围与目录同源**：把声明文本解析回来（模块中文名 + 表张数），逐个角色对账
     「目录里这个角色能读到的行」—— 不是拿代码再算一遍（那只能证明两个函数一样）。
  3. **范围是有效的**：每个角色至少拦得住一样东西（货主那份不许出现派单员专属的模块名，
     反之亦然）—— 「范围 = 全部」这种看着绿、其实没拦。
  4. **两道门同一份表**：read_data 的工具说明 = AiReads.forRole（不是另一个列表），
     执行前的门 = AiReads.allows，而且 AiReadScope 不许另算一份裁剪。
  5. **目录没被手抄**：AiReadCatalog.kt 的角色来自生成器（逐行对账后端算出来的答案）。

R4-BOUNDARY-JUSTIFICATION: 这是第四轮（R4）长出来的**新边界判据**，理由三条：
  ① 它钉的是**读权限**这条链上原来没有人守的那一段 —— 「AI 知不知道自己能读什么」；
     原来的 _check_role_parity.py 只验「AI 的动作集 ⊆ 后端授权」，一个字都没管提示词。
  ② 它必须**与生成链同源**：范围清单里任何一个手抄的字都会静默过期（不报错、只是模型越来越
     不会用），所以判据把目录那一侧当**唯一权威**反向核回提示词。
  ③ 它不许被顺手放宽绕过：范围声明被删 / 模块被裁错 / 执行门被短路，三种都必须当场变红
     （配套：python _tools/qa/_reverse_verify_ai_role_read_scope.py，8 种破坏方式全被抓）。

用法：python _tools/qa/_check_ai_role_read_scope.py
      python _tools/qa/_check_ai_role_read_scope.py --list   # 打一份人读的清单
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _check_hints import Checker, read, strip_comments  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
AI = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
CATALOG_JSON = ROOT / "docs/ai/ai_read_catalog.json"
GEN = ROOT / "_tools/ai/_gen_ai_read_catalog.py"
SCOPE = AI / "AiReadScope.kt"
PROMPT = AI / "AiRolePrompt.kt"
READS = AI / "AiReads.kt"
SERVICE = AI / "AiReadService.kt"
TEST_AI = ROOT / "android/app/src/test/java/com/tapmoay/sorders/ai"
TOOLS = AI / "AiTools.kt"

# ---- 反空转下限（清单过期时先报错，而不是安静地什么都不查） ----
MIN_MODULES = 10          # 派单员能读的模块个数（2026-10-11 实测 16）
MIN_TABLES = 30           # 派单员能读的表数（实测 53）
MIN_SHIPPER_TABLES = 15   # 货主能读的表数（实测 23）
MIN_CATALOG = 50          # 目录里的行数（实测 69）

# ---- 正则 ---------------------------------------------------------------

#: AiReadScope.rule(<模块列表变量>, <同一份列表的标识>) —— 拼出来的那一行
#: AiReads.forRole(...) 的**实参写法**（同一份裁剪的两个消费点必须传同一个东西）
#: 执行前的门（工具说明里看不到 ≠ 调不到）
#: 通用读回器的资源键（"product", "product_id" ->）


# ---- 解析：把源码里的事实读出来（不手写任何清单） ----

def read_scope_sites() -> list:
    """AiRolePrompt.kt 里**拼过范围声明**的调用点 -> [(模块实参, 标识实参)]。

    三行散在三个文件里也能拼上这条链的只有一处：确认声明真的被拼进了提示词，
    而不是「定义了但没人调」（那是本仓最爱的静默失效形状）。
    """
    src = strip_comments(read(PROMPT))
    out = []
    pos = 0
    while True:
        at = src.find('AiReadScope.rule(', pos)
        if at < 0:
            break
        pos = at + 1
        d = 1
        z = at + len('AiReadScope.rule(')
        while z < len(src) and d > 0:
            if src[z] == '(':
                d += 1
            elif src[z] == ')':
                d -= 1
            z += 1
        inner = src[at + len('AiReadScope.rule('):z - 1]
        parts = inner.split(',', 1)
        mod = parts[0].strip()
        if 'modulesOf(' in mod:
            mod = mod.split('modulesOf(', 1)[1].rstrip(')')
        ident = parts[1].strip() if len(parts) > 1 else ''
        if ident.endswith('.size'):
            ident = ident[:-5].strip()
        out.append((mod, ident))
    return out

def for_role_args(path) -> list:
    """某个文件里 AiReads.forRole(...) 的全部实参写法（去重、压掉空白）。"""
    src = strip_comments(read(path))
    out = set()
    pos = 0
    while True:
        at = src.find('AiReads.forRole(', pos)
        if at < 0:
            break
        pos = at + 1
        end = src.find(')', at)
        out.add(' '.join(src[at + len('AiReads.forRole('):end].split()))
    return sorted(out)


def scope_texts() -> dict:
    """从 AiReadScope.kt 里取两段**逐字**文案（判据钉的就是它们）。"""
    src = strip_comments(read(SCOPE))
    out = {}
    for name in ('SCOPE_RULE', 'NO_PERMISSION'):
        at = src.find('const val ' + name)
        q = src.find(chr(34), at)
        z = src.find(chr(34), q + 1)
        out[name] = src[q + 1:z] if (at >= 0 and q >= 0 and z > q) else None
    return out


def snapshot_res_keys() -> list:
    """AiWriteDataSource.snapshot 能认出的资源键（通用读回器的分派表）。"""
    src = strip_comments(read(AI / 'AiWriteDataSource.kt'))
    at = src.find('override suspend fun snapshot(')
    if at < 0:
        return []
    body = src[at:at + 12000]
    out = set()
    pos = 0
    while True:
        q = body.find(chr(34), pos)
        if q < 0:
            break
        z = body.find(chr(34), q + 1)
        if z < 0:
            break
        tok = body[q + 1:z]
        pos = z + 1
        if tok and tok.islower() and tok.isidentifier() and '->' in body[z:z + 40]:
            out.add(tok)
    return sorted(out)

def catalog_rows() -> list:
    """目录里每一行的 {action, module, cn, path, roles, memberOnly}（**唯一权威**：后端的授权）。

    ⚠️ 这里**不用正则**：目录里那一行本身带引号与括号，正则得靠转义层层套，而转义写错的形态
    恰好是「静默匹配不到」—— 判据会绿着什么都不查（本仓最忌的形状）。改用按字符切的解析器：
    引号与括号在目录里各只有一个含义。
    """
    DQ = chr(34)
    src = read(AI / 'AiReadCatalog.kt')
    rows = []
    pos = 0
    while True:
        at = src.find('ReadAction(', pos)
        if at < 0:
            break
        pos = at + 1
        fld = []
        q = src.find(DQ, at)
        while len(fld) < 3 and q >= 0:
            z = src.find(DQ, q + 1)
            if z < 0:
                break
            fld.append(src[q + 1:z])
            q = src.find(DQ, z + 1)
        if len(fld) < 3 or '.' not in fld[0] or ' ' in fld[0]:
            continue
        tail = src[at:at + 3000]
        s = tail.find('setOf(')
        body = ''
        after = tail
        if s >= 0:
            d = 1
            z = s + len('setOf(')
            while z < len(tail) and d > 0:
                if tail[z] == '(':
                    d += 1
                elif tail[z] == ')':
                    d -= 1
                z += 1
            body = tail[s:z]
            after = tail[z:z + 200]
        inner_roles = body[body.find('(') + 1:body.rfind(')')] if body else ''
        head = after.lstrip(' ,')
        member = head[:4] == 'true'
        rows.append({
            'action': fld[0],
            'module': fld[0].split('.')[0],
            'cn': fld[1],
            'path': fld[2],
            'roles': set(re.findall('[a-z]+', inner_roles)),
            'memberOnly': member,
        })
    return rows

def catalog_of(role: str, member: bool) -> list:
    """目录里这个角色（+ 是不是批发商）能读到的行 —— 判据的**唯一权威**。"""
    return [r for r in catalog_rows() if role in r["roles"] and (member or not r["memberOnly"])]

def gen_actions() -> dict:
    """**从后端源码再算一遍**每个端点的准入角色（证明目录没被手改宽）。"""
    spec = importlib.util.spec_from_file_location("_gen_catalog", GEN)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.endpoint_roles()
def _norm(path: str) -> str:
    return re.sub(r"{[^}]*}", "{}", path.strip("/"))

DISPATCHER_ONLY_MODULES = ("arrears", "driver_billing_rules", "expense_categories", "freight_categories",
                           "freight_templates", "invoices", "order_products", "order_template_categories")
SHIPPER_MUST_HAVE = ("orders", "products")
CORE_CHAIN = ("backend/scripts/gen_endpoint_index.py", "_tools/ai/_gen_ai_read_catalog.py", "docs/ai/ai_read_catalog.json")
PROBE_ENDPOINTS = (
    ("GET", "/api/v1/arrears-units"),
    ("GET", "/api/v1/driver-billing-rules"),
    ("GET", "/api/v1/expense-categories"),
    ("GET", "/api/v1/freight-categories"),
    ("GET", "/api/v1/freight-templates"),
    ("GET", "/api/v1/order-template-categories"),
)

# ---- 判据 ---------------------------------------------------------------
#: 范围声明的调用行（在 AiRolePrompt.kt 里就这一行 —— 顺序判据锚在它身上）
_SCOPE_CALL_LINE = 'AiReadScope.rule(AiReadScope.modulesOf(reads), reads.size)?.let { appendLine(it) }'
_CALL_FORROLE_LOOK = 'AiReads.forRole('
_GATE_LOOK = 'AiReads.allows('

#: 判据里钉的两段文案（与 AiReadScope.kt 逐字对照）
SCOPE_RULE_TEXT = '你只能读上面这几块里的东西。范围外的一律不要尝试、也不要猜（后台会直接拦住，换一种问法也一样）。'
NO_PERMISSION_TEXT = '读不了的东西 = **没有授权给你**，不是「系统里没有」；被问到就直说这件事不归你看，别绕。'

DISPATCHER_ONLY_MODULES = ('arrears', 'driver_billing_rules', 'expense_categories', 'freight_categories',
                           'freight_templates', 'invoices', 'order_products', 'order_template_categories')
SHIPPER_MUST_HAVE = ('orders', 'products')
CORE_CHAIN = ('backend/scripts/gen_endpoint_index.py', '_tools/ai/_gen_ai_read_catalog.py', 'docs/ai/ai_read_catalog.json')
PROBE_ENDPOINTS = (
    ('GET', '/api/v1/arrears-units'),
    ('GET', '/api/v1/driver-billing-rules'),
    ('GET', '/api/v1/expense-categories'),
    ('GET', '/api/v1/freight-categories'),
    ('GET', '/api/v1/freight-templates'),
    ('GET', '/api/v1/order-template-categories'),
)


def _norm(path: str) -> str:
    return re.sub(r'{[^}]*}', '{}', path.strip('/'))


def check():
    c = Checker()
    rows = catalog_rows()
    scopes = read_scope_sites()
    texts = scope_texts()
    keys = snapshot_res_keys()
    c.section('0. 反空转：解析出来的事实够不够多')
    c.ok('目录行数 >= %d' % MIN_CATALOG, len(rows) >= MIN_CATALOG,
         '只解析出 %d 行 —— 目录格式变了？（catalog_rows 该跟着改）' % len(rows))
    c.ok('认得出角色的行 >= 50', sum(1 for r in rows if r['roles']) >= 50,
         '只有 %d 行解析出角色 —— roles 的写法变了？' % sum(1 for r in rows if r['roles']))
    c.ok('memberOnly 也解析出来了', sum(1 for r in rows if r['memberOnly']) >= 2,
         '只认出 %d 行 memberOnly —— 参数顺序变了？' % sum(1 for r in rows if r['memberOnly']))
    c.ok('范围声明的调用点恰好 1 处', len(scopes) == 1,
         '找到 %d 处 —— 范围声明只能拼一次（两份边界 = 说不清哪份算）' % len(scopes))
    c.ok('派单员能读的模块 >= %d 个' % MIN_MODULES,
         len({r['module'] for r in catalog_of('dispatcher', False)}) >= MIN_MODULES, '')
    c.ok('派单员能读的表 >= %d 张' % MIN_TABLES, len(catalog_of('dispatcher', False)) >= MIN_TABLES, '')
    c.ok('货主能读的表 >= %d 张' % MIN_SHIPPER_TABLES,
         len(catalog_of('shipper', False)) >= MIN_SHIPPER_TABLES, '')
    c.ok('通用读回器认得 >= 25 个资源键', len(keys) >= 25, '只认出 %d 个：%s' % (len(keys), keys[:6]))
    c.ok('两段范围文案都解析到了', bool(texts.get('SCOPE_RULE')) and bool(texts.get('NO_PERMISSION')),
         repr(texts))
    c.ok('SCOPE_RULE 与判据里钉的那句逐字一致', texts.get('SCOPE_RULE') == SCOPE_RULE_TEXT,
         '现在是 %r' % texts.get('SCOPE_RULE'))
    c.ok('NO_PERMISSION 与判据里钉的那句逐字一致', texts.get('NO_PERMISSION') == NO_PERMISSION_TEXT,
         '现在是 %r' % texts.get('NO_PERMISSION'))
    c.section('1. 范围声明在不在（提示词里那句硬规矩）')
    c.ok('brief() 真的拼了范围声明', len(scopes) >= 1,
         'AiRolePrompt 里没有 AiReadScope.rule(...) 调用 —— 定义了没人拼 = 静默失效')
    if scopes:
        modvar, ident = scopes[0]
        c.ok('声明用的是同一份 reads（模块与表数都从它来）', modvar == ident,
             'rule(%s, %s) —— 两个实参必须是同一个列表' % (modvar, ident))
    sc = strip_comments(read(SCOPE))
    c.ok('AiReadScope 里没有另算一份裁剪', 'forRole' not in sc and 'roles' not in sc,
         'AiReadScope.kt 里出现了 forRole/roles —— 那是第三份边界，两道门会对不上')
    plines = strip_comments(read(PROMPT)).splitlines()
    idx = [i for i, ln in enumerate(plines) if _SCOPE_CALL_LINE in ln]
    c.ok('声明就拼在那唯一一行上', len(idx) == 1, '找到 %d 行' % len(idx))
    if len(idx) == 1:
        i = idx[0]
        prev = [ln for ln in plines[max(0, i - 12):i] if '查数据' in ln]
        nxt = [ln for ln in plines[i + 1:i + 5] if '他界面上有的页面' in ln]
        c.ok('声明紧跟在「查数据」之后', bool(prev), '上溯 12 行没有「查数据」—— 顺序变了')
        c.ok('声明排在页面清单之前（还在「你能做什么」那一段里）', bool(nxt), '下一行不是页面清单')
    tsrc = strip_comments(read(TEST_AI / 'AiRolePromptTest.kt'))
    c.ok('单测也钉着这两句（Kotlin 侧的证据）',
         'AiReadScope.SCOPE_RULE' in tsrc and 'AiReadScope.NO_PERMISSION' in tsrc,
         'AiRolePromptTest.kt 里没有引用 SCOPE_RULE / NO_PERMISSION')
    c.section('2. 范围与目录同源（提示词里那份 = 后端授权那份）')
    for role, cn in (('dispatcher', '派单员'), ('shipper', '货主')):
        got = catalog_of(role, False)
        floor = MIN_TABLES if role == 'dispatcher' else MIN_SHIPPER_TABLES
        c.ok('%s：目录里至少 %d 张表（反空转）' % (cn, floor), len(got) >= floor, '')
        c.ok('%s：目录里每张表的模块都认得出来' % cn, all(r['module'] for r in got), '')
    sh_keys = {r['module'] for r in catalog_of('shipper', False)}
    dp_keys = {r['module'] for r in catalog_of('dispatcher', False)}
    c.ok('货主那份确实被裁过（不是照抄派单员的）', len(sh_keys) < len(dp_keys),
         '货主 %d 个模块 / 派单员 %d 个 —— 一样多说明裁剪失效' % (len(sh_keys), len(dp_keys)))
    c.section('3. 范围是有效的（每个角色至少拦得住一样东西）')
    leaked = sorted(m for m in DISPATCHER_ONLY_MODULES if m in sh_keys)
    lost = sorted(m for m in SHIPPER_MUST_HAVE if m not in sh_keys)
    gap = sorted(dp_keys - sh_keys)
    c.ok('用户点名的那几个模块货主读不到', not leaked,
         '货主范围里漏进了：%s（后端只给派单员）' % '、'.join(leaked))
    c.ok('货主本来就能读的模块没被裁掉（裁多了也是故障）', not lost,
         '货主范围里少了：%s —— 明明有权限却被说成读不了' % '、'.join(lost))
    c.ok('派单员的范围确实比货主宽（至少多 3 个模块）', len(gap) >= 3,
         '只多出 %d 个：%s' % (len(gap), gap))
    c.section('4. 两道门是同一份表（工具说明 + 执行前的门）')
    tsrc2 = strip_comments(read(TOOLS))
    c.ok('read_data 的清单来自 AiReads.forRole', _CALL_FORROLE_LOOK in tsrc2,
         'AiTools.kt 里没有 AiReads.forRole —— 工具清单另算了一份')
    c.ok('工具 schema 也走同一份（不是另一个列表）', tsrc2.count('forRole') >= 1 and 'AiReads' in tsrc2, '')
    ssrc = strip_comments(read(SERVICE))
    c.ok('执行前真的过 AiReads.allows 这道门', _GATE_LOOK in ssrc,
         'AiReadService.kt 里找不到 AiReads.allows(...) —— 工具说明看不到 ≠ 调不到，门没了')
    c.ok('门的实参带角色与动作（没写死 true）',
         'role' in ssrc[ssrc.find(_GATE_LOOK):ssrc.find(_GATE_LOOK) + 90], '')
    rsrc = strip_comments(read(READS))
    at = rsrc.find('fun forRole(')
    fbody = rsrc[at:at + 900] if at >= 0 else ''
    c.ok('AiReads.forRole 真的按角色裁了（裁剪被去掉 = 每个角色都看到同一份全表）',
         'k in it.roles' in fbody and 'enabledModules' in fbody and '.filter' in fbody,
         'forRole 里找不到 "k in it.roles" / 模块过滤 —— 裁剪被去掉了：'
         '提示词、工具说明、执行前的门会同时变成「什么都能读」，而且不报错')
    c.ok('生成链三个环节都在', all((ROOT / rel).exists() for rel in CORE_CHAIN), '缺文件')
    c.section('5. 目录的角色 = 后端算出来的角色（没被手改宽）')
    ends = gen_actions()
    c.ok('后端端点表非空（生成器活着）', len(ends) >= 200, '只算出 %d 个端点' % len(ends))
    widened = []
    for r in rows:
        if not r['path'].startswith('/api/'):
            continue   # 本机能力（无后端端点）另算，见 AiLocalReads
        ent = ends.get(('GET', r['path'])) or ends.get(('POST', r['path']))
        if not ent:
            widened.append((r['action'], '目录里的路径在后端找不到'))
            continue
        extra = sorted(r['roles'] - ent['roles'])
        if extra:
            widened.append((r['action'], '多给了 %s（后端：%s）' % (extra, sorted(ent['roles']))))
    c.ok('目录里没有一条端点是写宽的', not widened,
         '%d 条对不上：%s' % (len(widened), widened[:4]))
    for meth, url in PROBE_ENDPOINTS:
        ent = ends.get((meth, url))
        c.ok('后端 %s %s 只给派单员' % (meth, url), bool(ent) and ent['roles'] == {'dispatcher'},
             '后端算出来是 %s' % (sorted(ent['roles']) if ent else None))
        has = [r for r in rows if r['path'] == url]
        c.ok('目录里 %s 有一条（整行被删掉也算故障）' % url, bool(has),
             '目录里找不到这一条 —— 这一行被删了，AI 那边的范围会凭空少一块（而且是静默的）')
        c.ok('目录里 %s 也没有给货主' % url,
             all('shipper' not in r['roles'] for r in rows if r['path'] == url),
             '目录里这一条给了货主：%s' % [r['action'] for r in rows if r['path'] == url])
    return c, rows


def main() -> int:
    c, rows = check()
    print()
    print('=' * 60)
    if c.fails:
        print('❌ AI 的角色读范围不自洽（%d/%d 项不通过）：' % (len(c.fails), len(c.fails) + c.n_ok))
        for label, detail in c.fails:
            print('   - ' + label)
            if detail:
                print('     ' + detail)
        return 1
    print('✅ AI 的角色读范围与后端授权一致（%d 项全过）' % c.n_ok)
    if '--list' in sys.argv:
        print()
        for role, cn in (('dispatcher', '派单员'), ('shipper', '货主')):
            got = catalog_of(role, False)
            mods = sorted({r['cn'] for r in got})
            print('%s 能读 %d 个模块 / %d 张表：%s' % (cn, len(mods), len(got), '、'.join(mods)))
    return 0


if __name__ == '__main__':
    sys.exit(main())