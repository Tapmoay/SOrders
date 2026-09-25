#!/usr/bin/env python3
'''_gen_capability_snapshot.py —— 把「能力」生成给 App（**机器生成，不许手抄**）。

R3-BOUNDARY-JUSTIFICATION: 这不是「又加一个检查器」——它是**把第二份真相删掉**的那一步。
    在此之前，App 侧关于「哪个角色能做什么」的知识是手写的（`AiWrite.SHIPPER_ACTIONS` 那 13 项），
    而指南 §R3-02-B 明确要求：**Android 不能再拥有第二份独立 Capability 真相**。
    边界解法就是这一条：后端是真源 → 机器可读产物 → App 侧生成快照（带 source hash）。
    `--check` 只是它自己的防篡改（和 `_gen_ai_read_catalog.py` 一模一样的做法），不是新判据。

### 为什么选「生成快照」而不是 `/me/capabilities` 接口（指南说这一步要按 App 架构验证）

指南原话：「但具体选择需要根据你当前的 App 架构验证，不能仅凭这份报告断言哪一个更适合。」
查过之后：**这个 App 已经在用生成快照这条路** ——
`_gen_ai_read_catalog.py` 生成 `AiReadCatalog.kt`，App 直接编译进去（读能力的角色裁剪就是这么做的）。
再开一条 `/me/capabilities` 的运行时通道，等于给同一个问题造第二套机制：
① UI 的按钮显隐会依赖一次网络往返（冷启动/离线=界面空白）；
② 多一个读端点要连带改端点索引、AI 读目录、角色对账三处判据；
③ 而能力表变化本来就是**发版级**的事（它跟着代码走）。
所以本轮沿用既有机制：**后端真源 → 生成 → App 编译进去 + source hash 对账**。

### 产物

- `docs/CAPABILITY_SNAPSHOT.json`         —— 全量快照（人看 / 判据用）
- `android/.../core/Capabilities.kt`      —— App 侧白名单（编译期带上，带 source hash）
- `docs/CAPABILITY_AUDIT_COVERAGE.md`     —— 能力 ↔ 审计动作码的覆盖表（人看）

用法：
    python _tools/ai/_gen_capability_snapshot.py          # 生成
    python _tools/ai/_gen_capability_snapshot.py --check   # 只比对（供 _check_all 用）
'''
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

from app.core.capabilities import CAPABILITIES  # noqa: E402
from app.core.capability_audit_coverage import AUDIT_CAPABILITY_EXEMPT, AUDIT_COVERAGE, AUDIT_EXCEPTIONS  # noqa: E402
from app.core.rbac import BYPASS_ROLES, ROLE_PERMISSIONS, Permission  # noqa: E402
from app.core.role_capabilities import ROLE_CAPABILITIES  # noqa: E402
from _airepo import GENERATED_ARTIFACTS, source_fingerprint  # noqa: E402

JSON_OUT = ROOT / 'docs/CAPABILITY_SNAPSHOT.json'
MD_OUT = ROOT / 'docs/CAPABILITY_AUDIT_COVERAGE.md'
KT_OUT = ROOT / 'android/app/src/main/java/com/tapmoay/sorders/core/Capabilities.kt'

#: 真源与产物登记在 `_airepo.GENERATED_ARTIFACTS` 里（判据用同一份，不各写一遍）。
ARTIFACT = next(a for a in GENERATED_ARTIFACTS if a.key == 'capability_snapshot')


def source_hash() -> str:
    '''能力表的**内容指纹**。

    ⛔ 算法在 `_airepo.source_fingerprint`（一处实现、两处消费：本生成器与
    `_check_generated_freshness.py` 必须算出同一个值，各写一份迟早走散）。
    ⛔ 真源表在 `_airepo.GENERATED_ARTIFACTS` 里（与判据同一份定义）。
    '''
    return source_fingerprint(ARTIFACT.sources)


