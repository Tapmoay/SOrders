"""联系人备注（L-10，CHG-0048）静态判据：一行自由文本，**只有自己看得见**，选人时带进地点备注。

## 用户原话（2026-10-06）
「还有我们那个叫什么联系人，他也是要**有备注**的哈，我们联系人可以备注的；以及我们那个**地点**
的时候，如果选择对应的联系人，**对应的备注也会写上去**的，当然，**这个备注是可以改的**……
而此备注**只有自己才能看见**」

## 机制（这条链路上每一段各由谁负责）
| 段 | 在哪 | 怎么规定的 |
| --- | --- | --- |
| 存哪 | backend/app/models/shipper.py | shipper_contacts 加一列 remark，与 shipper_locations.remark **逐字同形**（String(256) / default ""） |
| 建列 | backend/app/migrations/023_shipper_contact_remark.py | NOT NULL DEFAULT ''；⛔ 不回填老数据、⛔ 不建索引 |
| 入参 | backend/app/schemas/shipper.py | ContactCreate.remark（默认空串）/ ContactUpdate.remark（None = 不改）/ ContactOut.remark（"" = 没写） |
| 写 | backend/app/api/v1/shipper.py | POST（upsert）只在这次真给了才覆盖；PATCH 空串 = 明确清掉；两侧都 strip |
| 带出 | android/.../AddressViewModel.kt::applyPickedContact | 选联系人时把备注带进**地点备注**，只在地点备注还空着时填 |
| 显示 | android/.../AddressScreen.kt | 联系人抽屉里一格「备注」；联系人卡上画一行（没写就整行不画） |
| 只有自己看得见 | 端点全部按 current.id 隔离；⛔ 不进共享地点库（places 上没有这一列）、⛔ 不进订单出参 |

## ⛔ 这条判据证不了什么
1. **不证真机上的观感**：抽屉里那一格长什么样、卡上那一行挤不挤、带出之后用户改得顺不顺手 ——
   静态判据只能证明「代码是这么写的」，摸不到手感。
2. **不证服务端真的只回给主人**：这里只证端点按 current.id 过滤、ContactOut 的引用面收敛在
   联系人端点上；**行为证据**在 backend/tests/test_contact_remark.py（另一个账号 404）。
3. **不证「跟随联系人」不存在**：这里只证没有**无条件**的 locRemark = c.remark；用户手动把地点
   备注改成别的、之后再选同一个联系人会不会又盖回去，属于运行时行为，得靠人点。
4. **不证 AI 不会写备注**：AiWriteDataSource 现在压根不带 remark 这个键（POST 空串 = 没提、
   PATCH null = 不改），所以「AI 改联系人会不会顺手清掉备注」这条要新增 AI 字段时**重新看一遍**，
   本判据不会因为 AI 侧改动而变红。

R4-BOUNDARY-JUSTIFICATION: 这 40 条里有三类是**边界解决不了**、只能靠静态判据钉住的：
①「只有自己看得见」——它不是一个函数的返回值，而是**整张表的可见面**（哪些文件引用 ContactOut、
places 表上有没有这一列），代码边界（类型/校验/事务）管不到；②「⛔ 不回填 / ⛔ 不建索引 /
⛔ 不建第二份自愈」——是**不做什么**的纪律，写错了不会有任何测试变红（老数据被猜着补上、多一份
自愈同时生效都表现为"正常"），只有把源码逐字读一遍才看得见；③客户端「整份回传」的**沉默清空**：
不回填 / 少传一项，界面上完全看不出来（改个称呼顺手把备注清掉），后端 200、测试全绿。
反向破坏用例见 _tools/qa/_reverse_verify_contact_remark.py（19 条注入，逐条指明本文件哪条该红）。

## 判据（40 条，五组：存储 / schema / 端点 / 迁移 / 客户端 + 隐私）
用法：python _tools/qa/_check_contact_remark.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
BACK = ROOT / "backend" / "app"
MODELS = BACK / "models" / "shipper.py"
SCHEMAS = BACK / "schemas" / "shipper.py"
API = BACK / "api" / "v1" / "shipper.py"
BOOT = BACK / "core" / "schema_bootstrap.py"
MIGDIR = BACK / "migrations"
MIG = MIGDIR / "023_shipper_contact_remark.py"
PLACE_MODEL = BACK / "models" / "place.py"
PLACE_SVC = BACK / "services" / "place_service.py"

AND = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
DTOS = AND / "data" / "remote" / "dto" / "Dtos.kt"
VM = AND / "ui" / "shipper" / "AddressViewModel.kt"
SCREEN = AND / "ui" / "shipper" / "AddressScreen.kt"

#: 两处**必须逐字相同**的那一行（联系人备注 / 地点备注是同一件东西）。
REMARK_COL = 'remark: Mapped[str] = mapped_column(String(256), default="")'
#: 客户端保存联系人时**唯一**该用的那一句（新建与编辑各一次）。
VM_TRIM = "remark = contactRemark.trim(),"
#: 「带进地点备注」的那一行（有守卫的版本）。
VM_PICK = "if (locRemark.isBlank() && c.remark.isNotBlank()) locRemark = c.remark"


class Checker:
    def __init__(self) -> None:
        self.total = 0
        self.fails: list[str] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> bool:
        self.total += 1
        if not cond:
            self.fails.append("  [FAIL] " + label + (" —— " + detail if detail else ""))
        return bool(cond)

    def present(self, label: str, text: str, pattern: str, where: str = "") -> bool:
        hit = re.search(pattern, text, re.M) is not None
        return self.ok(label, hit, "没找到 " + pattern + ("（在 " + where + "）" if where else ""))

    def absent(self, label: str, text: str, pattern: str, where: str = "") -> bool:
        hit = re.search(pattern, text, re.M) is not None
        return self.ok(label, not hit, "却找到了 " + pattern + ("（在 " + where + "）" if where else ""))


def read(p: Path) -> str:
    if not p.exists():
        print("❌ 找不到文件：" + str(p))
        raise SystemExit(2)
    return p.read_text(encoding="utf-8", errors="replace")


def code_only(text: str) -> str:
    """剥掉 /* */ 与 // 注释（**保留行号**：注释里的字不算证据）。

    ⚠️ 只给 Kotlin / 只想扔块注释时用；Python 的 # 注释不会被它剥掉，
       所以 Python 侧还要 py_code_only 再过一道。
    """
    def _blank(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    out = re.sub(r"/\*.*?\*/", _blank, text, flags=re.S)
    return "\n".join(ln[: ln.find("//")] if "//" in ln else ln for ln in out.split("\n"))


def py_code_only(text: str) -> str:
    """把 Python 的整行 # 注释挖空（保留行数）。"""
    return "\n".join("" if ln.strip().startswith("#") else ln for ln in text.split("\n"))


