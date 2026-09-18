"""端到端核对（打**本机真后端**，不碰生产）：

1. **消息「全部清空」到底删没删干净**（用户报的那个 bug：清空 → 重启 → 消息又回来了）。
   这个脚本用两个账号把它钉死：派单员清空**不能**动到货主的消息，而且清空之后
   再查一次必须是 0 条（老代码里派单员能看见所有人的消息，所以查回来还有别人的）。
2. **AI 附件**：上传一个真的 .xlsx 与一个 GBK 编码的 .csv，看服务端读出来的行/列/日期/整数。

用法（先起本地后端）：
    cd backend && python -m uvicorn app.main:app --port 8000
    python _tools/ai/_probe_messages_and_files.py
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

BASE = "http://127.0.0.1:8000/api/v1"
DISP_PHONE = "13900000001"
DISP_PWD = "123321"
SHIP_PHONE = "13800000002"
SHIP_PWD = "123321"

fails: list[str] = []


def check(ok: bool, label: str, extra: str = "") -> None:
    print(("  [OK]   " if ok else "  [FAIL] ") + label + (f"  {extra}" if extra else ""))
    if not ok:
        fails.append(label)


def req(method: str, path: str, token: str | None = None, body: dict | None = None, raw: bytes | None = None,
        content_type: str | None = None) -> tuple[int, object]:
    url = BASE + path
    data = raw if raw is not None else (json.dumps(body).encode("utf-8") if body is not None else None)
    r = urllib.request.Request(url, data=data, method=method)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if data is not None:
        r.add_header("Content-Type", content_type or "application/json")
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            payload = resp.read()
            try:
                return resp.status, json.loads(payload.decode("utf-8")) if payload else None
            except json.JSONDecodeError:
                return resp.status, payload
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload.decode("utf-8"))
        except Exception:
            return e.code, payload.decode("utf-8", errors="replace")


def login(phone: str, password: str) -> str:
    st, body = req("POST", "/auth/login", body={"phone": phone, "password": password})
    if st != 200 or not isinstance(body, dict):
        raise SystemExit(f"登录失败 {phone}: {st} {body}")
    return body["access_token"]


def multipart(field: str, filename: str, content: bytes, mime: str) -> tuple[bytes, str]:
    boundary = "----sordersprobe7f3a"
    buf = io.BytesIO()
    buf.write(f"--{boundary}\r\n".encode())
    buf.write(f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode())
    buf.write(f"Content-Type: {mime}\r\n\r\n".encode())
    buf.write(content)
    buf.write(f"\r\n--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def xlsx_bytes() -> bytes:
    from datetime import date

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "商品清单"
    ws.append(["商品名", "单位", "单价", "库存", "上架日期"])
    ws.append(["红富士苹果", "箱", 45.5, 120, date(2026, 9, 17)])
    ws.append(["海南香蕉", "件", 3, 0, date(2026, 9, 18)])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def main() -> int:
    print("== 1. 消息「全部清空」是否真的清干净 ==")
    disp = login(DISP_PHONE, DISP_PWD)
    ship = login(SHIP_PHONE, SHIP_PWD)

    # 给货主发两条（走真实的站内信端点），也给派单员自己发一条
    st, me_disp = req("GET", "/users/me", disp)
    st, me_ship = req("GET", "/users/me", ship)
    check(st == 200, "两个账号都能登录并取到自己", f"dispatcher={me_disp.get('id')} shipper={me_ship.get('id')}")

    for i in (1, 2):
        st, _ = req("POST", "/notifications", disp, body={
            "recipient_id": me_ship["id"], "category": "reminder", "type": "probe",
            "title": f"探针消息 {i}", "content": "这条消息属于货主，派单员清空时不该动它",
        })
        check(st == 201, f"给货主发第 {i} 条消息", f"{st}")
    st, _ = req("POST", "/notifications", disp, body={
        "recipient_id": me_disp["id"], "category": "reminder", "type": "probe",
        "title": "探针消息（派单员自己的）", "content": "这条属于派单员，清空时应当被删掉",
    })
    check(st == 201, "给派单员自己发一条消息", f"{st}")

    st, disp_list = req("GET", "/notifications", disp)
    check(st == 200, "派单员能查消息列表", f"{st}")
    ids = {n["recipient_id"] for n in disp_list} if isinstance(disp_list, list) else set()
    check(
        ids <= {me_disp["id"]},
        "派单员查列表**只看到自己的**（这就是那个 bug 的根因）",
        f"看到的收件人={sorted(ids)} 应为 {[me_disp['id']]}",
    )

    st, res = req("POST", "/notifications/batch-delete", disp, body={"all": True})
    check(st == 200, "派单员点「全部清空」", f"{st} {res}")

    st, after = req("GET", "/notifications", disp)
    check(
        st == 200 and isinstance(after, list) and len(after) == 0,
        "清空之后**再查一次是 0 条**（老代码这里会剩一堆别人的消息 → 重启就「回来」了）",
        f"剩 {len(after) if isinstance(after, list) else '?'} 条",
    )

    st, ship_list = req("GET", "/notifications", ship)
    mine = [n for n in ship_list if n["recipient_id"] == me_ship["id"]] if isinstance(ship_list, list) else []
    check(len(mine) >= 2, "货主的两条消息**一条都没被删**（清空不能跨账号）", f"货主看到 {len(mine)} 条")

    # 收尾：把货主那两条也删掉，别把探针数据留给他
    st, _ = req("POST", "/notifications/batch-delete", ship, body={"ids": [n["id"] for n in mine]})
    check(st == 200, "货主自己把那两条探针消息删掉（不留垃圾）", f"{st}")

    print("\n== 2. AI 附件：Excel / GBK CSV 读得对不对 ==")
    payload, ctype = multipart("file", "商品清单.xlsx", xlsx_bytes(),
                               "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st, out = req("POST", "/files/parse-sheet?max_rows=50", disp, raw=payload, content_type=ctype)
    ok = st == 200 and isinstance(out, dict) and out.get("tables")
    check(ok, "上传 .xlsx 能读出来", f"{st}")
    if ok:
        t = out["tables"][0]
        check(t["name"] == "商品清单", "工作表名带回来了", t["name"])
        check(t["rows"][0] == ["商品名", "单位", "单价", "库存", "上架日期"], "表头原样", str(t["rows"][0]))
        check(t["rows"][1][2] == "45.5" and t["rows"][1][3] == "120", "数字列读成文本且不丢精度", str(t["rows"][1]))
        check(t["rows"][1][4] == "2026-09-17", "日期不是序列号", str(t["rows"][1][4]))
        check(t["row_count"] == 3 and t["truncated"] is False, "行数正确且未截断", f"{t['row_count']}")

    gbk = "商品名,单价\n红富士苹果,45.5\n".encode("gb18030")
    payload, ctype = multipart("file", "货主导出.csv", gbk, "text/csv")
    st, out = req("POST", "/files/parse-sheet", disp, raw=payload, content_type=ctype)
    ok = st == 200 and isinstance(out, dict) and out.get("tables")
    check(ok, "上传 GBK 编码的 .csv 能读出来", f"{st}")
    if ok:
        check(out["tables"][0]["rows"][1][0] == "红富士苹果", "中文没变乱码", str(out["tables"][0]["rows"][1]))
        check(any("GBK" in w for w in out.get("warnings", [])), "编码是猜的要如实说", str(out.get("warnings")))

    payload, ctype = multipart("file", "老表.xls", b"\xd0\xcf\x11\xe0", "application/vnd.ms-excel")
    st, out = req("POST", "/files/parse-sheet", disp, raw=payload, content_type=ctype)
    check(st == 400 and "xlsx" in json.dumps(out, ensure_ascii=False), "旧版 .xls 拒绝并教用户怎么办", f"{st} {out}")

    st, out = req("POST", "/files/parse-sheet", ship, raw=payload, content_type=ctype)
    check(st == 400, "货主也能用这个接口（AI 对货主开放）", f"{st}")

    print("\n" + ("✅ 全部通过" if not fails else f"❌ {len(fails)} 条不通过：{fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
