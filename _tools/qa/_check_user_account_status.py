"""静态审计：BUG-0002 的三件事还立着吗（P1 名册号码 / P2 账户状态档 / P10 绑车候选）。

### 由来（2026-10-03 · `_tmp/E2E测试报告.md`）
真机 E2E 报告里这三条是同一类毛病 —— **后端知道的事，界面自己瞎猜**：

· P1 名册卡直接画 `u.phone`，于是软删账号那一行显示 `13923111638_del62`
  （`_del{id}` 后缀是「号已经释放回号池」的标记，是内部值，不是给人看的）；
· P2 账户管理只有一档列表，删过的旧账号混在正常账号里，找人只能一屏屏翻；
· P10 绑车时停用/已删的账号照样出现在司机候选里，选了他也排不了单。

### 这一块会怎么悄悄坏掉

| 坏法 | 结果 | 哪一条会红 |
| --- | --- | --- |
| 展示层自己 `replace` 掉后缀 | 绕开后端唯一口径；「恢复时撞号」那种账号会显示成别人的号 | 口径 / 唯一口径指针 |
| 界面拿 `phone.contains("_del")` 当「已删除」判据 | 恢复撞号的账号被误算进回收站（它带后缀，但号已经归别人） | 回收站判据 |
| 「已停用」档不排掉回收站 | 这一档又混进被埋掉的旧账号 —— P2 等于没修 | 状态档判据 |
| 名册卡静默留白 | 用户以为「这人没填电话」，比乱码更难查 | 没号要说出来 |
| 绑车候选只过滤 `!isActive` | 已删账号（`isActive` 也是 false，语义不同）照样能选 | 绑车候选 |
| 回收站账号还挂着删除/停用按钮 | 按下去不是 400 就是重复改后缀 | 回收站只给恢复 |

### 判据
1. 后端 `UserOut` 下发 `phone_display` 与 `is_deleted` 两格，口径在本体
   （`services/soft_delete.dialable_phone` / `api/v1/users.py::_in_recycle_bin`）；
2. Android 的 `UserDto` 与之一一对应，并**保留 `phone` 原值**（表单回显 / 搜索 / AI 别名要用）；
3. 界面画号码只走 `rosterPhoneOf`（有 `phoneDisplay` 用它 → 自带 `_del` 后缀回 null → 否则回落 `phone`），
   没号时写 `ROSTER_PHONE_TAKEN`（≤ 8 字）而不是留白；四张名册卡都不再直接画 `u.phone`；
4. 账户页四档状态（全部 / 在用 / 已停用 / 已删除），默认停在「在用」，「已停用」排掉回收站，
   档位行常驻在搜索框下面不随列表滚走，筛空时**说出来**；
5. 回收站账号只给「恢复」；绑车候选排除已停用/已删除，并把「为什么少了人」说出来；
6. 空态文案真的画得出来：这几页的 EmptyView 调用**不带固定高度** —— 带了的那些
   （140dp / 160dp）在真机上只剩一个图标，文案被量成 0 高（2026-10-03 复测抓到）；
7. 留痕：变更文档 / 登记表 / AI_WORK_CLAIM 声明块都在（红了要能顺着找到由来）。

### R4-BOUNDARY-JUSTIFICATION

R4-BOUNDARY-JUSTIFICATION: 这一条**没法用边界消除** —— 「界面画的是后端算出的人话，还是自己猜的内部值」
只存在于**调用点**：后端把 phone_display 与 is_deleted 下发出来（边界那一半已经做了），
界面照样可以继续直画 u.phone（软删账号那一行就是 13923111638_del62）、
照样可以在绑车候选里只过滤 !isActive（「已停用」与「已删除」是两件事）——
这些在 Kotlin 里全是普通 String / Boolean，编译器一句都拦不住。
所以第 3 / 4 / 5 条只能拿源码文本把「谁画了哪一格、哪一档筛了谁、按不动的时候给不给按钮」钉住，
再由 _reverse_verify_user_account_status.py（13 条注入）证明这些钉子有牙；
另一半（「装到 5554 上真的好看」）交给 _install_all.py --only 5554 加截图人工判。

用法：python _tools/qa/_check_user_account_status.py
"""
from __future__ import annotations

