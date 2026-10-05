"""反向验证：把 CHG-0048 那条判据（_check_contact_remark.py）逐条弄坏，看它**真的会红**。

为什么这块必须反向验证：下面每一条坏法**都不报错**——
- 备注列 / 迁移的 DDL 收窄成 32 或 64：Kotlin 与 Python 照样编译、照样启动，
  只是「写 200 字备注」在某一天被数据库静默截断，或者带进地点备注时短了一截；
- ContactOut 不带 remark、或者打开编辑时不回填：改一次称呼就把备注清掉了，界面一声不响；
- POST 无条件覆盖 / 迁移里多一句 UPDATE：前者是「每次按号 upsert 都抹掉老备注」，
  后者是「凭空造出用户从没写过的话」——两件都只在真实库上跑出来；
- PATCH 少了 strip、把 String? 改成 String：类型都成立，只有语义没了；
- 抽屉那一格换绑、卡上那一行不画：界面照画，只是内容存不进去 / 看不见。

机器判据本身几乎全是「读源码里有没有那一行」，这种判据如果不反向验证，就可能因为名字改了、
文件搬了、正则写松了而**永远绿**。

用法：python _tools/qa/_reverse_verify_contact_remark.py    # 全部报红 → 退出码 0
"""
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CHECK = HERE / "_check_contact_remark.py"

BACK = ROOT / "backend/app"
MODELS = BACK / "models/shipper.py"
SCHEMAS = BACK / "schemas/shipper.py"
API = BACK / "api/v1/shipper.py"
MIG = BACK / "migrations/023_shipper_contact_remark.py"
BOOT = BACK / "core/schema_bootstrap.py"
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DTOS = AND / "data/remote/dto/Dtos.kt"
VM = AND / "ui/shipper/AddressViewModel.kt"
SCREEN = AND / "ui/shipper/AddressScreen.kt"