def source_commit() -> str:
    '''产物是**哪一版代码**生成的（短 sha）。取不到 git 时如实写 unknown。'''
    import subprocess

    try:
        out = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=str(ROOT),
                             capture_output=True, text=True, encoding='utf-8', errors='replace')
        return (out.stdout or '').strip() or 'unknown'
    except OSError:
        return 'unknown'


def generated_at() -> str:
    '''生成时刻（UTC，ISO）。

    ⚠️ **它不参与判据比对**：`--check` 会把它归一化掉 —— 否则每重生成一次就「过期」一次，
    而真正回答「这个产物对应哪一版代码」的是 `source_hash` 与 `source_commit`。
    '''
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def build() -> dict:
    caps = []
    for c in CAPABILITIES:
        caps.append({
            'key': Permission[c.permission].value,
            'member': c.permission,
            'what': c.what,
            'scope': c.scope,
            'scope_why': c.scope_why,
            'roles': list(c.roles),
            'kind': c.kind,
        })
    role_caps = []
    for rc in ROLE_CAPABILITIES:
        role_caps.append({
            'key': rc.key,
            'what': rc.what,
            'roles': list(rc.roles),
            'kind': rc.kind,
            'gate': rc.gate,
            'why_not_permission': rc.why_not_permission,
            'when_to_remove': rc.when_to_remove,
        })

    role_keys = sorted(ROLE_PERMISSIONS)
    by_role: dict[str, list[str]] = {r: [] for r in role_keys}
    for c in caps:
        for r in c['roles']:
            if r in by_role:
                by_role[r].append(c['key'])
    for rc in role_caps:
        for r in rc['roles']:
            if r in by_role:
                by_role[r].append(rc['key'])
    for r in by_role:
        by_role[r] = sorted(set(by_role[r]))

    return {
        'generated_by': '_gen_capability_snapshot.py',
        'source_hash': source_hash(),
        # R3-07：能回答「这个产物对应哪一版代码」的三个字段。
        # ⚠️ `generated_at` 每次生成都会变 —— `--check` 会把它归一化掉，见那里的注释。
        'source_commit': source_commit(),
        'generated_at': generated_at(),
        'source_files': list(ARTIFACT.sources),
        'authority_note': (
            'App 侧关于「哪个角色能做什么」的**唯一**来源。⛔ 不许在 Kotlin 里再写一份：'
            '改能力表 → 重跑本脚本 → 两边一起变。'
        ),
        'bypass_roles': sorted(BYPASS_ROLES),
        'role_keys': role_keys,
        'capabilities': caps,
        'role_capabilities': role_caps,
        'by_role': by_role,
        'audit_coverage': {k: list(v) for k, v in AUDIT_COVERAGE.items()},
        'audit_exceptions': dict(AUDIT_EXCEPTIONS),
        'audit_capability_exempt': dict(AUDIT_CAPABILITY_EXEMPT),
        'counts': {
            'capabilities': len(caps),
            'role_capabilities': len(role_caps),
            'write_capabilities': sum(1 for c in caps if c['kind'] == 'write'),
            'audited_action_codes': sum(len(v) for v in AUDIT_COVERAGE.values()),
            'audit_exceptions': len(AUDIT_EXCEPTIONS),
        },
    }


def kt_string_set(items: list[str]) -> str:
    return ', '.join('"' + s + '"' for s in items)


