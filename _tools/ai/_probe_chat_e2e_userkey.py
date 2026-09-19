"""端到端验证：真 DeepSeek key + 真后端 + 真工具循环，跑用户的目标场景。

为什么要有它：App 里的循环与这里**逻辑同构**（同样的工具集、同样的 8 轮上限、
同样的消息序列）。用它在命令行先验证"问题→选对工具→拿到真数据→答对人话"，
这样打开 App 实测时已知后端与工具链路是通的，能把问题范围缩到"手机端 UI/KeyStore"。

协议事实（已实测，勿改）：
  * 思考开关用 `thinking:{"type":"enabled"|"disabled"}`；`reasoning_effort` 会被静默忽略。
  * 模型名：deepseek-flash / deepseek-v4-pro。

用法：
  python _probe_chat_e2e.py              # 跑全部场景
  python _probe_chat_e2e.py --no-think   # 关思考（省 token）
  python _probe_chat_e2e.py --only 库存   # 只跑名字含"库存"的场景
"""
import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

BACKEND = "http://127.0.0.1:8000/api/v1"
LLM_BASE = "https://api.deepseek.com"
MODEL = "deepseek-flash"
TEST_PHONE = "13900000001"
DB = repo_root() / "backend" / "sorders.db"

# ---- 工具定义：与 App 端 ai/AiTools.kt 的 5 个只读工具一一对应 ----
TOOLS = [
    ("search_shipper", "按姓名或手机号模糊查找货主/司机等用户，返回 id、姓名、角色。当用户说某人名但你不确定是哪个人时先用它。",
     {"q": {"type": "string", "description": "姓名或手机号的一部分"}, "role": {"type": "string", "enum": ["shipper", "driver", "dispatcher"]}}),
    ("inventory_alerts", "列出库存已经降到报警阈值的商品（库存 <= 阈值）。用户问「哪些货要补」「哪个到红线了」时用。", {}),
    ("driver_performance", "某时间段内司机的完成单数、准时率、待结运费。", {"date_from": {"type": "string"}, "date_to": {"type": "string"}}),
    ("shipper_performance", "某时间段内各货主的下单量与金额排行（只统计已送达订单）。", {"date_from": {"type": "string"}, "date_to": {"type": "string"}}),
    ("export_sheet", "导出报表为 Excel。kind 取值 turnover/products/drivers/customers/finance/audit。",
     {"kind": {"type": "string"}, "mode": {"type": "string", "enum": ["day", "week", "month"]}, "date": {"type": "string", "description": "锚点日期 YYYY-MM-DD"}}),
]

SYSTEM = (
    "你是 SOrders 派单系统的查询助手，用户是派单员。"
    "规则：① 只能通过工具查数据，禁止编造数字；② 用户提到人名但你没把握是哪个人时，先用 search_shipper 查；"
    "③ 如果问题需要当前工具答不了的条件，必须显式说明「我没包含 X」，不许给一个漏条件的答案；"
    "④ 回答用简体中文、口语化、不要 Markdown 表格；⑤ 数字后面带上单位与时间范围。"
    "今天是 2026-09-14。"
)


def llm_key() -> str:
    cred = Path.home() / ".dsh" / ".credentials.yaml"
    for line in cred.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "DEEPSEEK_API_KEY" in line and ":" in line:
            return line.split(":", 1)[1].strip().strip("'\"")
    raise SystemExit("取不到 DEEPSEEK_API_KEY")