# (说明, 文件, 原文, 替换成, 期望变红的检查名关键词)
MUTATIONS = [
    (
        "备注列被收窄成 64（与地点那一列不再逐字同形）",
        MODELS,
        "    #: 与 `shipper_locations.remark` **逐字同形**（同样 `String(256)`、同样 `default=\"\"`）：\n"
        "    #: 两处是同一件事（「给人看的一行说明」），读侧不该出现两套写法。\n"
        "    remark: Mapped[str] = mapped_column(String(256), default=\"\")\n",
        "    #: 与 `shipper_locations.remark` **逐字同形**（同样 `String(256)`、同样 `default=\"\"`）：\n"
        "    #: 两处是同一件事（「给人看的一行说明」），读侧不该出现两套写法。\n"
        "    remark: Mapped[str] = mapped_column(String(64), default=\"\")\n",
        "[存储] 与 shipper_locations.remark 逐字同形",
    ),
    (
        "ContactCreate 的 SHOWABLE_FIELDS 里去掉 remark（备注不再是「看得见的字」）",
        SCHEMAS,
        "    SHOWABLE_FIELDS = (\"display_name\", \"remark\")\n"
        "\n"
        "    # 原来只写 `min_length=5` —— 5 位的\"电话\"实际上打不出去（生产库那条 `[222]` 就是这么进来的）。\n",
        "    SHOWABLE_FIELDS = (\"display_name\",)\n"
        "\n"
        "    # 原来只写 `min_length=5` —— 5 位的\"电话\"实际上打不出去（生产库那条 `[222]` 就是这么进来的）。\n",
        "[schema] ContactCreate 的 SHOWABLE_FIELDS 含 remark",
    ),
    (
        "ContactCreate.remark 长度收到 64（带进地点备注时会被截断）",
        SCHEMAS,
        "    remark: str = Field(default=\"\", max_length=256)\n"
        "\n"
        "\n"
        "class ContactUpdate(ShowableModel):\n",
        "    remark: str = Field(default=\"\", max_length=64)\n"
        "\n"
        "\n"
        "class ContactUpdate(ShowableModel):\n",
        "[schema] ContactCreate.remark 与 LocationCreate.remark 同一个长度",
    ),
    (
        "ContactOut 不再带回 remark（编辑一次就把备注静默清掉）",
        SCHEMAS,
        "    #: 备注（L-10）：\"\" = 没写。**只回给联系人自己的主人** —— 这个端点的查询本来\n"
        "    #: 就按 `current.id` 隔离（见 api/v1/shipper.py::list_contacts 的过滤与排序）。\n"
        "    remark: str = \"\"\n",
        "    #: 备注（L-10）：\"\" = 没写。**只回给联系人自己的主人** —— 这个端点的查询本来\n"
        "    #: 就按 `current.id` 隔离（见 api/v1/shipper.py::list_contacts 的过滤与排序）。\n",
        "[schema] ContactOut 带回 remark",
    ),
    (
        "POST 无条件覆盖备注（空串也覆盖：每次按号 upsert 都把老备注抹掉）",
        API,
        "        if remark:\n"
        "            row.remark = remark\n",
        "            row.remark = remark\n",
        "[端点] POST 只在这次真的给了备注时才覆盖",
    ),
    (
        "PATCH 落库前不再 strip（前后空格原样存进来）",
        API,
        "    if body.remark is not None:\n"
        "        c.remark = body.remark.strip()\n",
        "    if body.remark is not None:\n"
        "        c.remark = body.remark\n",
        "[端点] PATCH：strip 之后再落库",
    ),
    (
        "迁移 023 的 DDL 收窄成 32（模型 256 / 库里 32，两处不再同形）",
        MIG,
        "DDL = \"remark VARCHAR(256) NOT NULL DEFAULT ''\"\n",
        "DDL = \"remark VARCHAR(32) NOT NULL DEFAULT ''\"\n",
        "[迁移] 迁移 023 的列定义与模型逐字同形",
    ),
    (
        "迁移 023 不再判「列在不在」（已加过的库重跑就炸）",
        MIG,
        "    if COLUMN not in have:\n"
        "        with engine.begin() as conn:\n",
        "    if True:\n"
        "        with engine.begin() as conn:\n",
        "[迁移] 先判列在不在",
    ),
    (
        "迁移 023 顺手回填老数据（把称呼灌进备注 = 凭空造出用户没写过的话）",
        MIG,
        "    if COLUMN not in have:\n"
        "        with engine.begin() as conn:\n"
        "            conn.execute(text(f\"ALTER TABLE {TABLE} ADD COLUMN {DDL}\"))\n",
        "    if COLUMN not in have:\n"
        "        with engine.begin() as conn:\n"
        "            conn.execute(text(f\"ALTER TABLE {TABLE} ADD COLUMN {DDL}\"))\n"
        "            conn.execute(text(\"UPDATE shipper_contacts SET remark = display_name\"))\n",
        "[迁移] ⛔ 不回填老数据",
    ),
    (
        "schema_bootstrap 里又长出一份自愈（同一件事两个地方改）",
        BOOT,
        "        for col, ddl in (\n"
        "            (\"contact_name\", \"VARCHAR(128) DEFAULT ''\"),\n"
        "            (\"contact_phone\", \"VARCHAR(32) DEFAULT ''\"),\n"
        "        ):\n",
        "        for col, ddl in (\n"
        "            (\"contact_name\", \"VARCHAR(128) DEFAULT ''\"),\n"
        "            (\"contact_phone\", \"VARCHAR(32) DEFAULT ''\"),\n"
        "        ):\n"
        "        if \"shipper_contacts\" in insp.get_table_names():\n"
        "            ccols = {c[\"name\"] for c in insp.get_columns(\"shipper_contacts\")}\n"
        "            if \"remark\" not in ccols:\n"
        "                with engine.begin() as conn:\n"
        "                    conn.execute(text(\"ALTER TABLE shipper_contacts ADD COLUMN remark VARCHAR(256) NOT NULL DEFAULT ''\"))\n",
        "[迁移] ⛔ schema_bootstrap 里没有第二份自愈",
    ),
    (
        "ContactDto.remark 变成可空（出参可能出 null，界面拿到就得自己兜）",
        DTOS,
        "     * 备注（L-10，用户 2026-10-06：「联系人他也是要有备注的」）：\"\" = 没写。\n"
        "     *\n"
        "     * 与 `LocationDto.remark` 是**同一样东西**（同样是 256 字，见后端 `ContactCreate.remark`）：\n"
        "     * 在「选联系人」那一刻会被带进**地点备注栏**，之后那一格归用户自己改\n"
        "     * （⛔ 不做「跟随联系人」的联动）。**只有自己看得见** —— 服务端只把它回给联系人自己的主人，\n"
        "     * ⛔ 不进共享地点库、⛔ 不进订单出参。\n"
        "     */\n"
        "    val remark: String = \"\",\n"
        "    @SerialName(\"created_at\") val createdAt: String = \"\",\n",
        "     * 备注（L-10，用户 2026-10-06：「联系人他也是要有备注的」）：\"\" = 没写。\n"
        "     *\n"
        "     * 与 `LocationDto.remark` 是**同一样东西**（同样是 256 字，见后端 `ContactCreate.remark`）：\n"
        "     * 在「选联系人」那一刻会被带进**地点备注栏**，之后那一格归用户自己改\n"
        "     * （⛔ 不做「跟随联系人」的联动）。**只有自己看得见** —— 服务端只把它回给联系人自己的主人，\n"
        "     * ⛔ 不进共享地点库、⛔ 不进订单出参。\n"
        "     */\n"
        "    val remark: String? = null,\n"
        "    @SerialName(\"created_at\") val createdAt: String = \"\",\n",
        "[DTO] ContactDto.remark 是非空 String",
    ),
    (
        "ContactUpdateRequest.remark 不再可空（null 的「不动」语义没了，改一次就写一次）",
        DTOS,
        "    /** 备注：null = 不动；\"\" = 清掉（与地点备注同一条 PATCH 语义）。 */\n"
        "    val remark: String? = null,\n",
        "    /** 备注：null = 不动；\"\" = 清掉（与地点备注同一条 PATCH 语义）。 */\n"
        "    val remark: String = \"\",\n",
        "[DTO] ContactUpdateRequest.remark 可空",
    ),
    (
        "ContactCreateRequest 不再带 remark（新建时写的备注发不出去）",
        DTOS,
        "    /** 备注（\"\" = 没写）：只有自己看得见；选这位联系人时会带进地点备注。 */\n"
        "    val remark: String = \"\",\n",
        "    /** 备注（\"\" = 没写）：只有自己看得见；选这位联系人时会带进地点备注。 */\n",
        "[DTO] ContactCreateRequest.remark 有默认值",
    ),
    (
        "打开编辑时不再回填备注（整份回传 = 改个称呼顺手把备注清掉）",
        VM,
        "        // 备注同理**必须回填**：保存走的是「整份回传」（新建与编辑共用同一个请求体），\n"
        "        // 不回填就等于「改个称呼顺手把备注清掉了」。\n"
        "        contactRemark = c?.remark ?: \"\"\n",
        "        // 备注同理**必须回填**：保存走的是「整份回传」（新建与编辑共用同一个请求体），\n"
        "        // 不回填就等于「改个称呼顺手把备注清掉了」。\n",
        "[VM] 打开编辑时把备注回填",
    ),
    (
        "选联系人时无条件覆盖地点备注（用户自己写好的那一行被盖掉）",
        VM,
        "                // L-10：选联系人时把他档案上的**备注**带进地点备注 —— ⛔ 只在地点备注还空着时填：\n"
        "                // 用户自己写过的那一行是他的，不能被联系人档案上的字盖掉（这与 fillReceiver 的\n"
        "                // 「有值才覆盖」是**两条不同的纪律**，别混）。\n"
        "                if (locRemark.isBlank() && c.remark.isNotBlank()) locRemark = c.remark\n",
        "                // L-10：选联系人时把他档案上的**备注**带进地点备注 —— ⛔ 只在地点备注还空着时填：\n"
        "                // 用户自己写过的那一行是他的，不能被联系人档案上的字盖掉（这与 fillReceiver 的\n"
        "                // 「有值才覆盖」是**两条不同的纪律**，别混）。\n"
        "                locRemark = c.remark\n",
        "[VM] 选联系人时带出备注",
    ),
    (
        "新建联系人那条路不再带备注（写了也存不进去）",
        VM,
        "                            displayName = contactName.trim(),\n"
        "                            category = contactCategory.trim(),\n"
        "                            remark = contactRemark.trim(),\n"
        "                        )\n"
        "                    )\n"
        "                    if (lineContactCtx) {\n",
        "                            displayName = contactName.trim(),\n"
        "                            category = contactCategory.trim(),\n"
        "                        )\n"
        "                    )\n"
        "                    if (lineContactCtx) {\n",
        "[VM] 新建那条路带上备注",
    ),
    (
        "编辑联系人那条路不再带备注（整份回传 = 顺手把备注清掉）",
        VM,
        "                            phone = contactPhone.trim(),\n"
        "                            displayName = contactName.trim(),\n"
        "                            category = contactCategory.trim(),\n"
        "                            remark = contactRemark.trim(),\n"
        "                        )\n"
        "                    )\n"
        "                }\n",
        "                            phone = contactPhone.trim(),\n"
        "                            displayName = contactName.trim(),\n"
        "                            category = contactCategory.trim(),\n"
        "                        )\n"
        "                    )\n"
        "                }\n",
        "[VM] 编辑那条路带上备注",
    ),
    (
        "抽屉里那一格不再绑 contactRemark（写了也存不进去）",
        SCREEN,
        "                    FormInputRow(\n"
        "                        label = \"备注\",\n"
        "                        value = vm.contactRemark,\n"
        "                        onValueChange = { vm.contactRemark = it },\n"
        "                        placeholder = \"选填\",\n"
        "                        icon = Icons.Default.Notes,\n"
        "                        iconTint = MaterialTheme.colorScheme.outline,\n"
        "                    )\n",
        "                    FormInputRow(\n"
        "                        label = \"备注\",\n"
        "                        value = \"\",\n"
        "                        onValueChange = { vm.contactRemark = it },\n"
        "                        placeholder = \"选填\",\n"
        "                        icon = Icons.Default.Notes,\n"
        "                        iconTint = MaterialTheme.colorScheme.outline,\n"
        "                    )\n",
        "[界面] 联系人抽屉里备注那一格绑在 vm.contactRemark 上",
    ),
    (
        "联系人卡上不再画备注（写了也看不见）",
        SCREEN,
        "                // 备注（L-10）也上卡：用户 2026-10-06 明确要求备注显示在联系人卡上\n"
        "                // （「联系人他也是要有备注的」）。形状与地点卡那一行相同：没写就整行不画、不留空标签。\n"
        "                if (c.remark.isNotBlank()) {\n"
        "                    Spacer(Modifier.height(4.dp))\n"
        "                    Text(c.remark, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.outline)\n"
        "                }\n",
        "                // 备注（L-10）也上卡：用户 2026-10-06 明确要求备注显示在联系人卡上\n"
        "                // （「联系人他也是要有备注的」）。形状与地点卡那一行相同：没写就整行不画、不留空标签。\n",
        "[界面] 联系人卡上画着备注",
    ),
]


