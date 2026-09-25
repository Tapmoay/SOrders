#!/usr/bin/env python3
"""_check_domain_boundaries.py —— 领域边界地图的八条铁律（进 `_check_all.py` 自动跑）。

### 为什么需要它（第二轮 R2-01）
用户 2026-09-25 交来的方向指南第一节：「第二轮先不要改代码：先建立领域地图」。
地图在 `docs/DOMAIN_BOUNDARIES.md`，主体是一批 `domain` 声明块。

⛔ **一张没人核对的领域地图比没有地图更糟**：没有地图时你会去读代码拿一手真相；
有错地图时你会相信结论直接动手（这条教训本仓库在 `08_CODE_LOCATOR.md` 上写过一遍）。
所以这一页的每一条声明都必须**与代码对得上**，这条判据就是那把尺。

### 判据（八条铁律，逐条对应文档 §1）
1. 每张表**恰好一个**拥有者（`__tablename__` 全量，既不许多头也不许孤儿）；
2. `owns` 里的表名必须是真的；
3. 每个命令（`模块:函数`）必须真的存在；
4. 每个命令**恰好归一个域**；
5. `reads` 只登记跨域读边：表存在、不属于本域、且那个域名确实拥有它；
6. `events` 必须是代码里真的在产生的（扫 `outbox.enqueue` 的字面量），
   反过来，代码里产生的每一个事件也必须**恰好被一个域认领**；
7. `owns` 为空只允许 `pure_consumer: yes`；
8. `commands` 为空必须写非空的 `无命令的理由`。

⚠️ **判据自己算的东西**（不是从文档抄的）：表清单、事件类型、命令是否存在 —— 口径与实现都在
`_domain_map.py` 一处（R2-02 的命令注册表判据共用同一份解析，避免两处各写一遍）。
所以文档过期会当场报红，而不是安静地骗人。

用法：python _tools/qa/_check_domain_boundaries.py [--check]
"""
from __future__ import annotations

import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _domain_map as dm  # noqa: E402

#: 反空转下限 —— 清单/表/命令/事件少到这个数以下，说明判据自己空转了（本仓库的老规矩）。
MIN_DOMAINS = 15
MIN_TABLES = 47
MIN_COMMANDS = 30
MIN_EVENTS = 15
MIN_TEXT = 12