def api_get(path: str, token: str):
    req = urllib.request.Request(f"{BACKEND}{path}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:200]
    except Exception as e:  # noqa: BLE001
        return -1, str(e)


def login() -> str:
    for phone, pwd in ((TEST_PHONE, "test1234"), ("13800000001", "123321")):
        req = urllib.request.Request(
            f"{BACKEND}/auth/login",
            data=json.dumps({"phone": phone, "password": pwd}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=20).read())
            if d.get("access_token"):
                return d["access_token"]
        except Exception:  # noqa: BLE001
            continue
    raise SystemExit("登录失败：本地后端是否在跑？账号密码是否已重置？")


def prune(obj, depth=0):
    """剪裁响应：限条数、剔除成本字段（与 App 端同一原则）。"""
    if depth > 4:
        return "…"
    if isinstance(obj, list):
        return [prune(x, depth + 1) for x in obj[:20]]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            lk = k.lower()
            if any(b in lk for b in ("cost", "profit", "margin")):
                continue
            out[k] = prune(v, depth + 1)
        return out
    return obj


def run_tool(name: str, args: dict, token: str) -> str:
    if name == "search_shipper":
        q = urllib.parse.quote(str(args.get("q", "")))
        role = args.get("role")
        path = f"/users?q={q}&limit=10" + (f"&role={role}" if role else "")
        code, data = api_get(path, token)
    elif name == "inventory_alerts":
        code, data = api_get("/inventory/summary?below_alert=true", token)
    elif name == "driver_performance":
        code, data = api_get(
            f"/stats/driver-performance?date_from={args.get('date_from')}&date_to={args.get('date_to')}", token
        )
    elif name == "shipper_performance":
        code, data = api_get(
            f"/stats/shipper-performance?date_from={args.get('date_from')}&date_to={args.get('date_to')}", token
        )
    elif name == "export_sheet":
        kind = args.get("kind", "turnover")
        mode = args.get("mode", "month")
        date = args.get("date", "2026-09-14")
        code, data = api_get(f"/reports/export?kind={kind}&mode={mode}&date={date}", token)
        return json.dumps({"ok": code == 200, "note": "导出请求已发出（文件流未下载）"}, ensure_ascii=False)
    else:
        return json.dumps({"error": f"未知工具 {name}"}, ensure_ascii=False)

    if code != 200:
        return json.dumps({"error": f"该能力暂不可用（HTTP {code}）"}, ensure_ascii=False)
    return json.dumps(prune(data), ensure_ascii=False)[:4000]


def call_llm(messages, key, think: bool):
    body = {
        "model": MODEL,
        "messages": messages,
        "tools": [
            {"type": "function",
             "function": {"name": n, "description": d,
                          "parameters": {"type": "object", "properties": p, "required": []}}}
            for n, d, p in TOOLS
        ],
        "tool_choice": "auto",
        "temperature": 0,
        "max_tokens": 1200,
        "thinking": {"type": "enabled" if think else "disabled"},
    }
    req = urllib.request.Request(
        f"{LLM_BASE}/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        return {"__error__": f"HTTP {e.code}: {e.read().decode('utf-8','ignore')[:300]}"}
    except Exception as e:  # noqa: BLE001
        return {"__error__": str(e)}


SCENARIOS = [
    ("库存红线", "有哪些商品库存到红线了？"),
    ("司机跑货", "这个月哪个司机跑的货最多？"),
    ("货主下单量", "这个月哪个货主下单最多？"),
    ("货主账单", "找一下名字里带 Shipper 的货主，看他这周的账单情况"),
    ("导出表格", "把这个月的货主账单导出成一张表格"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-think", action="store_true")
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    think = not a.no_think

    k = llm_key()
    token = login()
    print(f"✅ 登录成功（本地后端 {BACKEND}）")
    print(f"   模型={MODEL}  思考={'开' if think else '关'}\n")

    passed = 0
    todo = [s for s in SCENARIOS if not a.only or a.only in s[0]]
    for name, question in todo:
        print(f"=== {name}：{question}")
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
        used: list[str] = []
        answer = ""
        for step in range(1, 9):
            resp = call_llm(messages, k, think)
            if "__error__" in resp:
                print(f"   ❌ 模型调用失败: {resp['__error__']}")
                break
            msg = (resp.get("choices") or [{}])[0].get("message") or {}
            calls = msg.get("tool_calls") or []
            if msg.get("reasoning_content"):
                print(f"   💭 思考({len(msg['reasoning_content'])} 字)")
            if not calls:
                answer = (msg.get("content") or "").strip()
                break
            messages.append(msg)
            for c in calls:
                fn = (c.get("function") or {})
                nm = fn.get("name") or "?"
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except Exception:  # noqa: BLE001
                    args = {}
                used.append(nm)
                out = run_tool(nm, args, token)
                print(f"   🔧 第{step}步 {nm}({json.dumps(args, ensure_ascii=False)}) -> {out[:110]}…")
                messages.append({"role": "tool", "tool_call_id": c.get("id") or f"call_{step}", "content": out})
        else:
            print("   ⚠️ 达到 8 轮上限")

        if answer:
            passed += 1
            print(f"   ✅ 答复：{answer[:300]}")
            print(f"   工具调用：{used or '（未调用）'}")
        print()

    print(f"===== 合计 {passed}/{len(todo)} 个场景得到最终答复 =====")
    return 0 if passed == len(todo) else 1


if __name__ == "__main__":
    sys.exit(main())