def read_src(p: Path) -> tuple[str, bool]:
    data = p.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(p: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    p.write_bytes(out)
    return out


def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**：写回后重新读回来逐字节比，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的字节 == 刚写出去的字节 才是。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print("⛔ 还原后与快照不一致（注入污染了源码树）：" + str(p))
        raise SystemExit(2)


def run_check() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(CHECK)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def verdict(expect: str) -> tuple[bool, str]:
    code, out = run_check()
    fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
    hit = code != 0 and any(expect in ln for ln in fails)
    return hit, f"实际红 {len(fails)} 条" + ("" if hit else f"：{[f.strip()[:70] for f in fails[:2]]}")


def main() -> int:
    bad = 0
    code, out = run_check()
    if code != 0:
        print(f"❌ 前提不成立：源码完好时这条红线没过\n{out[-1200:]}")
        return 1
    print("✅ 前提：源码完好时这条红线是绿的")

    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            hit, detail = verdict(expect)
        finally:
            restore_src(path, src, crlf)
        print(f"  [{'OK' if hit else 'MISS'}] {label} → {detail}")
        if not hit:
            bad += 1

    code, out = run_check()
    ok = code == 0
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1

    total = len(MUTATIONS) + 1
    print()
    if bad:
        print(f"❌ {bad}/{total} 条不成立（红线对它们不敏感）")
        return 1
    print(f"✅ {total}/{total} 全部成立：每条注入都让红线点出了那一条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