def to_kotlin(snap: dict) -> str:
    lines = [
        '// ⛔ 本文件由 _tools/ai/_gen_capability_snapshot.py 生成，**不许手改**。',
        '// 改能力表请改 backend/app/core/{capabilities,role_capabilities,capability_audit_coverage}.py，',
        '// 然后重跑：python _tools/ai/_gen_capability_snapshot.py',
        '//',
        '// source_hash = ' + snap['source_hash'],
        '//',
        '// 它回答的唯一问题：**这个角色能不能做这件事**（指南 §R3-02：Capability → UI）。',
        '// ⛔ 界面里不要再写 `role == Role.DISPATCHER` 来判断「能不能做某个业务动作」——问这里。',
        'package com.tapmoay.sorders.core',
        '',
        'object Capabilities {',
        '    /** 能力表的指纹。判据拿它对账：Kotlin 与后端不一致就是有人手改了。 */',
        '    const val SOURCE_HASH: String = "' + snap['source_hash'] + '"',

        # ⛔ source_commit / generated_at **不写进 Kotlin**：它们每次生成都变，而这个 .kt
        #    本身又是「提示语目录」那份产物的真源之一 —— 写进来就会变成
        #    「提交一次 → 快照变 → .kt 变 → 提示语目录过期 → 再提交又变」的死循环（实测撞到过）。
        #    它们只留在 JSON 里（那份给人排查用，不参与别的产物的指纹）。
        '',
        '    /** 有没有「绕过角色」（后端 BYPASS_ROLES）：它不受能力表限制。 */',
        '    val BYPASS_ROLES: Set<String> = setOf(' + kt_string_set(snap['bypass_roles']) + ')',
        '',
        '    /** 角色 → 它能做的全部能力键（含没有权限点的角色能力）。 */',
        '    val BY_ROLE: Map<String, Set<String>> = mapOf('
    ]
    for role, keys in snap['by_role'].items():
        lines.append('        "' + role + '" to setOf(' + kt_string_set(keys) + '),')
    lines.append('    )')
    lines.append('')
    lines.append('    /** 能力键 → 给人看的一句话（排障/审计页直接显示它，别再各写一份）。 */')
    lines.append('    val WHAT: Map<String, String> = mapOf(')
    for c in snap['capabilities']:
        lines.append('        "' + c['key'] + '" to "' + c['what'].replace('"', '') + '",')
    for rc in snap['role_capabilities']:
        lines.append('        "' + rc['key'] + '" to "' + rc['what'].replace('"', '') + '",')
    lines.append('    )')
    lines.append('')
    lines.append('    /**')
    lines.append('     * 这个角色能不能做这件事。')
    lines.append('     *')
    lines.append('     * ⛔ 认不出角色 = 一律 false（fail-closed）：新角色上线时宁可少显示一个按钮，')
    lines.append('     *    也不要因为「没见过的角色」而把界面全开出来。')
    lines.append('     */')
    lines.append('    fun can(role: String?, key: String): Boolean {')
    lines.append('        val r = role?.trim()?.lowercase() ?: return false')
    lines.append('        if (r in BYPASS_ROLES) return true')
    lines.append('        return BY_ROLE[r]?.contains(key) ?: false')
    lines.append('    }')
    lines.append('')
    lines.append('    /** 这个角色手上的全部能力键（界面要「按能力筛一串入口」时用它）。 */')
    lines.append('    fun of(role: String?): Set<String> {')
    lines.append('        val r = role?.trim()?.lowercase() ?: return emptySet()')
    lines.append('        if (r in BYPASS_ROLES) return BY_ROLE.values.flatten().toSet()')
    lines.append('        return BY_ROLE[r] ?: emptySet()')
    lines.append('    }')
    lines.append('}')
    return chr(10).join(lines) + chr(10)


