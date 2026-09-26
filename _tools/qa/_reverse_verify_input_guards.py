"""反向验证 §28（账号唯一创建路径 / 文本上限 / 中文报错）与 §29（司机钱账目完整性）。

## 为什么这两节也必须配反向验证
这两节的判据大多是**静态结构断言**（"这句话在不在源码里"），而这类判据最容易变成空转：
正则少个转义、扫错了文件、替换串过期——它照样"全绿"，什么也没查。
这个仓库已经栽过 6 次，所以规矩是：**新增红线就要有对应的注入实验**。

注入覆盖三类东西：
1. **源码红线**（`_check_ai_guardrails.py` 的 §28/§29）：把保护删掉 → 必须报红；
2. **审计工具**（`_tools/qa/_audit_text_fields.py`）：把某个字段的上限去掉 → 必须非零退出；
3. **"清单是算出来的"这条元判据**：把审计工具的反空转断言改坏 → 它必须自己停下来，
   而不是安静地报"全部有界"。

用法：`python _tools/qa/_reverse_verify_input_guards.py`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
AI_TOOLS = ROOT / "_tools" / "ai"
QA_TOOLS = ROOT / "_tools" / "qa"
GUARDRAILS = AI_TOOLS / "_check_ai_guardrails.py"
TEXT_AUDIT = QA_TOOLS / "_audit_text_fields.py"

AUTH_API = ROOT / "backend/app/api/v1/auth.py"
AUTH_SVC = ROOT / "backend/app/services/auth_service.py"
MAIN_PY = ROOT / "backend/app/main.py"
VAL_ERR = ROOT / "backend/app/core/validation_errors.py"
ORDER_SCHEMA = ROOT / "backend/app/schemas/order.py"
TEXT_SCHEMA = ROOT / "backend/app/schemas/text.py"
RULE_SCHEMA = ROOT / "backend/app/schemas/driver_billing_rule.py"
RULE_MODEL = ROOT / "backend/app/models/driver_billing_rule.py"
SHIPPER_SCHEMA = ROOT / "backend/app/schemas/shipper.py"
BILL_MODEL = ROOT / "backend/app/models/driver_bill.py"
BOOTSTRAP = ROOT / "backend/app/core/schema_bootstrap.py"
ACCT = ROOT / "backend/app/services/accounting_service.py"
SEED = AI_TOOLS / "_seed_test_data.py"
INVARIANTS = ROOT / "_tools/fuzz/_fuzz_invariants.py"
TEXT_TESTS = ROOT / "backend/tests/test_text_length_guards.py"
RECON_TESTS = ROOT / "backend/tests/test_driver_money_reconciliation.py"
UNIQUE_TESTS = ROOT / "backend/tests/test_driver_bill_unique.py"

#: (说明, 目标文件, 替换函数, 期望变红的检查)
CASES: list[tuple[str, Path, object, str]] = [
    # ---------------- §28 ----------------
    (
        "自助注册端点回来了（任何人能自助开号）",
        AUTH_API,
        lambda s: s.replace(
            '@router.post("/login", response_model=Token)',
            '@router.post("/register", response_model=Token)\ndef register_stub() -> None:\n    return None\n\n\n'
            '@router.post("/login", response_model=Token)',
            1,
        ),
        "guardrails",
    ),
    (
        "auth_service 里加回自助建号",
        AUTH_SVC,
        lambda s: s + "\n\ndef create_user(db, body):\n    return None\n",
        "guardrails",
    ),
    (
        "送货说明的上限被去掉（超长又能塞进 String(512) 列）",
        ORDER_SCHEMA,
        lambda s: s.replace('delivery_description: str = Field("", max_length=512)',
                            'delivery_description: str = ""', 1),
        "guardrails",
    ),
    (
        "送达收款方式的 pattern 被去掉（乱填的值会被静默当成挂账）",
        ORDER_SCHEMA,
        lambda s: s.replace('payment: str | None = Field(None, pattern="^(cash|arrears)$")',
                            "payment: str | None = None", 1),
        "guardrails",
    ),
    (
        "送达照片的条数上限被去掉",
        ORDER_SCHEMA,
        lambda s: s.replace(
            "delivery_photo_urls: list[Url] = Field(default_factory=list, max_length=MAX_IMAGES)",
            "delivery_photo_urls: list[Url] = Field(default_factory=list)", 1),
        "guardrails",
    ),
    (
        "app 上不再装中文校验处理器（422 又变成英文结构体）",
        MAIN_PY,
        lambda s: s.replace("    install_validation_errors(application)", "    pass", 1),
        "guardrails",
    ),
    (
        "认不出来的错误类型改成把英文原文甩出去",
        VAL_ERR,
        lambda s: s.replace('FALLBACK = "填写的内容不符合要求，请检查后重试"', 'FALLBACK = ""', 1),
        "guardrails",
    ),
    (
        "「边长值必须能过」的反向对照测试被删掉",
        TEXT_TESTS,
        lambda s: s.replace("def test_边长值被接受(", "def _disabled_边长值被接受(", 1),
        "guardrails",
    ),
    # ---------------- §29 ----------------
    (
        "账单唯一索引从模型上被去掉（数据库级闸门没了）",
        BILL_MODEL,
        lambda s: s.replace(
            '        Index("uq_driver_bills_order_type", "order_id", "bill_type", unique=True),\n',
            "", 1),
        "guardrails",
    ),
    (
        "旧库迁移不再补唯一索引",
        BOOTSTRAP,
        lambda s: s.replace("CREATE UNIQUE INDEX IF NOT EXISTS uq_driver_bills_order_type",
                            "CREATE INDEX IF NOT EXISTS ix_driver_bills_order_type", 1),
        "guardrails",
    ),
    (
        "有重复行也照建索引（启动会直接崩）",
        BOOTSTRAP,
        lambda s: s.replace("        if dups:\n", "        if False:\n", 1),
        "guardrails",
    ),
    (
        "付款前不再复核明细还在不在（明细被删也能把钱付出去）",
        ACCT,
        lambda s: s.replace('    if not live:\n        raise ValueError("这张结算单已经没有任何明细'
                            '（明细被删除或解绑），不能付款；请作废后重新结算")\n', "", 1),
        "guardrails",
    ),
    (
        "付款前不再核对明细金额",
        ACCT,
        lambda s: s.replace("    if Decimal(s.amount) != live_total:", "    if False:", 1),
        "guardrails",
    ),
    (
        "造数工具的自检被删掉（又能造出自相矛盾的账）",
        SEED,
        lambda s: s.replace('        sys.exit(f"  ⛔ 自检失败：本次造的结算单里有 {bad} 张没有明细'
                            '（造数不一致，必须修工具）")', "        pass", 1),
        "guardrails",
    ),
    (
        "不变式审计里的「已付款却无明细」判据被删掉",
        INVARIANTS,
        lambda s: s.replace('    check_ic(rep, "已确认/已付款结算单在库里没有任何关联明细"',
                            '    check_ic(rep, "_已禁用_结算单明细"', 1),
        "guardrails",
    ),
    (
        "「明细被删不许付款」的端到端测试被删掉",
        RECON_TESTS,
        lambda s: s.replace("def test_明细被删掉之后不许付款(", "def _disabled_明细被删(", 1),
        "guardrails",
    ),
    (
        "「月薪单不被唯一索引误拦」的反向对照被删掉",
        UNIQUE_TESTS,
        lambda s: s.replace("def test_salary_bills_without_order_are_not_blocked(",
                            "def _disabled_salary_bills(", 1),
        "guardrails",
    ),
    # ---------------- 审计工具自己 ----------------
    (
        "文本审计：某字段的上限被去掉 → 审计必须非零退出（不是只在源码里找字符串）",
        SHIPPER_SCHEMA,
        lambda s: s.replace("origin_address: str | None = Field(None, max_length=512)",
                            "origin_address: str | None = None", 1),
        "text_audit",
    ),
    (
        "文本审计：列表元素类型退化回裸 str（只限条数不再够用）",
        TEXT_SCHEMA,
        lambda s: s.replace("Url = Annotated[str, StringConstraints(max_length=MAX_URL)]",
                            "Url = str", 1),
        "text_audit",
    ),
    (
        "文本审计：模型清单被改坏（一个都不扫）→ 工具必须自己报「判据空转」",
        TEXT_AUDIT,
        lambda s: s.replace(
            "        if not any(model.__name__.endswith(s) for s in INPUT_SUFFIX):\n            continue",
            "        if True:\n            continue", 1),
        "text_audit_guard",
    ),
    # ---------------- 合法取值装得下吗（2026-09-24 第 19 轮） ----------------
    #
    # 真实咬过的一次：`piece_unit` 列与入参都是 8，而合法取值 `order_price` 有 11 个字符
    # —— 「拿这一单的钱」这条能力从上线起就没成功过（请求 422、列也存不下）。
    # 上面那一大段只比"声明 ≤ 列宽"，两边一致就放过，所以这三条注入专门打新加的那一问。
    (
        "文本审计：合法取值清单里最长的值装不下列宽（`piece_unit` 退回 String(8)）",
        RULE_MODEL,
        lambda s: s.replace("piece_unit: Mapped[str] = mapped_column(String(16)",
                            "piece_unit: Mapped[str] = mapped_column(String(8)", 1),
        "text_audit",
    ),
    (
        "文本审计：入参上界装不下合法取值（`piece_unit` 的 max_length 退回 8）",
        RULE_SCHEMA,
        lambda s: s.replace('piece_unit: str = Field("order", max_length=16)',
                            'piece_unit: str = Field("order", max_length=8)', 1),
        "text_audit",
    ),
    (
        "文本审计：bootstrap 的列宽自愈循环被删掉（老库永远停在窄列上）",
        BOOTSTRAP,
        lambda s: s.replace("def width_repair_ddl(", "def _disabled_width_repair_ddl(", 1),
        "text_audit",
    ),
]


def run(cmd: Path) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(cmd)], capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def section(out: str, n: int) -> str:
    """只取 §n 那一段（段内失败标记是 `[FAIL]`，不是汇总里的 ❌）。"""
    head = f"== {n}."
    if head not in out:
        return ""
    rest = out.split(head, 1)[1]
    return rest.split("\n" + "=" * 60, 1)[0]


def main() -> int:
    fails: list[str] = []
    code, out = run(GUARDRAILS)
    if code != 0:
        print(f"❌ 前提不成立：源码完好时红线就没过\n{out[-1500:]}")
        return 1
    for n in (28, 29):
        if not section(out, n):
            print(f"❌ 前提不成立：输出里找不到 §{n} 这一段")
            return 1
    code_a, out_a = run(TEXT_AUDIT)
    if code_a != 0:
        print(f"❌ 前提不成立：源码完好时文本审计没过\n{out_a[-1200:]}")
        return 1
    print("✅ 前提：源码完好时红线是绿的（§28/§29 都在），文本审计也是绿的")

    for label, path, mutate, which in CASES:
        original_bytes = path.read_bytes()
        original = original_bytes.decode("utf-8").replace(chr(13) + chr(10), chr(10))
        mutated = mutate(original)
        if mutated == original:
            fails.append(f"{label}：注入没生效（替换串过期了，请更新本脚本）")
            continue
        try:
            path.write_text(mutated, encoding="utf-8", newline="")
            if which == "text_audit_guard":
                code2, out2 = run(TEXT_AUDIT)
                red = "判据空转" in out2
            elif which == "text_audit":
                code2, out2 = run(TEXT_AUDIT)
                red = code2 != 0
            else:
                code2, out2 = run(GUARDRAILS)
                red = code2 != 0 and any("[FAIL]" in section(out2, n) for n in (28, 29))
        finally:
            path.write_bytes(original_bytes)
        # R3-07b：还原**当场核对**（不是「看起来还原了」）—— 对不上就记账，别让坏代码留在树里
        if path.read_bytes() != original_bytes:
            fails.append("还原后与快照不一致（注入污染了源码树）：" + str(path))
        if red:
            print(f"✅ 注入「{label}」→ 报红")
        else:
            fails.append(f"{label}：注入之后没有报红（{which}）——这条判据是空转的")

    if fails:
        print("\n❌ 反向验证不通过：")
        for f in fails:
            print("   - " + f)
        return 1
    print(f"\n✅ §28/§29 共 {len(CASES)} 条注入全部证明会红。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
