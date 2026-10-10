# -*- coding: utf-8 -*-
"""BUG-0035（台账 TA-11 / TA-03）反向验证：把修复逐条弄坏，判据必须变红；末尾逐字节还原。

每一条注入都选在**判据真的会看的地方**，分三组覆盖整条链路：

| 组 | 注入 | 想证明的那条判据不是摆设 |
|---|---|---|
| 后端 | 去掉 403 门 / 回收站里套上 is_active / 取 is_deleted=False / 去掉删除时间倒序 | 参数语义与"只列已删"是活的 |
| App 取数 | 取数改回只查在售 / 去掉切档核对 | "恢复真的被调到、竞态真的被挡住"不是靠嘴说 |
| 界面 | 那一排整个删掉 / 挪到搜索框下面 / 文案退回旧位置 | "入口在列表顶端且文案与实现同源"两条都能红 |

## 两条实现上的注意

① **换行**：这几个 Kotlin 文件是 CRLF，而注入锚点是"整行"（末尾带 `\n`）。
   所以先把内容归一成 LF 再匹配 —— 反正注入只活在副本生命周期内，末尾按**原始字节**还原。
② 「挪到搜索框下面」是**两处**改动（从顶上删掉 + 贴到搜索框之后），单独一条注入实现。
"""
import hashlib
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools/qa/_check_product_recycle_bin.py"

API = "backend/app/api/v1/products.py"
SCREEN = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductsScreen.kt"
VM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductsViewModel.kt"
REPO = "android/app/src/main/java/com/tapmoay/sorders/data/repo/AppRepository.kt"
FORM = "android/app/src/main/java/com/tapmoay/sorders/ui/dispatcher/ProductFormScreen.kt"

GATE = (
    "    if (deleted_only or include_deleted) and not role_has_permission(rk, Permission.PRODUCT_MANAGE):\n"
    "        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=\"无权查看回收站\")\n"
)
BIN_WHERE = "            .where(Product.is_deleted.is_(True))\n"
BIN_ORDER = "            .order_by(Product.deleted_at.desc(), Product.id.desc())\n"
PICKER = (
    "            SegmentedPicker(\n"
    "                labels = listOf(\"在用\", \"回收站\"),\n"
    "                selected = if (vm.recycleBin) 1 else 0,\n"
    "                onSelect = { vm.switchRecycleBin(it == 1) },\n"
    "                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),\n"
    "            )\n"
)
SEARCH_TAIL = (
    "                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),\n"
    "            )\n"
)
BIN_GUARD = "                if (bin == recycleBin) binItems = list\n"
WHERE_NEW = "最上面那一排的「回收站」"
WHERE_OLD = "列表顶端的「回收站」"

#: (名字, 文件, [(锚点, 换成)], 是否允许锚点出现多次——多次时全部替换)
MUTATIONS = [
    ("后端①：去掉「只有能恢复的人能看回收站」那道 403 门", API, [(GATE, "")], False),
    ("后端②：回收站分支顺手套上 is_active（删除会强制下架 ⇒ 回收站恒空）", API,
     [(BIN_WHERE, BIN_WHERE + "            .where(Product.is_active.is_(True))\n")], False),
    ("后端③：回收站取的是 is_deleted=False（只看活着的）", API,
     [(BIN_WHERE, "            .where(Product.is_deleted.is_(False))\n")], False),
    ("后端④：回收站不再按删除时间倒序（刚删的不在最上面）", API, [(BIN_ORDER, "")], False),
    ("App①：取数改回只查在售（deletedOnly 传 false）", REPO,
     [("api.productApi.listProducts(deletedOnly = true)", "api.productApi.listProducts()")], False),
    ("App②：去掉切档核对（异步回来会把回收站结果画成在用列表）", VM,
     [(BIN_GUARD, "                binItems = list\n")], False),
    ("界面①：那一排整个删掉（回收站入口又没了）", SCREEN, [(PICKER, "")], False),
    ("界面②：那一排挪到搜索框下面（弹窗承诺的是列表顶端）", SCREEN,
     [(PICKER, ""), (SEARCH_TAIL, SEARCH_TAIL + PICKER)], False),
    ("界面③：文案退回旧位置（说 A 做 B）", FORM, [(WHERE_NEW, WHERE_OLD)], True),
]


def run_check():
    p = subprocess.run([sys.executable, "-X", "utf8", str(CHECK)], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def apply_and_run(rel: str, subs, replace_all: bool):
    """注入 → 跑判据 → 按**原始字节**还原。返回 (退出码, 错误说明)。"""
    src = ROOT / rel
    original = src.read_bytes()
    before_sha = hashlib.sha256(original).hexdigest()
    # 归一成 LF 再匹配（CRLF 的整行锚点否则一条都匹配不上）
    text = original.decode("utf-8").replace("\r\n", "\n")
    for old, new in subs:
        n = text.count(old)
        if n == 0 or (n != 1 and not replace_all):
            return None, "锚点 %r 出现 %d 次（应为 1）" % (old[:40], n)
        text = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    src.write_bytes(text.encode("utf-8"))
    try:
        code, _ = run_check()
    finally:
        src.write_bytes(original)
    if hashlib.sha256(src.read_bytes()).hexdigest() != before_sha:
        return None, "还原后 sha256 不一致"
    return code, None


red = 0
problems = []
for name, rel, subs, replace_all in MUTATIONS:
    code, why = apply_and_run(rel, subs, replace_all)
    if why is not None:
        problems.append("%s：%s" % (name, why))
        continue
    if code == 0:
        problems.append("%s：判据**没有**变红" % name)
    else:
        red += 1
        print("  ✔ %s → 判据变红" % name)

print()
print("注入 %d 条，变红 %d 条" % (len(MUTATIONS), red))
print("被碰文件：" + "、".join(sorted({rel for _, rel, _, _ in MUTATIONS})))
if problems:
    print("❌ 有问题：")
    for p in problems:
        print("   -", p)
    sys.exit(1)
if red != len(MUTATIONS):
    print("❌ 没做到「每条注入都红」")
    sys.exit(1)
print("✅ %d/%d 都红了，且每个被碰文件都逐字节还原。" % (red, len(MUTATIONS)))
