"""反向验证 `_tools/qa/_check_user_search.py`（红线：按「人」搜索只有一条规则）。

## 为什么必须做

这条判据守的事**坏起来完全静默**：某页把匹配口径改回自己那一份 contains，
搜索框照样能用、页面照样好看 —— 只是**有些人在某一页搜不到**。
用户拿不到任何报错线索，只会觉得"这个 App 有时候找得到人、有时候找不到"。
本机单测（`UserSearchTest` 测的是规则本身）、真机点一遍（只点一页），两种方式都测不出来。

所以逐条**注入真缺陷**，每条都必须让判据报红。

用法：python _tools/qa/_reverse_verify_user_search.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "_tools" / "qa" / "_check_user_search.py"

KT = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
USER_SEARCH_KT = KT / "core/UserSearch.kt"
LEDGER_SCREEN = KT / "ui/dispatcher/DispatcherLedgerScreen.kt"
LEDGER_VM = KT / "ui/dispatcher/DispatcherLedgerViewModel.kt"
USERS_VM = KT / "ui/dispatcher/UsersManageViewModel.kt"
ACCOUNT_VM = KT / "ui/dispatcher/AccountManageViewModel.kt"
VEHICLE_SCREEN = KT / "ui/dispatcher/VehicleManageScreen.kt"
ADDRESS_SCREEN = KT / "ui/shipper/AddressScreen.kt"
COMPONENTS = KT / "ui/common/Components.kt"
REPO = KT / "data/repo/AppRepository.kt"
APIS = KT / "data/remote/api/Apis.kt"
DTOS = KT / "data/remote/dto/Dtos.kt"

PY_APP = ROOT / "backend/app"
PY_RULE = PY_APP / "core/user_search.py"
PY_USERS = PY_APP / "api/v1/users.py"
PY_LEDGER = PY_APP / "api/v1/ledger.py"
PY_FREIGHT = PY_APP / "api/v1/freight_settlement.py"
PY_SCHEMA = PY_APP / "schemas/ledger.py"
PY_SOFT = PY_APP / "services/soft_delete.py"

TEST_KT = ROOT / "android/app/src/test/java/com/tapmoay/sorders/core/UserSearchTest.kt"


def _drop(s: str, needle: str, n: int = 1) -> str:
    return s.replace(needle, "", n)


#: (说明, 目标文件, 替换函数)
CASES: list[tuple[str, Path, object]] = [
    # ---- 规则唯一 ----
    (
        "客户端规则不再认手机号（只剩姓名 → 「后 4 位」这条需求当场失效）",
        USER_SEARCH_KT,
        lambda s: s.replace("if (phone?.contains(q, ignoreCase = true) == true) return true", "return false", 1),
    ),
    (
        "有人在别的页面又定义了一份按人匹配（两条口径开始分叉）",
        USERS_VM,
        lambda s: s.replace(
            "    fun openCreate() {",
            "    fun matches(q: String, name: String?, phone: String?): Boolean ="
            " name?.contains(q) == true || phone?.contains(q) == true\n\n    fun openCreate() {",
            1,
        ),
    ),
    (
        "后端谓词改成等值比较（「后 4 位」再也搜不到）",
        PY_RULE,
        lambda s: s.replace('like = f"%{term}%"', "like = term", 1),
    ),
    (
        "账号名册退回就地手搓谓词（不再走 user_search）",
        PY_USERS,
        lambda s: s.replace(
            "    pred = name_or_phone_like(User.full_name, User.phone, q)",
            '    pred = or_(User.full_name.like(f"%{q}%"), User.phone.like(f"%{q}%"))',
            1,
        ),
    ),
    (
        "实名册页的搜索退回本地过滤（第 501 个账号物理上找不到）",
        USERS_VM,
        lambda s: s.replace(
            "val page = container.repo.usersPage(role = pool.role, memberOnly = pool.memberOnly, q = kw)",
            "val page = container.repo.usersPage(role = pool.role, memberOnly = pool.memberOnly)",
            1,
        ),
    ),
    (
        "账户管理的搜索退回本地过滤（这一页列的是全部角色，最容易漏人）",
        ACCOUNT_VM,
        lambda s: s.replace("val page = container.repo.usersPage(q = kw)", "val page = container.repo.usersPage()", 1),
    ),
    (
        "仓库层不再把 q 传给接口（搜索框看着在，实际什么都没搜）",
        REPO,
        lambda s: s.replace("q = q?.trim()?.ifBlank { null },", "", 1),
    ),
    (
        "接口层 listUsers 不再声明 q 参数（请求打到后端会被忽略）",
        APIS,
        lambda s: s.replace('@Query("q") q: String? = null,', "", 1),
    ),
    (
        "搜索结果直接覆盖名册（`shown` 不再回落到 users）",
        USERS_VM,
        lambda s: s.replace(
            "val shown: List<UserDto> get() = hits ?: users",
            "val shown: List<UserDto> get() = hits ?: emptyList()",
            1,
        ),
    ),
    (
        "名字查找不再看搜索结果（搜出来的人被说成「不在名册里」）",
        USERS_VM,
        lambda s: s.replace("            ?: hits?.firstOrNull { it.id == driverId }\n", "", 1),
    ),
    # ---- 按人搜索框都走这一份 ----
    (
        "又有一个页面自己写按人匹配（提示语里同时提人和号码却不用规则）",
        VEHICLE_SCREEN,
        lambda s: s.replace(
            "placeholder = com.tapmoay.sorders.core.UserSearch.HINT,",
            'placeholder = "搜司机姓名 / 手机号",',
            1,
        ).replace("com.tapmoay.sorders.core.UserSearch.filter(", "listOf(", 1).replace(
            "        { it.fullName.ifBlank { it.username }},\n        { it.phone },\n    )", "    )", 1
        ),
    ),
    (
        "联系人那一段退回就地 contains（同一件事两个答案）",
        ADDRESS_SCREEN,
        lambda s: s.replace(
            "else vm.contacts.filter { UserSearch.matches(kw, it.displayName, it.phone) }",
            "else vm.contacts.filter { it.displayName.contains(kw, true) || it.phone.contains(kw) }",
            1,
        ),
    ),
    (
        "共享搜索框的默认提示语不再引用 UserSearch.HINT（各页开始各写一份）",
        COMPONENTS,
        lambda s: s.replace(
            "placeholder: String = com.tapmoay.sorders.core.UserSearch.HINT,",
            'placeholder: String = "搜索",',
            1,
        ),
    ),
    # ---- 后 4 位的行为得有人钉着 ----
    (
        "「后 4 位」那条单测被删掉（规则改了没人知道）",
        TEST_KT,
        lambda s: s.replace('assertTrue("手机号后 4 位", UserSearch.matches("8001", name, phone))', "", 1),
    ),
    (
        "单测里的反例被删掉（匹配恒真也能过）",
        TEST_KT,
        lambda s: s.replace('assertFalse(UserSearch.matches("8002", "张三", "13800008001"))', "", 1),
    ),
    # ---- 账本不许退回挑选器 ----
    (
        "账本又长出「多选挑选器」的状态（用户明确否掉的那套）",
        LEDGER_VM,
        lambda s: s.replace(
            "    var query by mutableStateOf(\"\")",
            "    var query by mutableStateOf(\"\")\n    var selectedAccounts by mutableStateOf<Set<String>>(emptySet())",
            1,
        ),
    ),
    (
        "三类账的行渲染拆回三段复制（改一处漏一处）",
        LEDGER_SCREEN,
        lambda s: s.replace(
            "                                        LedgerAccountRow(\n",
            "                                        LedgerAccountRow(\n"
            "                                        LedgerAccountRow(\n",
            1,
        ),
    ),
    (
        "账本的搜索不再走唯一实现（自己写 contains）",
        LEDGER_VM,
        lambda s: s.replace("UserSearch.filter(accountRows(), query, { it.title }, { it.phone })", "accountRows()", 1),
    ),
    # ---- 账户卡片必须认得出人 ----
    (
        "账本出参不再下发手机号（同名不同人分不开、也没得按号搜）",
        PY_SCHEMA,
        lambda s: s.replace("    phone: str | None = None", "    phone_unused: str | None = None", 1),
    ),
    (
        "司机账户组不再下发 driver_phone（三类账认人方式分叉）",
        PY_FREIGHT,
        lambda s: s.replace('"driver_phone": None,', '"driver_phone_x": None,', 1),
    ),
    (
        "Android 的 LedgerAccountOut 不再收 phone（后端给了也白给）",
        DTOS,
        lambda s: re.sub(
            r"(data class LedgerAccountOut\([\s\S]{0,900}?)val phone: String\? = null,",
            r"\1",
            s,
            count=1,
        ),
    ),
    (
        "Android 的 LedgerAccountOut 不再收 is_active（账号停用了界面上看不出来）",
        DTOS,
        lambda s: re.sub(
            r"(data class LedgerAccountOut\([\s\S]{0,900}?)@SerialName\(\"is_active\"\) val isActive: Boolean = true,",
            r"\1",
            s,
            count=1,
        ),
    ),
    (
        "账户行不再显示手机号（收下不用 = 用户还是分不开同名的人）",
        LEDGER_SCREEN,
        lambda s: s.replace('row.phone?.ifBlank { null } ?: "未注册账号",', '"",', 1),
    ),
    (
        "软删后缀不再去掉（给用户看一个打不通的号）",
        PY_LEDGER,
        lambda s: s.replace("b[\"phone\"] = (strip_del_suffix(u.phone) or None) if u else None", "b[\"phone\"] = (u.phone or None) if u else None", 1),
    ),
    (
        "去尾工具本身被删掉（逆运算没地方放）",
        PY_SOFT,
        lambda s: s.replace("def strip_del_suffix(", "def strip_del_suffix_removed(", 1),
    ),
]


def run(path: Path) -> int:
    p = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(ROOT),
    )
    return p.returncode


def main() -> int:
    before = {str(p): p.read_text(encoding="utf-8") for _, p, _ in CASES}
    if run(CHECK) != 0:
        print("❌ 前提不成立：源码完好时这条判据就没过（先让 _check_user_search.py 变绿）")
        return 1
    print("✅ 前提：源码完好时判据是绿的")

    fails: list[str] = []
    for label, path, mutate in CASES:
        original = path.read_text(encoding="utf-8")
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            code = run(CHECK)
        finally:
            path.write_text(original, encoding="utf-8", newline="")
        if code != 0:
            print(f"✅ 注入「{label}」→ 报红")
        else:
            fails.append(f"{label}：注入之后没有报红 —— 这条判据是空转的")

    # 收尾自证：所有文件都还原了（注入式验证最容易留下的坑是"改坏了自己不知道"）
    for k, v in before.items():
        if Path(k).read_text(encoding="utf-8") != v:
            fails.append(f"收尾没还原：{k}")
    if run(CHECK) != 0:
        fails.append("还原之后判据仍然红（有文件没被改回来）")

    if fails:
        print("\n❌ 反向验证没通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ {len(CASES)}/{len(CASES)} 种破坏方式全部被抓到，且源码已还原。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