def main() -> int:
    blocks, unparsed = dm.load_blocks()
    tables = dm.real_tables()
    events = dm.real_events()

    fails: list[str] = []
    passed = 0

    if unparsed:
        fails.append("这些行不是 `键: 值` 的形状（判据读不出来）：" + "、".join(unparsed))
    else:
        passed += 1

    # ---- 反空转 ----------------
    if len(blocks) < MIN_DOMAINS:
        fails.append(f"只数到 {len(blocks)} 个域（<{MIN_DOMAINS}）—— 判据可能空转了")
    else:
        passed += 1
    if len(tables) < MIN_TABLES:
        fails.append(f"只数到 {len(tables)} 张表（<{MIN_TABLES}）—— 模型扫描可能坏了")
    else:
        passed += 1
    if len(events) < MIN_EVENTS:
        fails.append(f"只数到 {len(events)} 个事件类型（<{MIN_EVENTS}）—— 事件扫描可能坏了")
    else:
        passed += 1

    # ---- 每个块的键齐不齐、文字够不够 ----------------
    names: list[str] = []
    for d in blocks:
        nm = d.get("name", "?")
        names.append(nm)
        miss = [k for k in dm.REQUIRED_KEYS if k not in d]
        if miss:
            fails.append(f"域 {nm} 缺字段：" + "、".join(miss))
        if len(d.get("为什么是它自己的域", "")) < MIN_TEXT:
            fails.append(f"域 {nm} 的「为什么是它自己的域」太短（<{MIN_TEXT} 字，等于没写）")
    dup_names = {n for n in names if names.count(n) > 1}
    if dup_names:
        fails.append("域名重复：" + "、".join(sorted(dup_names)))
    if not fails:
        passed += 1

    # ---- 铁律 1/2：每张表恰好一个拥有者 ----------------
    owner_of: dict[str, str] = {}
    for d in blocks:
        nm = d.get("name", "?")
        for t in dm.split_list(d.get("owns", "")):
            if t in owner_of:
                fails.append(f"表 {t} 有**两个**拥有者：{owner_of[t]} 与 {nm}（一个事实不能有两处口径）")
            else:
                owner_of[t] = nm
            if t not in tables:
                fails.append(f"域 {nm} 声称拥有表 {t}，但项目里没有这张表（写错了名字？）")
    orphan = sorted(tables - set(owner_of))
    if orphan:
        fails.append(f"这 {len(orphan)} 张表**没有拥有者**（孤儿）：" + "、".join(orphan))
    if not fails:
        passed += 1

    # ---- 铁律 3/4：命令真的存在、且恰好归一个域 ----------------
    cmd_owner: dict[str, str] = {}
    cmd_count = 0
    for d in blocks:
        nm = d.get("name", "?")
        refs = dm.split_list(d.get("commands", ""))
        cmd_count += len(refs)
        for ref in refs:
            why = dm.command_problem(ref)
            if why:
                fails.append(f"域 {nm} 的命令 {ref} 对不上代码：{why}")
            if ref in cmd_owner:
                fails.append(f"命令 {ref} 有**两个**归属：{cmd_owner[ref]} 与 {nm}")
            else:
                cmd_owner[ref] = nm
    if cmd_count < MIN_COMMANDS:
        fails.append(f"只登记到 {cmd_count} 条命令（<{MIN_COMMANDS}）—— 地图缩水了？")
    elif not fails:
        passed += 1

    # ---- 铁律 5：reads 是**跨域**读边 ----------------
    read_edges = 0
    before = len(fails)
    for d in blocks:
        nm = d.get("name", "?")
        for item in dm.split_list(d.get("reads", "")):
            read_edges += 1
            tbl, sep, other = item.partition("@")
            if not sep or not tbl or not other:
                fails.append(f"域 {nm} 的 reads 项 {item} 不是 `表@域` 的形状")
                continue
            if tbl not in tables:
                fails.append(f"域 {nm} 读的表 {tbl} 不存在")
                continue
            if other == nm:
                fails.append(f"域 {nm} 的 reads 里写了 {tbl}@{other} —— 那是**自己的**表，reads 只登记跨域读边")
                continue
            if owner_of.get(tbl) != other:
                fails.append(
                    f"域 {nm} 认为 {tbl} 属于 {other}，但地图上它属于 "
                    + (owner_of.get(tbl) or "（没人）")
                    + " —— 读边指错了域，等于偷偷读"
                )
    if len(fails) == before:
        passed += 1

    # ---- 铁律 6：事件两边对齐 ----------------
    ev_owner: dict[str, str] = {}
    for d in blocks:
        nm = d.get("name", "?")
        for ev in dm.split_list(d.get("events", "")):
            if ev not in events:
                fails.append(f"域 {nm} 声称产生事件 {ev}，但代码里没有任何 `enqueue` 产生它")
            if ev in ev_owner:
                fails.append(f"事件 {ev} 有**两个**归属：{ev_owner[ev]} 与 {nm}")
            else:
                ev_owner[ev] = nm
    unclaimed = sorted(events - set(ev_owner))
    if unclaimed:
        fails.append(f"这 {len(unclaimed)} 个事件**没有域认领**（没人负责的事实）：" + "、".join(unclaimed))
    if not fails:
        passed += 1

    # ---- 铁律 7/8：空值的例外要留解释 ----------------
    before = len(fails)
    for d in blocks:
        nm = d.get("name", "?")
        pc = d.get("pure_consumer", "").strip().lower()
        if pc not in ("yes", "no"):
            fails.append(f"域 {nm} 的 pure_consumer 只能是 yes / no，现在是 {pc!r}")
        if not dm.split_list(d.get("owns", "")) and pc != "yes":
            fails.append(f"域 {nm} 一张表都不拥有，却没标 pure_consumer: yes")
        if not dm.split_list(d.get("commands", "")):
            why = d.get("无命令的理由", "").strip()
            if len(why) < MIN_TEXT:
                fails.append(f"域 {nm} 没有命令，但没写（或写得太短）「无命令的理由」")
    if len(fails) == before:
        passed += 1

    print(
        f"领域边界：{len(blocks)} 个域 / {len(owner_of)}/{len(tables)} 张表有主 / "
        f"{cmd_count} 条命令 / {read_edges} 条跨域读边 / {len(ev_owner)}/{len(events)} 个事件有主"
    )
    if fails:
        for f in fails:
            print("  ❌ " + f)
        return 1
    print(
        f"  ✅ {passed} 组判据全部通过：每张表恰好一个拥有者、命令与事件都在代码里对得上、"
        "读边是跨域的且指对了域、空值的例外都留了解释。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
