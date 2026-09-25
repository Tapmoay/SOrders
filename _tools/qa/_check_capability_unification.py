#!/usr/bin/env python3
'''_check_capability_unification.py —— **四端同源**：能力表 → API / AI / UI / Audit（R3-02）。

### 为什么需要它（指南 §R3-02 的退出条件）

第二轮做到了 API ✅ 与 AI ✅（`_check_capability_registry.py` + `_check_role_parity.py`），
剩下的两条是「UI 不再自行定义角色能力」与「Audit action 能证明 write capability 的留痕覆盖」，
外加一条总要求：**不存在第二份静态 Capability 真相**。

R3-BOUNDARY-JUSTIFICATION: 边界解法已经先做了 —— App 侧的能力快照改成**机器生成**
（`_gen_capability_snapshot.py`，带 source hash），并且后端补齐了两张此前不存在的真源表
（`role_capabilities.py` 角色门事实、`capability_audit_coverage.py` 审计覆盖）。
判据在这里守的是「**这两张表与生成物不会各走各的**」：没有它，快照可以过期、Kotlin 可以手改、
覆盖表可以漏掉一个新动作码 —— 三种都不会报错，只会让人看到一张与实际不符的表。

### 判据（五组）
1. 生成物与源码一致（**直接跑真生成器** `_gen_capability_snapshot.py --check`，不在这里重写一份）；
2. ⭐ 没有第二份静态真相：Kotlin **代码**里不许出现权限键字面量集合（注释不算 —— 那是文档）；
   生成的 Kotlin 必须带 `SOURCE_HASH`，且与后端现算出来的指纹一致；
3. 角色能力：`gate` 指向的那一行必须真有角色门；声明的角色都在那一行里；键不许与任何 `Permission` 的值重名；
4. 审计覆盖：每个**写**能力有下落；每个动作码有着落；名字真实（防化石）；关系不是双射；
   被认领的动作码必须在后端源码里真的被写过；例外/豁免是**只减不增的棘轮**（与 HEAD 比）；
5. 反空转：能力 ≥26、角色能力 ≥5、被覆盖的动作码 ≥80 —— 表被掏空时先喊。

用法：python _tools/qa/_check_capability_unification.py
'''
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

from app.core.capabilities import CAPABILITIES  # noqa: E402
from app.core.capability_audit_coverage import (  # noqa: E402
    AUDIT_CAPABILITY_EXEMPT,
    AUDIT_COVERAGE,
    AUDIT_EXCEPTIONS,
    EXCEPTION_RATCHET,
    EXEMPT_RATCHET,
)
from app.core.rbac import Permission  # noqa: E402
from app.core.role_capabilities import ROLE_CAPABILITIES  # noqa: E402
from app.models.enums import OperationAction  # noqa: E402

MIN_CAPS = 26
MIN_ROLE_CAPS = 5
MIN_ACTION_CODES = 80
KT = ROOT / 'android/app/src/main/java/com/tapmoay/sorders/core/Capabilities.kt'
GENERATOR = '_tools/ai/_gen_capability_snapshot.py'
PERM_LITERAL = re.compile(r'"[a-z_]+:[a-z_]+"')


def strip_kotlin_comments(text: str) -> str:
    '''去掉 `//` 行注释与 `/* */` 块注释 —— ⛔ 判据看的是**代码**：
    注释里提到 `ROLE_PERMISSIONS` 是**文档**（说明这个文件照着后端定的），不是第二份真相。'''
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    return chr(10).join(re.sub(r'//.*$', '', ln) for ln in text.split(chr(10)))