import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders"
ROSTER = AND / "ui" / "common" / "RosterCard.kt"
DTOS = AND / "data" / "remote" / "dto" / "Dtos.kt"
VM = AND / "ui" / "dispatcher" / "AccountManageViewModel.kt"
SCREEN = AND / "ui" / "dispatcher" / "AccountManageScreen.kt"
USERS_UI = AND / "ui" / "dispatcher" / "UsersManageScreen.kt"
VEHICLE = AND / "ui" / "dispatcher" / "VehicleManageScreen.kt"
USER_SCHEMA = ROOT / "backend" / "app" / "schemas" / "user.py"
USERS_API = ROOT / "backend" / "app" / "api" / "v1" / "users.py"
SOFT_DELETE = ROOT / "backend" / "app" / "services" / "soft_delete.py"
BACKEND_TEST = ROOT / "backend" / "tests" / "test_user_roster_phone_and_bin.py"
CHANGE_DOC = ROOT / "docs" / "changes" / "BUG-0002.md"
CHANGE_README = ROOT / "docs" / "changes" / "README.md"
CLAIM = ROOT / "docs" / "AI_WORK_CLAIM.md"
REVERSE = ROOT / "_tools" / "qa" / "_reverse_verify_user_account_status.py"

Q = chr(34)  # ASCII 双引号：判据要逐字对源码，而 Python 里不好直接嵌它
TAKEN = "号码已让给新账号"

MIN_ITEMS = 60


def read(p: Path) -> str:
    if not p.exists():
        raise SystemExit("找不到 " + str(p.relative_to(ROOT)) + " —— 改名 / 移动了？本脚本的断言要跟着改")
    return p.read_text(encoding="utf-8")


class Checker:
    def __init__(self) -> None:
        self.total = 0
        self.failed: list[str] = []

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        self.total += 1
        if not cond:
            self.failed.append(label + ("：" + detail if detail else ""))

    def present(self, label: str, text: str, needle: str) -> None:
        self.ok(label, needle in text, "没找到 " + needle)

    def absent(self, label: str, text: str, needle: str) -> None:
        self.ok(label, needle not in text, "不该还在：" + needle)


def empty_view_calls(src: str) -> list[str]:
    """把每一处 EmptyView(...) 的实参原文抠出来（配平括号；字符串里的括号不算）。"""
    out: list[str] = []
    i = src.find("EmptyView(")
    while i >= 0:
        j = i + len("EmptyView(")
        depth = 1
        while j < len(src) and depth:
            ch = src[j]
            if ch == Q:
                j += 1
                while j < len(src) and src[j] != Q:
                    j += 2 if src[j] == chr(92) else 1
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            j += 1
        out.append(src[i:j])
        i = src.find("EmptyView(", j)
    return out


