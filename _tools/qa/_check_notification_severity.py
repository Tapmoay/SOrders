#!/usr/bin/env python3
"""FEAT-0019 消息分级：severity（**判定只有一处**）与 payload.emphasis（**不许整行上色**）。

用户口径（2026-10-11，逐字）：
  ·「消息（底部 Tab）……要按消息类型做颜色区别，而且**只有未读状态才有这个样式**」；
  ·「文字也要按风险程度着色……按风险程度分红 / 橙 / …（重要程度不同 → 文字颜色不同）」；
  · 追加修正（同日晚）：「你的文字不能全部用颜色给他去搞出来……真正的重心是这几个字
    ……全是重点就是没有重点」。

## 这个功能为什么必须有自己的判据
「给消息上一个颜色」看起来是最不容易写错的一类改动 —— 恰恰因为如此，它错起来最安静：
判错的档不会抛异常、不会 500，它只是**安静地告诉用户一件错误的事**（该红的显示成普通，
或者反过来「全红」）。所以每一条口径都要有一条机器判据盯着：

| 少了这条判据 | 后果 | 谁会先发现 |
| --- | --- | --- |
| 判定散成两处 | 同一条消息在不同路径上得到不同档，改一边另一边不动 | 没人（安静地不一致） |
| 调用点写死 severity="warn" | 上面那条的入口 | 没人 |
| 表里漏了新 type | 新消息永远是「普通消息」 | 用户（「怎么不红」） |
| 出参里没有 severity | App 拿不到档，整件事白做 | 用户 |
| 列默认值改成 danger | 所有没登记的消息都变红 | 用户（「怎么全是红的」） |
| emphasis 不过滤 | 标了正文里根本没有的词 / 整行上色 | 用户（「全是重点就是没有重点」） |
| 迁移不可重跑 | 第二次启动直接炸 | 部署的人 |

R4-BOUNDARY-JUSTIFICATION: 本判据只**读文本**（backend 的模型 / Schema / 服务 / 端点 / 迁移，
加一个单测文件），不连库、不起服务、不写任何文件；反向验证
_reverse_verify_notification_severity.py 注入后逐字节还原。

判据口径（本仓库既有约定）：
  1. 认**代码形状**不认文字：先剥注释与三引号，再看结构（散文骗过判据的坑踩过）；
  2. 关键函数体与规则表用**原文切片**（不剥注释）；切片为空必须让调用方自己 ok(...) 报红
     —— 本仓库被「清单为空 ⇒ 检查恒真」坑过多次；
  3. 每条 ok() 的失败文案互不相同（红了要能一眼看出是哪一条）。

用法：
    python _tools/qa/_check_notification_severity.py              # 查当前树
    python _tools/qa/_check_notification_severity.py <另一棵树>    # 反向验证用
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]

MODEL = ROOT / "backend/app/models/notification.py"
SCHEMA = ROOT / "backend/app/schemas/notification.py"
CENTER = ROOT / "backend/app/services/message_center.py"
API = ROOT / "backend/app/api/v1/notifications.py"
MIGRATION = ROOT / "backend/app/migrations/032_notification_severity.py"
TEST = ROOT / "backend/tests/test_notification_severity.py"
APP_DIR = ROOT / "backend/app"

#: 判定表至少要有这么多行（低于它说明表被清空 / 取法失效，不是「通过」）。
MIN_TYPES = 30
#: 代码里至少能扫到这么多 type 字面量（扫不到说明取法失效）。
MIN_LITERALS = 20
#: 单测至少这么多条（任务书要求 ≥6）。
MIN_TESTS = 6

PASS = 0
FAIL: list[str] = []


def ok(cond: bool, msg: str) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(msg)


def read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def code_only(src: str) -> str:
    """剥掉注释与三引号（认代码形状，不认我们自己写的说明文字）。"""
    src = re.sub(r'"""[\s\S]*?"""', "", src)
    src = re.sub(r"'''[\s\S]*?'''", "", src)
    return re.sub(r"^[ \t]*#.*$", "", src, flags=re.M)


def region(src: str, signature: str, end_marker: str) -> str:
    """取**原文切片**：找不到返回空串（调用方必须自己 ok(...) 报红）。"""
    i = src.find(signature)
    if i < 0:
        return ""
    j = src.find(end_marker, i + len(signature))
    return src[i:] if j < 0 else src[i:j]


def func(src: str, name: str) -> str:
    return region(src, "def " + name + "(", "\n\ndef ")


def table_rows(src: str, header: str) -> dict[str, str]:
    """把「名字: dict[...] = { ... }」那张表读成 {键: 值文本}。"""
    body = region(src, header, "\n}")
    rows: dict[str, str] = {}
    for line in body.splitlines():
        # 表里的行**带行尾注释**（分级理由写在右边）→ 先切掉注释再认结构。
        # ⚠️ 不切的话「带注释的那几行」会被静默漏掉（写这个判据时自己踩过一次：
        #    预留的 stock.low 那几行被读成 None，判据红了但红的是判据自己）。
        line = line.split("#", 1)[0]
        m = re.match(r'\s*"([a-z0-9_.]+)":\s*(\S+?),?\s*$', line)
        if m:
            rows[m.group(1)] = m.group(2)
    return rows


model_src = read(MODEL)
schema_src = read(SCHEMA)
center_src = read(CENTER)
api_src = read(API)
mig_src = read(MIGRATION)
test_src = read(TEST)

model_code = code_only(model_src)
center_code = code_only(center_src)
api_code = code_only(api_src)
schema_code = code_only(schema_src)

# ── 0. 先证明切片非空（否则下面全是假红/假绿）─────────────────────────────────
col = region(model_src, "severity: Mapped[str] = mapped_column(", "\n    )")
sev_default = region(model_src, "def severity_default(", "\n\nclass ")
sev_rule = func(center_src, "severity_for")
emph_rule = func(center_src, "emphasis_for")
emph_payload = func(center_src, "emphasis_payload")
factory = func(center_src, "create_message")
out_model = region(schema_src, "class NotificationOut(", "\nclass ")
sev_table = table_rows(center_src, "SEVERITY_BY_TYPE: dict[str, str] = {")
emph_table = table_rows(center_src, "EMPHASIS_BY_TYPE: dict[str, tuple[str, ...]] = {")

ok(bool(model_src) and bool(schema_src) and bool(center_src) and bool(api_src),
   "读不到 backend 的四个文件（路径变了？检查脚本顶部的路径常量）")
ok(bool(col), "模型里没有 severity 列（severity: Mapped[str] = mapped_column 切片为空）")
ok(bool(sev_default), "模型里没有 def severity_default( —— 列默认值的按 type 现算没了")
ok(bool(sev_rule), "message_center 里没有 def severity_for( —— **唯一的那处判定**不见了")
ok(bool(emph_rule), "message_center 里没有 def emphasis_for(")
ok(bool(emph_payload), "message_center 里没有 def emphasis_payload(")
ok(bool(factory), "message_center 里没有 def create_message(")
ok(bool(out_model), "Schema 里没有 class NotificationOut(")
ok(len(sev_table) >= 2, "读不出 SEVERITY_BY_TYPE 的行（表头写法变了？）")
ok(len(emph_table) >= 2, "读不出 EMPHASIS_BY_TYPE 的行（表头写法变了？）")

# ── 1. 词汇表与列（models/notification.py）───────────────────────────────────
for name, value in (("SEVERITY_INFO", "info"), ("SEVERITY_WARN", "warn"), ("SEVERITY_DANGER", "danger")):
    ok(bool(re.search(r'^%s = "%s"$' % (name, value), model_code, re.M)),
       '模型里的 %s 必须是 "%s"（三档词汇表是整件事的底座）' % (name, value))
ok(bool(re.search(r"^SEVERITY_VALUES: tuple\[str, \.\.\.\] = \(", model_code, re.M)),
   "模型里没有 SEVERITY_VALUES（合法取值元组，Schema 的出参描述要用它）")

ok("String(8)" in col, "severity 列不是 String(8)（三档最长 danger=6，8 是留白）")
ok("index=True" in col, "severity 列没有 index=True（按严重度筛消息会全表扫）")
ok("default=severity_default" in col,
   "severity 列没有挂 default=severity_default —— 绕过工厂的构造路径会拿不到正确的档")
ok('server_default=text("\'info\'")' in col,
   "severity 列没有 server_default=info（裸 SQL 插入 / 不走 ORM 的行会是 NULL）")

ok("from app.services.message_center import severity_for" in sev_default,
   "severity_default 没有委托给 message_center.severity_for（那就成了第二处判定）")
ok('return severity_for(params.get("type"))' in sev_default,
   "severity_default 没有按**当前行的 type** 现算（写死 info 就等于绕过工厂的都掉进 info）")

# ── 2. 判定**只有一处** ──────────────────────────────────────────────────────
app_files = sorted(p for p in APP_DIR.rglob("*.py"))
defs = [str(p.relative_to(ROOT)).replace("\\", "/") for p in app_files if "def severity_for(" in read(p)]
ok(defs == ["backend/app/services/message_center.py"],
   "def severity_for( 必须**只在** backend/app/services/message_center.py 出现一次，实际：" + repr(defs))

hard_coded = ["%s:%d" % (p.relative_to(ROOT), i) for p in app_files
              for i, line in enumerate(read(p).splitlines(), 1)
              if re.search(r'severity\s*[:=]\s*["\']', line)]
ok(not hard_coded,
   "不许在任何调用点写死严重度（判定的入口只有 severity_for）：" + ", ".join(hard_coded[:5]))

ok('SEVERITY_BY_TYPE.get(str(message_type or "").strip(), SEVERITY_INFO)' in sev_rule,
   "severity_for 必须查表并以 info 兜底（查不到 = 普通消息，不是假装很危险）")

# ── 3. 判定表覆盖：代码里出现的每个 type 都要有名有姓 ─────────────────────────
constructors = [p for p in app_files if "Notification(" in read(p)]
ok(len(constructors) >= 3, "扫到的通知构造文件太少（%d 个）—— 发现规则可能失效了" % len(constructors))
literals: set[str] = set()
for p in constructors:
    literals |= set(re.findall(r'(?<![_\w])type_?\s*=\s*"([a-z0-9_.]+)"', code_only(read(p))))
ok(len(literals) >= MIN_LITERALS,
   "只扫到 %d 个 type 字面量（< %d）—— 本节的取法失效了，先修判据" % (len(literals), MIN_LITERALS))
missing = sorted(t for t in literals if t not in sev_table)
ok(not missing, "这些 type 在代码里出现、却没在 SEVERITY_BY_TYPE 里登记（会安静地掉进 info）：" + ", ".join(missing))
ok(len(sev_table) >= MIN_TYPES,
   "SEVERITY_BY_TYPE 只有 %d 行（< %d）—— 表被清空了？" % (len(sev_table), MIN_TYPES))

# 三个 *_dispatcher 的 type 是**位置参数**传进 _broadcast_to_dispatchers 的（不是 type= 字面量），
# 上面的扫描扫不到它们 —— 单独钉住，免得被悄悄删掉或改档。
for t in ("order.delivered_dispatcher", "order.driver_ack_dispatcher", "order.cancelled_dispatcher"):
    ok(t in sev_table, "%s 没有在 SEVERITY_BY_TYPE 里登记（位置参数传的，扫描扫不到，只能在这里钉）" % t)

# 四类档位（任务书要求的口径）
for t, want in (("order.assigned", "SEVERITY_INFO"), ("order.delivered", "SEVERITY_INFO"),
                ("order.revoked", "SEVERITY_WARN"), ("order.deleted", "SEVERITY_WARN"),
                ("order.returned", "SEVERITY_WARN"), ("order.return_request", "SEVERITY_WARN"),
                ("stock.low", "SEVERITY_DANGER"), ("payable.overdue", "SEVERITY_DANGER"),
                ("payable.due_soon", "SEVERITY_WARN"), ("arrears.over_limit", "SEVERITY_DANGER"),
                ("account.new_device_login", "SEVERITY_DANGER"), ("system.notice", "SEVERITY_INFO")):
    ok(sev_table.get(t) == want, "%s 的档位必须是 %s，实际是 %r" % (t, want, sev_table.get(t)))
ok(bool(sev_table) and all(v.startswith("SEVERITY_") for v in sev_table.values()),
   "SEVERITY_BY_TYPE 里出现了裸字符串档位（必须引用 SEVERITY_* 常量，否则词汇表会被绕开）")

# ── 4. 工厂出口（severity + emphasis 都从这里出去）───────────────────────────
ok("emphasis: tuple[str, ...] | list[str] | None = None" in factory,
   "create_message 没有 emphasis 参数（发消息那一侧就没法把金额/人名交给重点词表）")
ok("severity=severity_for(type)" in factory,
   "create_message 没有 severity=severity_for(type)（工厂出口没盖档）")
ok("payload=emphasis_payload(payload, type, title, content, emphasis)" in factory,
   "create_message 没有把 payload 过一遍 emphasis_payload（重点词写不进 payload）")

# ── 5. 重点词：三条不许（用户否掉「整行上色」）───────────────────────────────
ok("if word not in text:" in emph_rule and "continue" in emph_rule,
   "emphasis_for 少了『正文/标题里找不到就一个都不标』那道闸")
ok('word == (title or "").strip() or word == (content or "").strip()' in emph_rule,
   "emphasis_for 少了『整条标题 / 整段正文不许当重点词』那道闸（那就是整行上色）")
ok("len(word) > MAX_EMPHASIS_CHARS" in emph_rule,
   "emphasis_for 少了长度闸（一句整话会被当成一个重点词）")
ok("out[:MAX_EMPHASIS]" in emph_rule,
   "emphasis_for 没有按 MAX_EMPHASIS 截断（全是重点就是没有重点）")
ok('payload.get("order_no")' in emph_payload,
   "emphasis_payload 没有把 payload 里的单号自动补成重点词候选")
ok("if not words and payload is None:" in emph_payload and "return None" in emph_payload,
   "emphasis_payload 会把没有重点词的 None payload 变成空字典 ——「没有 payload 就只读」的口径会被改掉")
ok('out["emphasis"] = words' in emph_payload, "emphasis_payload 没有写 payload 的 emphasis 键")
ok(emph_table.get("price_change") == '("价格调整",)',
   "价格调整那一类的重点词没了（价格卡的新价要靠这一类）")
for t in ("stock.low", "payable.overdue", "account.new_device_login"):
    ok(t in emph_table, "%s 没有重点词行（危险类一个字都不点，等于白做分级）" % t)

# ── 6. 出参（NotificationOut 必须带 severity）────────────────────────────────
ok("from app.models.notification import SEVERITY_INFO, SEVERITY_VALUES" in schema_code,
   "Schema 没有从模型引入档位词汇表（出参的默认值/描述必须与模型同一处来源）")
ok("severity: str = Field(" in out_model, "NotificationOut 里没有 severity 字段 —— App 拿不到档")
ok("default=SEVERITY_INFO" in out_model, "NotificationOut.severity 的默认值不是 SEVERITY_INFO")
ok('" | ".join(SEVERITY_VALUES)' in out_model,
   "NotificationOut.severity 的描述没有从 SEVERITY_VALUES 生成（会漂移成第二份词汇表）")

# ── 7. 端点：只许调用助手，不许自己定档，也不许丢老字段 ──────────────────────
price_notify = region(api_src, "def notify_price_change(", "\n@router.")
ok(bool(price_notify), "找不到 notify_price_change（端点被改名了？）")
ok("emphasis_payload(" in price_notify, "价格通知没有走 emphasis_payload（新价不会被点名）")
ok('"old_price": old_s' in price_notify and '"new_price": str(body.new_price)' in price_notify,
   "价格通知的 payload 丢了老字段（旧 H5 的 ShipperPriceNoticeBar.vue 在读它们）")
ok("severity=" not in api_code, "api/v1/notifications.py 里出现了 severity= —— 判定被搬到了调用点")

# ── 8. 迁移（可重跑 + 默认 info + 索引单独建）────────────────────────────────
ok(MIGRATION.exists(), "迁移 backend/app/migrations/032_notification_severity.py 不存在")
ok("VERSION = 32" in mig_src, "迁移 032 的 VERSION 不是 32")
ok(bool(re.search(r"ALTER TABLE notifications ADD COLUMN severity VARCHAR\(8\)", mig_src)),
   "迁移没有给 notifications 加 severity VARCHAR(8)")
ok("NOT NULL DEFAULT 'info'" in mig_src, "迁移的 severity 列不是 NOT NULL DEFAULT info")
ok("CREATE INDEX ix_notifications_severity" in mig_src,
   "迁移没有单独建 ix_notifications_severity（SQLite 不支持 ALTER 带索引，必须分开）")
ok('"severity" not in' in mig_src, "迁移没有『列已存在就跳过』那道闸（不可重跑）")
ok(mig_src.count("inspect(engine)") >= 2,
   "迁移在 ALTER 之后没有重新看一眼 inspector（第二次启动会重复建索引）")

# ── 9. 单测（任务书要求 ≥6 条，四类档位 + 默认值 + 出参）──────────────────────
tests = re.findall(r"^def test_[a-z0-9_]+\(", test_src, re.M)
ok(len(tests) >= MIN_TESTS, "单测只有 %d 条（< %d）" % (len(tests), MIN_TESTS))
ok('"/api/v1/notifications"' in test_src, "单测没有验证 GET /notifications 的出参真的带 severity")
for want in ('== "danger"', '== "warn"', '== "info"'):
    ok(want in test_src, "单测里没有 %s 这一档的断言" % want)

print("PASS =", PASS)
if FAIL:
    print("")
    for i, msg in enumerate(FAIL, 1):
        print("  [x] %d. %s" % (i, msg))
    print("")
    print("FEAT-0019 消息分级：%d 条判据红了 —— 上面每一条都对应一条用户口径。" % len(FAIL))
    sys.exit(1)
print("== FEAT-0019 消息分级：%d 条判据全绿（判定只有一处、表覆盖代码里每个 type、"
      "出参带 severity、重点词不过滤不标、迁移可重跑）。" % PASS)