def region(text: str, start: str, stop: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(stop, i + len(start))
    return text[i:j] if j > 0 else text[i:]


def cls_region(text: str, name: str) -> str:
    """Python 类的整段（到下一个顶层 class 为止）。"""
    key = "class " + name + "("
    i = text.find(key)
    if i < 0:
        return ""
    m = re.search(r"\nclass ", text[i:])
    return text[i : i + m.start()] if m else text[i:]


def func_region(text: str, name: str) -> str:
    """后端端点函数的整段（到下一个 @router. 装饰器为止）。"""
    key = "def " + name + "("
    i = text.find(key)
    if i < 0:
        return ""
    m = re.search(r"\n@router\.", text[i:])
    return text[i : i + m.start()] if m else text[i:]


def kt_func_region(text: str, name: str) -> str:
    """Kotlin 顶层成员函数的整段（到下一个 4 空格缩进的成员为止）。"""
    key = "fun " + name + "("
    i = text.find(key)
    if i < 0:
        return ""
    m = re.search(r"\n    (?:/\*\*|@|fun |private fun |internal fun |suspend fun )", text[i:])
    return text[i : i + m.start()] if m else text[i:]


def kt_region(text: str, name: str) -> str:
    """Kotlin data class 的整段（到下一个 @Serializable / data class 为止）。"""
    key = "data class " + name + "("
    i = text.find(key)
    if i < 0:
        return ""
    m = re.search(r"\n(?:@Serializable\n)?data class ", text[i + 1 :])
    return text[i : i + 1 + m.start()] if m else text[i:]


def scan(root: Path, needle: str, skip: tuple[str, ...]) -> list[str]:
    """哪些 .py 文件里出现过这个标识符（跳过 __pycache__ / migrations / tests）。"""
    hits: list[str] = []
    for f in sorted(root.rglob("*.py")):
        if any(part in skip for part in f.parts):
            continue
        if needle in f.read_text(encoding="utf-8", errors="replace"):
            hits.append(f.relative_to(ROOT).as_posix())
    return hits


def main() -> int:
    c = Checker()
    models = read(MODELS)
    schemas = read(SCHEMAS)
    api = read(API)
    boot = read(BOOT)
    mig = read(MIG)
    dtos = read(DTOS)
    vm = read(VM)
    screen = read(SCREEN)

    # ---------- 一、存储 ----------
    contact_cls = cls_region(models, "ShipperContact")
    loc_cls = cls_region(models, "ShipperLocation")
    c.present("[存储] ShipperContact 有 remark 这一列（String(256) / default \"\"）",
              contact_cls, re.escape(REMARK_COL), "ShipperContact")
    c.ok("[存储] 与 shipper_locations.remark 逐字同形（同一个 String(256) / default \"\"）",
         REMARK_COL in loc_cls and contact_cls.count(REMARK_COL) == 1 and loc_cls.count(REMARK_COL) == 1,
         "两处写法不一致（改一处必须改另一处，否则带过去会被截断）")
    others = re.findall(r"^\s+remark\w*\s*:\s*Mapped", contact_cls, re.M)
    c.ok("[存储] ⛔ 联系人上没有第二个备注列（remark_* 之类）", len(others) == 1,
         "ShipperContact 里有 " + str(len(others)) + " 个 remark 列")

    # ---------- 二、schema ----------
    cc = cls_region(schemas, "ContactCreate")
    cu = cls_region(schemas, "ContactUpdate")
    co = cls_region(schemas, "ContactOut")
    lc = cls_region(schemas, "LocationCreate")
    c.ok("[schema] ContactCreate 的 SHOWABLE_FIELDS 含 remark（看得见的字由它兜住）",
         'SHOWABLE_FIELDS = ("display_name", "remark")' in cc, "ContactCreate 里没有这一行")
    c.present("[schema] ContactCreate.remark = Field(default=\"\", max_length=256)", cc,
              r'remark: str = Field\(default="", max_length=256\)', "ContactCreate")
    cc_len = re.search(r'remark: str = Field\(default="", max_length=(\d+)\)', cc)
    lc_len = re.search(r'remark: str = Field\(default="", max_length=(\d+)\)', lc)
    c.ok("[schema] ContactCreate.remark 与 LocationCreate.remark 同一个长度（256）",
         bool(cc_len) and bool(lc_len) and cc_len.group(1) == lc_len.group(1) == "256",
         "联系人 " + (cc_len.group(1) if cc_len else "?") + " / 地点 " + (lc_len.group(1) if lc_len else "?"))
    c.ok("[schema] ContactUpdate 的 SHOWABLE_FIELDS 含 remark",
         'SHOWABLE_FIELDS = ("display_name", "remark")' in cu, "ContactUpdate 里没有这一行")
    c.present("[schema] ContactUpdate.remark 可空（None = 不改）", cu,
              r"remark: str \| None = Field\(None, max_length=256\)", "ContactUpdate")
    c.present("[schema] ContactOut 带回 remark（\"\" = 没写，不是 null）", co,
              r'^\s+remark: str = ""$', "ContactOut")

    # ---------- 三、端点 ----------
    post = func_region(api, "upsert_contact")
    patch = func_region(api, "update_contact")
    c.present("[端点] POST 把备注 strip 一遍", post,
              r'remark = \(body\.remark or ""\)\.strip\(\)', "upsert_contact")
    c.present("[端点] POST 只在这次真的给了备注时才覆盖（空串 = 这次没提）", post,
              r"^\s+if remark:$", "upsert_contact")
    c.ok("[端点] ⛔ 全文件只有这一处 row.remark = remark（没有第二条无条件覆盖）",
         api.count("row.remark = remark") == 1 and "row.remark = remark" in post,
         "出现了 " + str(api.count("row.remark = remark")) + " 次")
    c.present("[端点] POST 新建那行把备注写进去", post, r"^\s+remark=remark,$", "upsert_contact")
    c.present("[端点] PATCH：None = 不改（if body.remark is not None）", patch,
              r"^\s+if body\.remark is not None:$", "update_contact")
    c.present("[端点] PATCH：strip 之后再落库", patch,
              r"^\s+c\.remark = body\.remark\.strip\(\)$", "update_contact")
    c.absent("[端点] ⛔ PATCH 里没有无条件的 c.remark = body.remark", api,
             r"^\s+c\.remark = body\.remark$", "api/v1/shipper.py")
    listing = func_region(api, "list_contacts")
    c.ok("[端点] 列表端点按 current.id 隔离",
         "ShipperContact.shipper_id == current.id" in listing
         and "ShipperContact.is_deleted.is_(False)" in listing, "list_contacts 少了归属过滤")
    missed = [fn for fn in ("update_contact", "delete_contact", "restore_contact")
              if "shipper_id != current.id" not in func_region(api, fn)
              or "未找到对应记录" not in func_region(api, fn)]
    c.ok("[端点] 改 / 删 / 恢复都判归属（拿别人的 id → 404）", not missed,
         "这几处没判归属：" + "、".join(missed))

    # ---------- 四、迁移 ----------
    all_versions: list[tuple[int, str]] = []
    for f in sorted(MIGDIR.glob("*.py")):
        t = f.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"^VERSION = (\d+)$", t, re.M):
            all_versions.append((int(m.group(1)), f.name))
    top = max(v for v, _ in all_versions) if all_versions else -1
    c.ok("[迁移] 023 存在且 VERSION = 23（全目录唯一最大）",
         MIG.exists() and top == 23 and sum(1 for v, _ in all_versions if v == 23) == 1,
         "最大版本号是 " + str(top) + "（023 是 " + str(sum(1 for v, _ in all_versions if v == 23)) + " 份）")
    c.ok("[迁移] NAME 是 shipper_contact_remark（与文件名同形）",
         'NAME = "shipper_contact_remark"' in mig and MIG.name == "023_shipper_contact_remark.py",
         "NAME / 文件名不一致")
    model_len = re.search(r'remark: Mapped\[str\] = mapped_column\(String\((\d+)\), default=""\)', contact_cls)
    c.ok("[迁移] 迁移 023 的列定义与模型逐字同形（VARCHAR(256) NOT NULL DEFAULT ''）",
         bool(model_len) and ("DDL = \"remark VARCHAR(256) NOT NULL DEFAULT ''\"" in mig)
         and model_len.group(1) == "256",
         "迁移里的 DDL 与模型 String(256) 对不上")
    c.ok("[迁移] 先判列在不在：已经加过就安静通过（可重跑）",
         "if COLUMN not in have:" in mig, "没有 if COLUMN not in have: 这道判")
    c.ok("[迁移] 表还不存在时返回（全新库由 create_all 建）",
         "if have is None:" in mig, "没有 if have is None: 这道判")
    c.ok("[迁移] ⛔ 不回填老数据（没有 UPDATE 语句）",
         re.search(r"\bUPDATE\b", py_code_only(mig)) is None, "迁移里有 UPDATE")
    c.ok("[迁移] ⛔ 不建索引（备注不分栏）",
         re.search(r"CREATE\s+(UNIQUE\s+)?INDEX", py_code_only(mig)) is None, "迁移里建了索引")
    boot_code = code_only(boot)
    boot_lines = [ln for ln in boot_code.split("\n") if "shipper_contacts" in ln and "remark" in ln]
    c.ok("[迁移] ⛔ schema_bootstrap 里没有第二份自愈",
         not boot_lines and 'get_columns("shipper_contacts")' not in boot_code,
         "schema_bootstrap 里又写了一份补列：" + (boot_lines[0].strip() if boot_lines else "get_columns(shipper_contacts)"))

    # ---------- 五、客户端 ----------
    cdto = kt_region(dtos, "ContactDto")
    cu_req = kt_region(dtos, "ContactUpdateRequest")
    cc_req = kt_region(dtos, "ContactCreateRequest")
    c.present("[DTO] ContactDto.remark 是非空 String（\"\" = 没写；出参不许出 null）", cdto,
              r'^\s+val remark: String = "",$', "ContactDto")
    c.present("[DTO] ContactUpdateRequest.remark 可空（null = 不动；\"\" = 清掉）", cu_req,
              r"^\s+val remark: String\? = null,$", "ContactUpdateRequest")
    c.present("[DTO] ContactCreateRequest.remark 有默认值（\"\" = 没写）", cc_req,
              r'^\s+val remark: String = "",$', "ContactCreateRequest")
    c.ok("[VM] contactRemark 草稿态在（\"\" = 没写）", 'var contactRemark by mutableStateOf("")' in vm,
         "AddressViewModel 里没有 contactRemark 草稿态")
    open_dlg = kt_func_region(vm, "openContactDialog")
    c.present("[VM] 打开编辑时把备注回填（整份回传，不回填 = 改个称呼顺手清掉）", open_dlg,
              r'contactRemark = c\?\.remark \?: ""', "openContactDialog")
    save = kt_func_region(vm, "saveContact")
    i_create = save.find("ContactCreateRequest(")
    i_update = save.find("ContactUpdateRequest(")
    c.ok("[VM] 新建那条路带上备注",
         i_create >= 0 and i_update > i_create and VM_TRIM in save[i_create:i_update],
         "ContactCreateRequest 那一份没带 remark")
    c.ok("[VM] 编辑那条路带上备注", i_update >= 0 and VM_TRIM in save[i_update:],
         "ContactUpdateRequest 那一份没带 remark")
    pick = kt_func_region(vm, "applyPickedContact")
    c.ok("[VM] 选联系人时带出备注：只在地点备注还空着时带出", VM_PICK in pick,
         "applyPickedContact 里没有带出那一行（或守卫被去掉）")
    c.ok("[VM] ⛔ 没有无条件的 locRemark = c.remark（用户写的那行不许被盖）",
         re.search(r"^\s*locRemark = c\.remark\s*$", vm, re.M) is None
         and vm.count("locRemark = c.remark") == 1,
         "全文件出现 " + str(vm.count("locRemark = c.remark")) + " 次 locRemark = c.remark")
    at = screen.find("value = vm.contactRemark,")
    win = screen[max(0, at - 400) : at + 400]
    c.ok("[界面] 联系人抽屉里备注那一格绑在 vm.contactRemark 上（label = \"备注\"）",
         at >= 0 and 'label = "备注",' in win, "抽屉里找不到绑在 vm.contactRemark 上的「备注」那一格")
    c.ok("[界面] 抽屉备注那一格形状与地点表单一致（placeholder = \"选填\"）",
         at >= 0 and 'placeholder = "选填",' in win, "那一格没有 placeholder = 选填")
    card = region(screen, "private fun ContactCard(", "private fun LocationCard(")
    c.ok("[界面] 联系人卡上画着备注（没写就整行不画）",
         "if (c.remark.isNotBlank()) {" in card and "Text(c.remark," in card,
         "ContactCard 上没有画备注（或缺了 isNotBlank 的守卫）")

    # ---------- 六、只有自己看得见 ----------
    refs = scan(BACK, "ContactOut", ("__pycache__", "migrations", "tests"))
    c.ok("[隐私] ContactOut 只被联系人端点引用（派单侧 / 订单出参都拿不到它）",
         refs == ["backend/app/api/v1/shipper.py", "backend/app/schemas/shipper.py"],
         "引用面变成了：" + "、".join(refs))
    c.ok("[隐私] places 表与 place_service 里没有 remark（共享地点库不带它）",
         re.search(r"\bremark\b", code_only(read(PLACE_MODEL))) is None
         and re.search(r"\bremark\b", code_only(read(PLACE_SVC))) is None,
         "共享地点库里出现了 remark")

    if c.fails:
        print("\n".join(c.fails))
        print("❌ 共 " + str(c.total) + " 条，" + str(len(c.fails)) + " 条不成立")
        return 1
    print("✅ 联系人备注（L-10）静态判据：" + str(c.total) + " 条全过"
          "（存储 / schema / 端点 / 迁移 / DTO / VM / 界面 / 隐私）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