def git(*args: str) -> tuple[int, str]:
    p = subprocess.run(['git', *args], cwd=str(ROOT), capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def head_counts() -> tuple[int | None, int | None]:
    code, out = git('show', 'HEAD:backend/app/core/capability_audit_coverage.py')
    if code != 0 or not out.strip():
        return None, None
    e = re.search(r'EXCEPTION_RATCHET\s*=\s*(\d+)', out)
    x = re.search(r'EXEMPT_RATCHET\s*=\s*(\d+)', out)
    return (int(e.group(1)) if e else None, int(x.group(1)) if x else None)


def main() -> int:
    fails: list[str] = []

    # ---- 1. 生成物新鲜（跑真生成器）----
    proc = subprocess.run([sys.executable, str(ROOT / GENERATOR), '--check'], cwd=str(ROOT),
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    gen_out = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode != 0:
        for ln in gen_out.splitlines():
            if ln.strip().startswith('❌'):
                fails.append(ln.strip())

    # ---- 2. 没有第二份静态真相 ----
    if not KT.exists():
        fails.append('App 侧的能力快照不存在：' + str(KT.relative_to(ROOT)))
    else:
        kt = KT.read_text(encoding='utf-8')
        sys.path.insert(0, str(ROOT / '_tools/ai'))
        from _gen_capability_snapshot import source_hash  # noqa: E402
        want = source_hash()
        m = re.search(r'SOURCE_HASH:\s*String\s*=\s*"([^"]+)"', kt)
        if not m:
            fails.append('生成的 Kotlin 里没有 SOURCE_HASH —— 没法证明它来自哪一版能力表')
        elif m.group(1) != want:
            fails.append('Kotlin 里的 SOURCE_HASH 与后端不一致（' + m.group(1)[:24]
                          + ' vs ' + want[:24] + '）—— 有人手改了生成物，或者忘了重跑生成器')
    bad_files = []
    for p in sorted((ROOT / 'android/app/src/main/java').rglob('*.kt')):
        if p == KT:
            continue
        code = strip_kotlin_comments(p.read_text(encoding='utf-8', errors='replace'))
        lits = PERM_LITERAL.findall(code)
        if len(set(lits)) >= 3:
            bad_files.append(str(p.relative_to(ROOT)) + '（' + str(len(set(lits))) + ' 个权限键字面量）')
    if bad_files:
        fails.append('Kotlin **代码**里出现了手写的权限键表（第二份真相）：' + '、'.join(bad_files[:3]))

    # ---- 3. 角色能力 ----
    perm_values = {p.value for p in Permission}
    keys = [c.key for c in ROLE_CAPABILITIES];
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        fails.append('角色能力键重复：' + '、'.join(dup))
    clash = sorted(set(keys) & perm_values)
    if clash:
        fails.append('角色能力键与权限点重名（两套真相混在一个命名空间）：' + '、'.join(clash))
    if len(ROLE_CAPABILITIES) < MIN_ROLE_CAPS:
        fails.append('角色能力只登记到 ' + str(len(ROLE_CAPABILITIES)) + ' 条（下限 ' + str(MIN_ROLE_CAPS) + '）')
    for c in ROLE_CAPABILITIES:
        if c.kind not in ('read', 'write'):
            fails.append(c.key + ' 的 kind 只能是 read / write，实际是 ' + repr(c.kind))
        if len(c.why_not_permission) < 8 or len(c.when_to_remove) < 8:
            fails.append(c.key + ' 没写清「为什么不是权限点」或「什么时候删掉这一条」')
        rel, _, line_no = c.gate.partition(':');
        gp = ROOT / rel
        if not gp.exists():
            fails.append(c.key + ' 的 gate 指向一个不存在的文件：' + rel)
            continue
        lines = gp.read_text(encoding='utf-8', errors='replace').split(chr(10))
        idx = int(line_no) - 1 if line_no.isdigit() else -1
        gate_line = lines[idx] if 0 <= idx < len(lines) else ''
        if not gate_line.strip():
            fails.append(c.key + ' 的 gate 行号越界：' + c.gate)
            continue
        has_gate = ('require_roles(' in gate_line) or ('_must_dispatcher' in gate_line)
        if not has_gate:
            fails.append(c.key + ' 的 gate（' + c.gate + '）那一行不是角色门：' + gate_line.strip()[:60])
        else:
            for role in c.roles:
                token = role.upper()
                if token not in gate_line.upper() and role in ('shipper', 'dispatcher', 'driver'):
                    # 体内判断那种（`user_role_key(...) != UserRole.DISPATCHER.value`）也要能对上
                    if token not in gate_line.upper():
                        fails.append(c.key + ' 声明的角色 ' + role + ' 不在 gate 那一行里：' + c.gate)

    # ---- 4. 审计覆盖 ----
    codes = {a.value for a in OperationAction}
    write_caps = [Permission[c.permission].value for c in CAPABILITIES if c.kind == 'write']
    role_write = [c.key for c in ROLE_CAPABILITIES if c.kind == 'write']
    valid = set(write_caps) | {c.key for c in ROLE_CAPABILITIES}
    for k in sorted(set(AUDIT_COVERAGE) - valid):
        fails.append('审计覆盖里有一个不认识的能力键（化石）：' + k)
    for k in sorted(set(AUDIT_CAPABILITY_EXEMPT) - valid):
        fails.append('豁免表里有一个不认识的能力键（化石）：' + k)
    for k in sorted(set(AUDIT_EXCEPTIONS) - codes):
        fails.append('例外表里有一个不存在的动作码（化石）：' + k)
    owned: dict[str, list[str]] = {}
    for k, vs in AUDIT_COVERAGE.items():
        for v in vs:
            owned.setdefault(v, []).append(k)
    for k in sorted(set(owned) - codes):
        fails.append('覆盖表里有一个不存在的动作码（化石）：' + k)
    for cap in write_caps + role_write:
        if not AUDIT_COVERAGE.get(cap) and cap not in AUDIT_CAPABILITY_EXEMPT:
            fails.append('写能力没有下落（既没有动作码也没写为什么）：' + cap)
    orphan = sorted(codes - set(owned) - set(AUDIT_EXCEPTIONS))
    if orphan:
        fails.append('这些动作码既没有能力认领、也没进例外表：' + '、'.join(orphan[:6]))
    if not any(len(v) >= 2 for v in AUDIT_COVERAGE.values()):
        fails.append('没有任何「一个能力 → 多个动作码」—— 那说明它被写成了一一映射（指南 §R3-02-C 反的就是这个）')
    if not any(len(v) >= 2 for v in owned.values()):
        fails.append('没有任何「一个动作码 → 多个能力」—— 同上，关系不该是双射')
    backend_src = ''
    for p in (ROOT / 'backend/app').rglob('*.py'):
        if p.name == 'enums.py' and p.parent.name == 'models':
            continue
        backend_src += p.read_text(encoding='utf-8', errors='replace')
    dead = [c for c in sorted(owned) if ('OperationAction.' + c) not in backend_src]
    if dead:
        fails.append('被认领但在后端源码里从未被写过的动作码（死枚举）：' + '、'.join(dead[:6]))
    prev_e, prev_x = head_counts()
    if prev_e is not None and EXCEPTION_RATCHET > prev_e:
        fails.append('例外棘轮从 ' + str(prev_e) + ' 涨到 ' + str(EXCEPTION_RATCHET) + ' —— 只能减不能增')
    if prev_x is not None and EXEMPT_RATCHET > prev_x:
        fails.append('豁免棘轮从 ' + str(prev_x) + ' 涨到 ' + str(EXEMPT_RATCHET) + ' —— 只能减不能增')
    if len(AUDIT_EXCEPTIONS) > EXCEPTION_RATCHET:
        fails.append('例外 ' + str(len(AUDIT_EXCEPTIONS)) + ' 条 > 上限 ' + str(EXCEPTION_RATCHET))
    if len(AUDIT_CAPABILITY_EXEMPT) > EXEMPT_RATCHET:
        fails.append('豁免 ' + str(len(AUDIT_CAPABILITY_EXEMPT)) + ' 条 > 上限 ' + str(EXEMPT_RATCHET))

    # ---- 5. 反空转 ----
    if len(CAPABILITIES) < MIN_CAPS:
        fails.append('能力表只登记到 ' + str(len(CAPABILITIES)) + ' 条（下限 ' + str(MIN_CAPS) + '）—— 表被掏空了？')
    if len(owned) < MIN_ACTION_CODES:
        fails.append('被覆盖的动作码只有 ' + str(len(owned)) + ' 个（下限 ' + str(MIN_ACTION_CODES) + '）')

    print('四端同源：能力 ' + str(len(CAPABILITIES)) + ' 条（写 ' + str(len(write_caps)) + '）'
          + ' / 角色能力 ' + str(len(ROLE_CAPABILITIES)) + ' 条'
          + ' / 审计覆盖 ' + str(len(owned)) + ' 个动作码（例外 ' + str(len(AUDIT_EXCEPTIONS))
          + ' / 豁免 ' + str(len(AUDIT_CAPABILITY_EXEMPT)) + '）')
    for ln in gen_out.splitlines():
        if ln.strip().startswith('✅'):
            print('  ' + ln.strip())
    if fails:
        print()
        for f in fails:
            print('  ❌ ' + f)
        print()
        print('❌ ' + str(len(fails)) + ' 条不成立')
        return 1
    print()
    print('  ✅ 5 组判据全部通过：生成物与源码一致、Kotlin 里没有第二份真相、角色能力的门都核过、'
          '审计覆盖完整且不是双射、棘轮只减不增。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