def main() -> int:
    c = Checker()
    roster = read(ROSTER)
    dtos = read(DTOS)
    vm = read(VM)
    screen = read(SCREEN)
    users_ui = read(USERS_UI)
    vehicle = read(VEHICLE)
    schema = read(USER_SCHEMA)
    api = read(USERS_API)
    soft = read(SOFT_DELETE)
    bt = read(BACKEND_TEST)

    # ---- ① 口径本体（后端）----
    c.present("手机号：schema 有 phone_display", schema, "phone_display: str | None = None")
    c.present("手机号：schema 有 is_deleted", schema, "is_deleted: bool = False")
    c.present("手机号：可拨号码的唯一口径还在", soft, "def dialable_phone(user")
    c.present("手机号：删号会加 _del 后缀", soft, "def del_suffix")
    c.present("回收站判据：后端算好再下发", api, "def _in_recycle_bin(u: User) -> bool:")
    c.present("回收站判据：带后缀且已停用", api, "return _is_deleted_account(u) and not u.is_active")
    c.present("回收站判据：_to_out 下发 is_deleted", api, "out.is_deleted = _in_recycle_bin(u)")
    c.present("手机号：_to_out 下发 phone_display", api, "out.phone_display = dialable_phone(u)")
    c.present("恢复：有 restore 端点", api, "@router.post(" + Q + "/{user_id}/restore" + Q)

    # ---- ② 后端用例（口径的行为证据）----
    c.present("用例：回收站账号的名册号码不再带后缀", bt, "def test_回收站账号的名册号码不再带_del后缀")
    c.present("用例：恢复时撞号的账号不给号码", bt, "def test_恢复时撞号的账号不给号码")
    c.present("用例：停用的账号不算回收站", bt, "def test_停用的账号不算回收站")
    c.present("用例：在用账号显示自己的号码", bt, "def test_在用账号的显示号码就是自己的号码")

    # ---- ③ Android 那面镜子 ----
    c.present("DTO：phone_display 与后端同名", dtos, "@SerialName(" + Q + "phone_display" + Q + ") val phoneDisplay: String? = null,")
    c.present("DTO：is_deleted 与后端同名", dtos, "@SerialName(" + Q + "is_deleted" + Q + ") val isDeleted: Boolean = false,")
    c.present("DTO：phone 原值必须留着（表单回显 / 搜索 / AI 别名）", dtos, "val phone: String,")
    c.present("DTO：注释点明唯一口径在 soft_delete.dialable_phone", dtos, "soft_delete.py::dialable_phone")
    c.present("DTO：注释写明界面不许自己猜后缀", dtos, "界面不许自己拿")

    # ---- ④ 展示口径（唯一一处）----
    c.present("口径：rosterPhoneOf 收账号", roster, "fun rosterPhoneOf(u: UserDto): String?")
    c.present("口径：后端给了就用它", roster, "if (!shown.isNullOrBlank()) return shown")
    c.present("口径：没有可拨号时回 null（不回落内部值）", roster, "return if (u.phone.contains(" + Q + "_del" + Q + ")) null else u.phone")
    c.present("没号要说出来：常量存在", roster, "const val ROSTER_PHONE_TAKEN: String = " + Q + TAKEN + Q)
    c.ok("没号要说出来：常驻文案 ≤ 8 字（设计规范 §4.10）", len(TAKEN) <= 8, "现在是 " + str(len(TAKEN)) + " 字")
    c.present("没号要说出来：那一行真的画它", roster, "ROSTER_PHONE_TAKEN,")
    c.present("没号要说出来：灰字（不染能打的号那种青绿）", roster, "color = MaterialTheme.colorScheme.onSurfaceVariant,")
    c.present("展示件：RosterPhoneRowOf 收账号", roster, "fun RosterPhoneRowOf(")
    c.present("展示件：有号走共用的 RosterPhoneRow", roster, "RosterPhoneRow(phone = shown, modifier = modifier, fontSize = fontSize)")

    # ---- ⑤ 四张名册卡的调用点 ----
    c.present("账户卡：电话行走账号版", screen, "RosterPhoneRowOf(u)")
    c.present("账户卡：姓名空时回落到显示号码", screen, "name = u.fullName.ifBlank { rosterPhoneOf(u) ?: ROSTER_PHONE_TAKEN }")
    c.present("账户卡：删除确认框也走显示号码", screen, "val shownPhone = rosterPhoneOf(target) ?: ROSTER_PHONE_TAKEN")
    c.present("名册卡：电话行走账号版", users_ui, "RosterPhoneRowOf(u)")
    c.present("名册卡：卡上仍然写得出「已停用」", users_ui, Q + "已停用" + Q)

    # ---- ⑥ 状态档（P2）----
    c.present("状态档：四档名字", vm, "val ACCOUNT_STATUS_TABS: List<String> = listOf(" + Q + "全部" + Q + ", " + Q + "在用" + Q + ", " + Q + "已停用" + Q + ", " + Q + "已删除" + Q + ")")
    c.present("状态档判据：只认后端算好的 isDeleted", vm, "fun matchesStatus(u: UserDto, tab: Int): Boolean = when (tab) {")
    c.present("状态档判据：「在用」= 启用且不在回收站", vm, "1 -> u.isActive && !u.isDeleted")
    c.present("状态档判据：「已停用」排掉回收站", vm, "2 -> !u.isActive && !u.isDeleted")
    c.present("状态档判据：「已删除」= 回收站", vm, "3 -> u.isDeleted")
    c.present("状态档：默认停在「在用」", vm, "var statusTab by mutableStateOf(1)")
    c.present("状态档：列表按档过滤", vm, "inRail(shown, railKey) { it.category }.filter { matchesStatus(it, statusTab) }")
    c.present("状态档：档位行在搜索框下面（常驻）", screen, "SegmentedStatusTabs(")
    c.present("状态档：档位色一档一格", screen, "colors = ACCOUNT_STATUS_COLORS,")
    c.present("状态档：选中态来自 ViewModel", screen, "selected = vm.statusTab,")
    c.present("状态档：列表吃剩余高度（weight(1f)）", screen, "Modifier.weight(1f),")
    c.present("状态档：卡片来自筛过的那个列表", screen, "items(vm.shownInRail, key = { it.id })")
    c.present("状态档：筛空要说出来（不是一片白）", screen, "if (vm.shownInRail.isEmpty() && railShown.isNotEmpty())")
    c.present("状态档：空态点名当前档", screen, "ACCOUNT_STATUS_TABS[vm.statusTab]")

    # ---- ⑦ 回收站只给「恢复」----
    c.present("回收站只给恢复：卡片收下回调", screen, "onRestore: () -> Unit,")
    c.ok("回收站只给恢复：按 isDeleted 分岔（回收站那一支写在后面，见下一条的前后关系）",
         "if (!u.isDeleted) {" in screen or "if (u.isDeleted) {" in screen,
         "卡片动作行里找不到 isDeleted 分岔")
    c.present("回收站只给恢复：动作只有「恢复」一个", screen, "AccountAction(" + Q + "恢复" + Q + ", Icons.Default.RestoreFromTrash, Color(MgrGreen), onRestore)")
    c.present("回收站只给恢复：徽章写「已删除」", screen, Q + "已删除" + Q + ",")
    c.present("回收站只给恢复：调用点传回调", screen, "onRestore = { vm.restore(u) },")
    c.present("回收站只给恢复：ViewModel 调 restoreUser", vm, "val back = container.repo.restoreUser(u.id)")
    c.present("回收站只给恢复：提示走显示号码", vm, "(rosterPhoneOf(back) ?: back.fullName.ifBlank { back.username })")

    # ---- ⑧ 绑车候选（P10）----
    c.present("绑车候选：先排掉停用/已删", vehicle, "val eligible = hits.filter { it.isActive && !it.isDeleted }")
    c.present("绑车候选：被排掉的人数记下来", vehicle, "val excluded = hits.size - eligible.size")
    c.present("绑车候选：只列合格的", vehicle, "val shown = eligible.take(30)")
    c.present("绑车候选：副标题走显示号码", vehicle, "else -> rosterPhoneOf(d) ?: ROSTER_PHONE_TAKEN")
    c.absent("绑车候选：不再有「已停用的账号」那一支", vehicle, Q + "已停用的账号" + Q)
    c.present("绑车候选：一个都不剩时说清楚", vehicle, "都是已停用/已删除的账号")
    c.present("绑车候选：有被挡下的就说明", vehicle, "个匹配的司机是已停用/已删除的账号")
    c.present("绑车候选：只在还有合格的人时才加那句", vehicle, "if (excluded > 0 && eligible.isNotEmpty())")

    # ---- ⑨ 别处不许改宽（回归护栏）----
    texts = {p: p.read_text(encoding="utf-8") for p in sorted(AND.rglob("*.kt"))}
    blob = "".join(texts.values())
    c.absent("全库：不留 phone = u.phone 这种直画", blob, "phone = u.phone")
    guessed = [p.name for p, t in texts.items() if "u.phone.contains(" + Q + "_del" + Q + ")" in t]
    c.ok("全库：只有一处自己判 _del 后缀（RosterCard 的兜底）", guessed == ["RosterCard.kt"], str(guessed))
    c.present("回归护栏：val shown 那条口径没被动过（别的红线钉着）", vm, "val shown: List<UserDto> get() = hits ?: users")
    c.absent("回归护栏：账户页不许有描边输入框（_check_sheet_form_pages 钉着）", screen, "OutlinedTextField(")

    # ---- ⑨b 空态文案要真的画得出来（2026-10-03 真机复测抓到的）----
    # EmptyView 肚子里的账是「上下各 48dp 内边距 + 56dp 图标 + 12dp 间隔 + 文案」：
    # 调用点再套一个固定高度（140dp / 160dp），内容盒只剩 44dp / 64dp，Column 会把超出的
    # 额度从后面的孩子身上扣光 —— 文案被量成 0 高，屏幕上只剩一个图标（真机截图
    # _tmp/v2_empty_tab.png、_tmp/v2_search_empty.png）。⛔ 所以钉的是
    # 「这几页里没有一个 EmptyView 调用带 height(」。
    for _p in (SCREEN, USERS_UI, VEHICLE):
        _calls = empty_view_calls(texts[_p])
        c.ok("空态看得见：" + _p.name + " 扫得到 EmptyView（判据没空转）", bool(_calls), "一处都没扫到？")
        _fat = [t for t in _calls if "height(" in t]
        c.ok(
            "空态看得见：" + _p.name + " 的空态不带固定高度",
            not _fat,
            "；".join(x.replace(chr(10), " ") for x in _fat),
        )

    # ---- ⑩ 留痕与指针 ----
    c.ok("留痕：变更文档在", CHANGE_DOC.exists(), str(CHANGE_DOC.relative_to(ROOT)))
    dtext = CHANGE_DOC.read_text(encoding="utf-8") if CHANGE_DOC.exists() else ""
    c.present("留痕：文档写了判据脚本", dtext, "_check_user_account_status.py")
    c.present("留痕：文档写了反验脚本", dtext, "_reverse_verify_user_account_status.py")
    c.present("留痕：文档写了后端用例", dtext, "test_user_roster_phone_and_bin.py")
    c.ok("留痕：反验脚本在", REVERSE.exists(), str(REVERSE.relative_to(ROOT)))
    c.present("留痕：登记表里有这一条", read(CHANGE_README), "BUG-0002")
    c.present("留痕：AI_WORK_CLAIM 有声明块", read(CLAIM), "_check_user_account_status.py")

    if c.total < MIN_ITEMS:
        c.ok("判据下限（" + str(MIN_ITEMS) + " 条）", False, "只跑了 " + str(c.total) + " 条 —— 判据在空转")
    for line in c.failed:
        print("[FAIL] " + line)
    if c.failed:
        print("❌ " + str(len(c.failed)) + "/" + str(c.total) + " 条不达标")
        return 1
    print("✅ 全部 " + str(c.total) + " 项通过：P1 名册号码 / P2 账户状态档 / P10 绑车候选 都在")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())