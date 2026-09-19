"""红线：**软删（伪装删除）的行不许还能被"改"**。

## 为什么要有这一条（R11-F4，2026-09-19 审计）
"删除"在本项目是**打标记**（`SoftDeleteMixin`：`is_deleted=True` + `deleted_at`），
所以每一张这样的表都必须在**三个地方**同时尊重这个标记，少一个就出事：

| 地方 | 现状 |
|---|---|
| 列表/查询 | 有（`X.is_deleted.is_(False)`） |
| 删除/恢复 | 有（`DELETE` 查标记、`restore` 要求标记为真） |
| **改（PATCH/PUT/set-default）** | **漏了几处**——`PUT /freight-templates/{id}`、`PATCH /arrears-units/{id}`、`PATCH /price-rules/{id}`、`POST /shipper/addresses/{id}/set-default` |

漏了会怎样（这就是它为什么是缺陷，而不是"代码不好看"）：
- 接口**返回 200**，界面/AI 回一句「已完成」，而那条记录在**所有列表里都看不见**——
  用户以为改好了，回头在页面上找不到它，只能怀疑自己记错了；
- `price_rules` 更狠：它还会写一条**价格变动审计日志**（"旧价 → 新价"），
  而批发商看到的价格**一个字都没变**——审计追出来的是一条没发生过的调价；
- 地址的 `set-default` 会把"默认地址"落在看不见的行上：`delete_address` 特意
  `is_default = False` 防的就是这个，而 set-default 一句话就能设回去。

## 判据（清单**自己算**，不手写）
1. 从 `backend/app/models/*.py` 扫出**所有软删模型**（用了 `SoftDeleteMixin`，
   或自己声明了 `is_deleted` 列）——扫到的数量低于下限就报错（防"扫描空转"）；
2. 从 `backend/app/api/v1/*.py` 扫出所有**会改一行**的端点：
   `@router.patch` / `@router.put`，以及路径里带 `/{id}/set-default` 这类状态型 POST；
3. 逐个端点看它的函数体：只要它**按 URL 里的编号取出了软删模型的那一行**
   （`db.get(X, <路径参数>)`）——那就是"这个端点改的就是这一行"——就必须同时出现
   "想过了"的证据：`ensure_alive(`（统一入口）或 `is_deleted`。

   ⚠️ 判据必须锚在**路径参数**上，这是第一版太松被假缺陷打回来才收紧的：
   第一版只要求"函数体里出现过软删模型"，于是 `PATCH /order-products/{line_id}`
   被报成缺陷——它 `db.get(Product, body.product_id)` 只是**查一下参考商品**来抄成本快照，
   而且 `_check_product_ref()` 里已经 `if p.is_deleted: 400`。**假缺陷会让人开始无视红线**，
   所以口径收紧成"被这个 URL 直接寻址、且是软删模型的那一行"。
4. **`del_suffix` 的列宽必须等于模型里声明的宽度**（G4 的第二次加固）：
   软删要把唯一列改写成"原值 + `_del{id}`"，而**本机 SQLite 不校验 VARCHAR 长度**、
   生产 MySQL 会报 `Data too long` 并被翻成"填写的内容超出可保存范围"（用户只是点了删除）。
   所以每个 `x.col = del_suffix(x.col, x.id, N)` 的 `N` 都必须与模型里那一列的 `String(N)` 一致；
   模型改列宽时这条会立刻红（否则要等生产上有人删不掉记录才发现）。

用法：
    python _tools/qa/_check_soft_delete_guards.py            # 直接跑（_check_all.py 会带上它）
    python _tools/qa/_check_soft_delete_guards.py --list      # 只列扫到的端点与模型，不下结论
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "backend/app/models"
API = ROOT / "backend/app/api/v1"

# 扫到的数量下限（清单过期/正则失效时先喊，而不是安静地什么都不查）
MIN_MODELS = 6
MIN_ENDPOINTS = 8
MIN_PAIRS = 6

ROUTER = re.compile(r'@router\.(patch|put|post)\(\s*"([^"]*)"', re.M)
# ⚠️ **切块**要用"任意 router 装饰器"，不能用上面那个（只含 patch/put/post）：
#    用上面那个切，`PUT /{id}` 的块会一路吃到下一个 patch/put/post —— 中间夹着
#    `DELETE /{id}`（它当然写了 `is_deleted = True`），于是"守卫被拿掉"也照样被判成绿。
#    反向验证当场抓到了这一点（4 条注入里红线一条都没红）。
ANY_ROUTE = re.compile(r"@router\.\w+\(", re.M)


def soft_models() -> dict[str, str]:
    """{模型类名: 文件}——用了 SoftDeleteMixin 或自己声明了 is_deleted。"""
    out: dict[str, str] = {}
    for f in sorted(MODELS.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"^class\s+(\w+)\s*\(([^)]*)\)\s*:", src, re.M):
            name, bases = m.group(1), m.group(2)
            if "SoftDeleteMixin" in bases:
                out[name] = f.name
                continue
            # 基类列表里没有 mixin 的（如 Product 自己声明列）：看类体里有没有 is_deleted
            body_start = m.end()
            nxt = re.search(r"^class\s+\w+", src[body_start:], re.M)
            body = src[body_start : body_start + (nxt.start() if nxt else len(src) - body_start)]
            if re.search(r"^\s+is_deleted\s*:", body, re.M):
                out[name] = f.name
    return out


def handlers(src: str) -> list[tuple[int, str, str, str]]:
    """[(行号, 方法, 路径, 源码块)]——每个"会改一行"的端点。"""
    spans: list[tuple[int, str, str]] = []
    for m in ROUTER.finditer(src):
        method, path = m.group(1), m.group(2)
        # 会改一行的端点：patch/put 全部；post 只认"对某一条做二次动作"的形状。
        # ⚠️ 尾段要允许连字符（`set-default`）——第一版写成 `\w+$` 时它**整个被跳过**，
        #    而 `set-default` 恰好就是漏掉的那个洞（`delete_address` 特意把 is_default
        #    置 false 防的事，`set-default` 一句话就能做回去）。
        if method == "post" and not re.search(r"/\{[^}]+\}/[\w\-]+$", path):
            continue
        if method == "post" and not path.endswith(("set-default", "/driver", "/attach", "/restore", "/visibility")):
            continue
        spans.append((src[: m.start()].count("\n") + 1, method, path))
    out = []
    for i, (line, method, path) in enumerate(spans):
        start = src.splitlines(keepends=True)
        # 从装饰器那一行开始，切到**下一个 router 装饰器**（含 delete/get）或文件尾
        begin = sum(len(x) for x in start[: line - 1])
        nxt = ANY_ROUTE.search(src, begin + 1)
        end = nxt.start() if nxt else len(src)
        out.append((line, method, path, src[begin:end]))
    return out


def column_widths() -> dict[tuple[str, str], int]:
    """{(模型类名, 列名): 声明宽度}——**按类**取宽度，不按列名。

    ⚠️ 必须按类：`name` 这个列名在 `ArrearsUnit(128)` / `Customer(32)` / `Product(256)` 上都存在，
    只按列名匹配的话"传 128 给一个 String(32) 的列"照样算通过（第一版就是这样，等于没查）。
    """
    out: dict[tuple[str, str], int] = {}
    for f in sorted(MODELS.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        for cm in re.finditer(r"^class\s+(\w+)\s*\(", src, re.M):
            cls = cm.group(1)
            body_start = cm.end()
            nxt = re.search(r"^class\s+\w+", src[body_start:], re.M)
            body = src[body_start : body_start + (nxt.start() if nxt else len(src) - body_start)]
            for m in re.finditer(
                r"^\s*(\w+)\s*:\s*Mapped\[[^\]]*\]\s*=\s*mapped_column\(\s*String\((\d+)\)", body, re.M
            ):
                out[(cls, m.group(1))] = int(m.group(2))
    return out


def del_suffix_calls() -> list[tuple[str, int, str, str, int]]:
    """[(文件, 行号, 变量名, 列名, 传进去的宽度)]。"""
    out: list[tuple[str, int, str, str, int]] = []
    for f in sorted((ROOT / "backend/app").rglob("*.py")):
        if f.name == "soft_delete.py":
            continue
        src = f.read_text(encoding="utf-8")
        for i, line in enumerate(src.splitlines(), 1):
            m = re.search(r"(\w+)\.(\w+)\s*=\s*del_suffix\([^,]+,[^,]+,\s*(\d+)\)", line)
            if m:
                out.append(
                    (str(f.relative_to(ROOT)).replace("\\", "/"), i, m.group(1), m.group(2), int(m.group(3)))
                )
    return out


def row_class_of(src: str, line_no: int, var: str) -> str | None:
    """这一行所在函数里，`<var>` 是从哪个模型取出来的（`<var> = db.get(Class, ...)`）。"""
    lines = src.splitlines()
    # 向上找最近的一次赋值（同一函数内），最多回溯 200 行
    for i in range(line_no - 1, max(-1, line_no - 200), -1):
        m = re.search(rf"\b{re.escape(var)}\s*=\s*db\.get\(\s*(\w+)", lines[i])
        if m:
            return m.group(1)
        if re.match(r"^(def |@router)", lines[i]) and i != line_no - 1:
            return None
    return None


def main() -> int:
    listing = "--list" in sys.argv
    models = soft_models()
    print(f"软删模型 {len(models)} 个：{'、'.join(sorted(models))}")
    if len(models) < MIN_MODELS:
        print(f"❌ 只认出 {len(models)} 个软删模型（应 ≥{MIN_MODELS}）——判据在空转，停。")
        return 1

    pairs: list[tuple[str, int, str, str, str, bool]] = []
    for f in sorted(API.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        for line, method, path, block in handlers(src):
            params = re.findall(r"\{(\w+)\}", path)
            if not params:
                continue
            # 被这个 URL 直接寻址的那一行（按路径参数取行），且它属于软删模型
            for m in models:
                for p in params:
                    got = re.search(
                        rf"(\w+)\s*=\s*db\.get\(\s*{re.escape(m)}\s*,\s*{re.escape(p)}\b", block
                    )
                    if not got:
                        continue
                    var = got.group(1)
                    # "想过了"的证据必须**落在这个变量上**，三种写法都算：
                    #   · `ensure_alive(<var>, …)`（统一入口）
                    #   · `<var>.is_deleted`（直接比较）
                    #   · `getattr(<var>, "is_deleted", False)`（shipper.py 那三处就是这种）
                    # ⚠️ 不能只查"块里出现过 is_deleted"：同一段里往往还有**别的**用途——
                    #    `arrears` 的重名检查写着 `ArrearsUnit.is_deleted.is_(False)`（类属性），
                    #    于是"守卫被拿掉"照样被判成绿（反向验证当场抓到 2 条）。
                    thought = (
                        f"ensure_alive({var}," in block
                        or bool(re.search(rf"\b{re.escape(var)}\.is_deleted\b", block))
                        or bool(re.search(rf'getattr\(\s*{re.escape(var)}\s*,\s*"is_deleted"', block))
                    )
                    pairs.append((f.name, line, method.upper(), path, m, thought))

    print(f"扫到「会改一行 + 取过软删模型」的端点 {len(pairs)} 处：")
    for name, line, method, path, model, ok in pairs:
        print(f"  [{'OK' if ok else '!!'}] {name}:{line} {method} {path}  → {model}")
    if listing:
        return 0

    if len(pairs) < MIN_PAIRS:
        print(f"❌ 只扫到 {len(pairs)} 处（应 ≥{MIN_PAIRS}）——判据在空转，停。")
        return 1

    bad = [p for p in pairs if not p[5]]
    if bad:
        print("\n❌ 这些端点能改到**已经删除（在回收站里）**的行，而且返回 200：")
        for name, line, method, path, model, _ in bad:
            print(f"   - {name}:{line} {method} {path}（{model}）")
        print(
            "\n   修法：取到行之后立刻 `ensure_alive(row, \"<中文名>\", \"POST /xxx/{id}/restore\")`"
            "（app/services/soft_delete.py），它会给出一句能照着做的中文原因。"
        )
        return 1

    # ---- 判据 4：del_suffix 的宽度必须与**那一行所属模型**的列宽一致 ----
    widths = column_widths()
    calls = del_suffix_calls()
    print(f"\n`del_suffix` 调用点 {len(calls)} 处（软删要改写唯一列，宽度不对 = 生产 MySQL 删不掉）：")
    width_bad: list[str] = []
    for rel, line, var, col, w in calls:
        src = (ROOT / rel).read_text(encoding="utf-8")
        cls = row_class_of(src, line, var)
        declared = widths.get((cls or "", col))
        ok = declared == w
        print(
            f"  [{'OK' if ok else '!!'}] {rel}:{line} 变量 {var} → 模型 {cls}，列 {col}："
            f"传入 {w}，模型声明 {declared}"
        )
        if not ok:
            width_bad.append(
                f"{rel}:{line}（{cls}.{col}：传入 {w}，模型声明 {declared}）"
            )
    if len(calls) < 3:
        print(f"❌ 只扫到 {len(calls)} 处 `del_suffix` 调用（<3）——判据在空转，停。")
        return 1
    if width_bad:
        print("\n❌ 这些地方给 `del_suffix` 传的列宽与**那一行所属模型**不一致（生产 MySQL 会 'Data too long'）：")
        for b in width_bad:
            print("   - " + b)
        print("   修法：把宽度改成该模型里 `String(N)` 的 N（本机 SQLite 不校验长度，测不出来）。")
        return 1

    print("\n✅ 所有会改一行的端点都想过「这行是不是已经删了」，且 del_suffix 的列宽与模型一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