def to_markdown(snap: dict) -> str:
    out = [
        '# 能力 ↔ 审计覆盖（Capability Audit Coverage）',
        '',
        '> **本文件由 `_tools/ai/_gen_capability_snapshot.py` 生成，不要手改。**',
        '> 重新生成：`python _tools/ai/_gen_capability_snapshot.py`',
        '>',
        '> `source_hash = ' + snap['source_hash'] + '`',
        '',
        '这张表回答：**一个写能力会留下哪些审计动作码**（指南 §R3-02-C：不要假设一一对应）。',
        '',
        '> 名词：**动作码**（action code）= `backend/app/models/enums.py` 里 `OperationAction` 的成员名；',
        '> 一个 capability 可以对应多个 action，一个 action 也可以由多个 capability 产生（例如 `ORDER_CANCEL`）。',
        '',
        '| 能力 | 动作码 |',
        '| --- | --- |',
    ]
    for k, v in sorted(snap['audit_coverage'].items()):
        out.append('| `' + k + '` | ' + (', '.join('`' + x + '`' for x in v) if v else '—') + ' |')
    out += ['', '## 例外：没有能力认领的动作码', '', '| 动作码 | 为什么 + 什么时候删掉这一条 |', '| --- | --- |']
    for k, v in sorted(snap['audit_exceptions'].items()):
        out.append('| `' + k + '` | ' + v.replace(chr(10), ' ') + ' |')
    out += ['', '## 豁免：写能力但一个动作码都没有', '', '| 能力 | 为什么 + 什么时候删掉这一条 |', '| --- | --- |']
    for k, v in sorted(snap['audit_capability_exempt'].items()):
        out.append('| `' + k + '` | ' + v.replace(chr(10), ' ') + ' |')
    out += ['', '---', '', '## 说明：这张表证明什么、不证明什么', '',
            '✅ 证明**覆盖与命名**：每个写能力都有下落；每个动作码都有着落；名字都是真的；关系不是双射。',
            '⛔ **不证明**「这个动作码确实由这个能力授权」—— 那要逐条读写入点的鉴权，本轮没做。', '']
    return chr(10).join(out)


def _strip_volatile(text: str) -> str:
    '''比对前把**每次生成都会变**的字段去掉（R3-07 的新鲜度契约）。

    ⛔ 去掉 `generated_at` **和** `source_commit` 两个字段（Kotlin 里对应的两个常量也去掉）：
    它们记的是「哪一次生成、哪一版代码生成的」——**每次都变**，一行代码没改也会变
    （哪怕只是提交了一次别的东西）。
    ⛔ 但 `source_hash` **不去掉**：它变了就是真的变了（真源动了），那才是内容契约。
    '''
    out = []
    for ln in text.split(chr(10)):
        s = ln.strip()
        if s.startswith('"generated_at"') or s.startswith('"source_commit"'):
            continue
        if s.startswith('const val GENERATED_AT') or s.startswith('const val SOURCE_COMMIT'):
            continue
        out.append(ln)
    return chr(10).join(out)


def main() -> int:
    check = '--check' in sys.argv
    snap = build()
    payload = json.dumps(snap, ensure_ascii=False, indent=1) + chr(10)
    kt = to_kotlin(snap)
    md = to_markdown(snap)
    if check:
        ok = True
        for p, want in ((JSON_OUT, payload), (KT_OUT, kt), (MD_OUT, md)):
            if not p.exists():
                print('❌ 缺少产物：' + str(p.relative_to(ROOT)))
                ok = False
            elif _strip_volatile(p.read_text(encoding='utf-8')) != _strip_volatile(want):
                print('❌ 产物已过期：' + str(p.relative_to(ROOT)) + '（重跑生成脚本）')
                ok = False
        if ok:
            c = snap['counts']
            print('✅ 能力快照与源码一致（' + str(c['capabilities']) + ' 条能力 / '
                  + str(c['role_capabilities']) + ' 条角色能力 / ' + str(c['audited_action_codes']) + ' 个动作码）')
            return 0
        return 1
    JSON_OUT.write_text(payload, encoding='utf-8')
    KT_OUT.write_text(kt, encoding='utf-8')
    MD_OUT.write_text(md, encoding='utf-8')
    c = snap['counts']
    print('✅ 已生成：' + str(JSON_OUT.relative_to(ROOT)))
    print('✅ 已生成：' + str(KT_OUT.relative_to(ROOT)))
    print('✅ 已生成：' + str(MD_OUT.relative_to(ROOT)))
    print('   ' + str(c['capabilities']) + ' 条能力（' + str(c['write_capabilities']) + ' 写）+ '
          + str(c['role_capabilities']) + ' 条角色能力；审计覆盖 ' + str(c['audited_action_codes'])
          + ' 个动作码 / 例外 ' + str(c['audit_exceptions']) + ' 条')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

