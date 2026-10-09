#!/usr/bin/env python3
"""反向验证 _tools/finance/_check_expense_links.py 真的会红（BUG-0023 / 台账 TB-07）。

## 为什么是这一份
判据本身是「接线型」的（某处必须有某个写法、某处不许再有某个写法）—— 接线型判据最典型的
失效方式是锚点太宽或太窄：把守卫的调用删掉、把 SQL 里那一刀加回来、把 400 变成 500，
判据都必须当场红，而且红的必须是**那一条**判据，不是随便红一条。

## 25 种破坏（每一种都必须让判据当场红，且报出对应那条标签）

| # | 注入 | 现实里谁会这么改 |
| --- | --- | --- |
| ① | 守卫从 create_expense 里被摘掉 | 「反正报表能看出来」 |
| ② | 司机那格不再看 is_active | 只判存在，忘了停用/已删账号 |
| ③ | 车辆那格查的不是那一辆车 | 复制粘贴时把 id 写错 |
| ④ | 订单那格不看 deleted_at | 忘了回收站也是「关联不成立」 |
| ⑤ | 手抄一份 _del 后缀判据 | 「就这么一行，懒得 import」 |
| ⑥ | 服务层直接抛 HTTPException | 忘了 AI / 种子脚本也走这条路 |
| ⑦ | 文案里不再点名是哪个字段 | 图省事只印一个 id |
| ⑧ | SQL 里又把没挂车的行过滤掉 | 改前那一刀回来了 |
| ⑨ | 孤儿那一桶不再计数 | 只算钱、不数笔数 |
| ⑩ | 逐车那格改吃窗口全部开销 | 「顺手把三块合成一块」 |
| ⑪ | 返回体少一格新字段 | 加了字段忘了放进返回体 |
| ⑫ | 对账那一格不再等于三块相加 | 恒等式被改坏 |
| ⑬ | 动态说明行改成没有金额的套话 | 「说明嘛，写一句就行了」 |
| ⑭ | 动态说明行里加星号 | 抄了别处的 markdown 写法 |
| ⑮ | 静态口径那条被改成动态说明的措辞 | 「两句话一样，统一一下」 |
| ⑯ | response_model 里少声明一格 | 改了返回体没改 schema |
| ⑰ | 返回体多加一个没声明的键 | 调试字段忘了删 |
| ⑱ | 单测里少一支 | 「测试太啰嗦」 |
| ⑲ | 单测里的 400 断言放宽成不是 200 | 断言越写越松 |
| ⑳ | 单测里两张表对账的恒等式被删 | 把最贵的那条断言删了 |
| ㉑ | 单测里说明行的认法被放宽 | 恰好一条变成至少一条 |
| ㉒ | ValueError 不再被转成 400 | 改成 except Exception |
| ㉓ | expenses 三个关联列补 ForeignKey | 「数据库层拦一下更保险」 |
| ㉔ | 报表层开始写库 | 顺手在报表里改个状态 |
| ㉕ | 安卓 DTO 不再解析 notes | 后端加了字段、客户端没接 |

⚠️ 与仓库里其它 _reverse_verify_*.py 同一套纪律：按字节备份 / 还原、跑完逐文件核对哈希、
全程不碰 git checkout --（那会在真有改动时抹掉工作）。注入只落在**本单改过的文件**与两个
当时干净的文件（api/v1/expenses.py、安卓 Dtos.kt）上；跑之前先确认这两个文件没有被别的会话改。

用法：python _tools/finance/_reverse_verify_expense_links.py
      python _tools/finance/_reverse_verify_expense_links.py --list
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
CHECK = ROOT / "_tools/finance/_check_expense_links.py"

ACC = "backend/app/services/accounting_service.py"
VC = "backend/app/services/reports/vehicle_cost_query.py"
SCH = "backend/app/schemas/reports.py"
API = "backend/app/api/v1/expenses.py"
MODEL = "backend/app/models/expense.py"
TEST = "backend/tests/test_expense_links.py"
DTO = "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"

NOTE_HEAD = (
    "            f\"本窗口还有 {unlinked['count'] + orphan['count']} 笔没挂到任何一台车上的开销：\"\n"
    "            f\"未挂车的 {unlinked['count']} 笔共 {money_text(unlinked['total'])} 元、\"\n"
    "            f\"挂到查不到车辆的 {orphan['count']} 笔共 {money_text(orphan['total'])} 元。\"\n"
    "            f\"窗口内全部开销 {money_text(expense_window_total)} 元 ＝ 上面各车开销合计 \"\n"
    "            f\"{money_text(expense_total_all)} 元 ＋ 这 {money_text(off_vehicle_total)} 元；\"\n"
)

#: (说明, 文件, 原文, 替换成, 期望出现在失败清单里的标签片段, 命中次数)
CASES: list[tuple[str, str, str, str, str, int | str]] = [
    (
        "① 守卫从唯一写入闸门里被摘掉（先落库、再指望报表兜）",
        ACC,
        "    _require_expense_links(db, body)\n",
        "",
        "1-2 守卫挂在唯一写入闸门", 1,
    ),
    (
        "② 司机那格不再看账号是否还在用（停用 / 已删账号照样挂）",
        ACC,
        '        if not bool(getattr(driver, "is_active", True)):\n',
        "        if False:\n",
        "1-3 司机三态都拦", 1,
    ),
    (
        "③ 车辆那格查的不是那一辆车（挂到不存在的车照样落库）",
        ACC,
        "        vehicle = db.get(Vehicle, int(body.vehicle_id))\n",
        "        vehicle = db.get(Vehicle, 0)\n",
        "1-4 车辆两态都拦", 1,
    ),
    (
        "④ 订单那格不看回收站（回收站里的单照样挂）",
        ACC,
        '        if getattr(order, "deleted_at", None) is not None:\n',
        "        if False:\n",
        "1-5 订单两态都拦", 1,
    ),
    (
        "⑤ 手抄一份 _del 后缀判据（删账号的判据变成两份）",
        ACC,
        "        if has_del_suffix(driver.id, driver.phone, driver.username):\n",
        '        if str(driver.phone or "").endswith("_del"):\n',
        "1-6 删除态用的是唯一实现", 1,
    ),
    (
        "⑥ 服务层直接抛 HTTPException（AI 与种子脚本那两条路变成 500）",
        ACC,
        '            raise ValueError(\n                f"司机不存在',
        '            raise HTTPException(\n                f"司机不存在',
        "1-7 失败一律 ValueError", 1,
    ),
    (
        "⑦ 文案里不再点名是哪个字段（用户拿着 400 不知道改哪一格）",
        ACC,
        'f"司机不存在（driver_id={body.driver_id}）：请在司机管理里选一位在用的司机，"',
        'f"司机不存在（{body.driver_id}）：请在司机管理里选一位在用的司机，"',
        "1-8 六条文案都点名", 1,
    ),
    (
        "⑧ SQL 里又把没挂车的行过滤掉（改前那一刀回来了）",
        VC,
        "        .where(Expense.exp_date >= start, Expense.exp_date <= end)\n",
        "        .where(Expense.exp_date >= start, Expense.exp_date <= end, Expense.vehicle_id.isnot(None))\n",
        "2-3 分桶不再把没挂车", 1,
    ),
    (
        "⑨ 孤儿那一桶不再计数（另有 N 笔里的 N 丢了）",
        VC,
        '            orphan["count"] += int(count or 0)\n',
        "",
        "2-4 三块都各自计数与求和", 1,
    ),
    (
        "⑩ 逐车那一格改吃窗口全部开销（expense_total 语义被改）",
        VC,
        '        "expense_total": expense_total_all,\n',
        '        "expense_total": expense_window_total,\n',
        "2-5 逐车只吃挂到真实车辆", 1,
    ),
    (
        "⑪ 返回体里少一格新字段（孤儿笔数没有名字）",
        VC,
        '        "orphan_expense_count": int(orphan["count"]),\n',
        "",
        "2-6 六个新字段都在返回体里", 1,
    ),
    (
        "⑫ 对账那一格不再等于三块相加（又回到只算挂车的）",
        VC,
        "    expense_window_total = expense_total_all + off_vehicle_total\n",
        "    expense_window_total = expense_total_all\n",
        "2-7 expense_window_total", 1,
    ),
    (
        "⑬ 动态说明行改成一句没有金额的套话（用户核对不上那两笔钱）",
        VC,
        NOTE_HEAD,
        '            "另有未挂车的开销，请自行核对。"\n',
        "2-9 动态说明行含笔数与金额", 1,
    ),
    (
        "⑭ 动态说明行里冒出 markdown 星号（手机上原样显示两个星号）",
        VC,
        '            f"未挂车的 {unlinked[\'count\']} 笔共 {money_text(unlinked[\'total\'])} 元、\"\n',
        '            f"**未挂车**的 {unlinked[\'count\']} 笔共 {money_text(unlinked[\'total\'])} 元、\"\n',
        "2-10 动态说明行没有 markdown 星号", 1,
    ),
    (
        "⑮ 静态口径那条被改成动态说明的措辞（单测恰好一条会失效）",
        VC,
        "；没挂车的开销进不了本表",
        "；未挂车的开销进不了本表",
        "2-11 _NOTES 静态那几条原文没被改写", 1,
    ),
    (
        "⑯ response_model 里少声明一格（接口把它静默丢掉）",
        SCH,
        "    unlinked_expense_count: int = 0\n",
        "",
        "3-1 VehicleCostReportOut 声明了六个新字段", 1,
    ),
    (
        "⑰ 返回体里多加一个 schema 没声明的键（FastAPI 静默丢掉）",
        VC,
        '        "expense_window_count": int(expenses["window_count"]),\n',
        '        "expense_window_count": int(expenses["window_count"]),\n'
        '        "orphan_total_debug": off_vehicle_total,\n',
        "3-2 返回体的每个键都在 response_model", 1,
    ),
    (
        "⑱ 单测里少一支（两张表对账那条被改名 / 删掉）",
        TEST,
        "def test_同一个窗口两张表能对上(",
        "def _retired_同一个窗口两张表能对上(",
        "4-1 五个行为各一支", 1,
    ),
    (
        "⑲ 单测里的 400 断言放宽成不是 200（等于没断言状态码）",
        TEST,
        "assert r.status_code == 400",
        "assert r.status_code != 200",
        "4-2 单测钉着 400", "all",
    ),
    (
        "⑳ 单测里两张表对账的恒等式被删（口径对不上也没人发现）",
        TEST,
        '    assert _dec(vc, "expense_window_total") == _dec(pf, "operating_expense_total") + _dec(pf, "tax_total")\n',
        "",
        "4-3 单测钉着三块相加与两张表对账的恒等式", 1,
    ),
    (
        "㉑ 单测里说明行的认法被放宽（漏成两条也能过）",
        TEST,
        '    assert len(hit) == 1, "要有一行说明被漏掉的钱（笔数 + 金额）：" + str(notes)\n',
        "    assert len(hit) >= 1\n",
        "4-4 单测钉着", 1,
    ),
    (
        "㉒ 服务层抛的 ValueError 不再被转成 400（用户看到 500）",
        API,
        "    except ValueError as ex:\n",
        "    except Exception as ex:\n",
        "5-1 api/v1/expenses.py 没有第二份校验", 1,
    ),
    (
        "㉓ expenses 的关联列补上 ForeignKey（既有孤儿行会让迁移 / 写入直接失败）",
        MODEL,
        "    driver_id: Mapped[int | None] = mapped_column(nullable=True, index=True)\n",
        '    driver_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)\n',
        "5-2 expenses 表没有加 ForeignKey", 1,
    ),
    (
        "㉔ 报表层开始写库（只读边界被打破）",
        VC,
        "    expenses = _expense_buckets(db, start, end, {int(v.id) for v in vehicles})\n",
        "    db.flush()\n    expenses = _expense_buckets(db, start, end, {int(v.id) for v in vehicles})\n",
        "5-3 报告层仍然只读", 1,
    ),
    (
        "㉕ 安卓 DTO 不再解析 notes（说明行到不了用户眼前）",
        DTO,
        '    @SerialName("per_vehicle") val perVehicle: List<VehicleCostItemDto> = emptyList(),\n'
        '    @SerialName("notes") val notes: List<String> = emptyList(),\n',
        '    @SerialName("per_vehicle") val perVehicle: List<VehicleCostItemDto> = emptyList(),\n',
        "5-4 安卓的车辆成本 DTO 仍带 notes", 1,
    ),
]


class Sandbox:
    """按字节记账的注入台：每条注入都从最初那份字节重来，末尾逐字节还原并读回校验。"""

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
            print("❌ 前提不成立：判据本来就是红的，先把它修绿再做反验。");
            print("\n".join(out.splitlines()[-12:]))
            return 1
        green = [ln for ln in out.splitlines() if ln.startswith("✅")]
        print("前提：判据当前是绿的 —— " + (green[-1] if green else "（没有读到汇总行）"));
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
