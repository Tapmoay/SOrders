"""把后端所有写接口的「方法 / 路径 / 授权 / 请求体字段」抽成一张机读表。

### 为什么要有它
AI 写动作的每一处参数校验和摘要都依赖"后端到底收什么字段"。
手工一个文件一个文件读：慢、会漏、而且**改一次后端就要重读一遍**。
这里把事实一次性抽出来，写成 JSON，实现动作时照着它写；后端改了重跑一次即可。

用法：
    cd backend && python ../_tools/ai/_dump_write_endpoints.py
输出：
    docs/ai/write-endpoints.json   （机读）
    stdout                          （人读的摘要表）
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
API = BACKEND / "app" / "api" / "v1"
SCHEMAS = BACKEND / "app" / "schemas"
OUT = ROOT / "docs" / "ai" / "write-endpoints.json"

WRITE_METHODS = {"post", "patch", "put", "delete"}


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def pydantic_models(sources: dict[str, str]) -> dict[str, dict]:
    """从 schemas/*.py 里抽出所有 BaseModel 的字段（名 / 类型 / 必填 / 默认）。

    用 ast 而不是正则：Pydantic 里 `Field(None, ...)` 与 `= None` 的必填性不同，
    正则区分不了，而"哪个字段必填"恰恰是这一轮最不能搞错的东西。
    """
    models: dict[str, dict] = {}
    for fname, src in sources.items():
        for node in ast.walk(ast.parse(src)):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [getattr(b, "id", getattr(b, "attr", "")) for b in node.bases]
            if "BaseModel" not in bases:
                continue
            fields = []
            for st in node.body:
                if not isinstance(st, ast.AnnAssign) or not isinstance(st.target, ast.Name):
                    continue
                name = st.target.id
                ann = ast.unparse(st.annotation)
                required = True
                default = None
                if st.value is not None:
                    required = False
                    if isinstance(st.value, ast.Call) and getattr(st.value.func, "id", "") == "Field":
                        # Field(...) 的第一个参数是 ... 时为必填
                        if st.value.args and isinstance(st.value.args[0], ast.Constant) \
                                and st.value.args[0].value is Ellipsis:
                            required = True
                        else:
                            default = ast.unparse(st.value.args[0]) if st.value.args else None
                    else:
                        default = ast.unparse(st.value)
                fields.append({"name": name, "type": ann, "required": required, "default": default})
            models[node.name] = {"file": fname, "fields": fields}
    return models


def signature_after(src: str, pos: int) -> tuple[str, str] | None:
    """从 `pos` 往后找第一个函数定义，返回 `(函数名, 参数表原文)`；找不到返回 None。

    ## 为什么不能用一条正则（v3.43 修的真实缺陷）
    原来是 `\\n(?:async\\s+)?def (\\w+)\\((.*?)\\n\\)\\s*->` —— 它要求**参数表换行收尾**。
    于是 `def use_place(a: int, b: X = Depends(get_db)) -> Out:` 这种**单行签名**会被
    **静默跳过**：端点从 `write-endpoints.json` 里凭空消失，而覆盖率检查只看这张表，
    于是它报"没有缺口"。这类"清单少看了一个东西 → 结论变成没问题"是本仓库最忌讳的假绿。

    改成"数括号"的写法：从 `(` 开始按深度扫，深度回到 0 时看后面是不是 `->`。
    这样单行/多行、任意层嵌套（`Depends(require_permission(Permission.X))` 是两层）都对，
    而且**不会跨过函数边界**（正则版的一个真实风险：一层嵌套的规则遇到两层嵌套时，
    它会一路扫到下**一个**函数才收尾，把别人的名字安到这个路径上）。
    """
    m = re.search(r"\n(?:async\s+)?def (\w+)\(", src[pos:])
    if not m:
        return None
    name = m.group(1)
    i = pos + m.end()  # 停在 `(` 之后
    depth = 1
    start = i
    while i < len(src) and depth > 0:
        c = src[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    if depth != 0:
        return None
    sig = src[start:i]
    # 参数表收尾之后必须是 `->`（否则这不是一个带返回标注的函数定义，宁可不收）
    if not re.match(r"\s*->", src[i + 1: i + 8]):
        return None
    return name, sig


def handlers() -> list[dict]:
    """扫 api/v1/*.py，取每个写路由的方法、路径、函数名、请求体类型、授权依赖。"""
    out: list[dict] = []
    for path in sorted(API.glob("*.py")):
        src = read(path)
        prefix_m = re.search(r'APIRouter\(prefix="([^"]+)"', src)
        prefix = prefix_m.group(1) if prefix_m else ""
        for m in re.finditer(r"@router\.(post|patch|put|delete)\(\s*[\"']([^\"']*)[\"']", src):
            method, route = m.group(1), m.group(2)
            # 取这个装饰器之后的第一个 def。
            # ⚠️ `async def` 也必须认：少了 `(?:async )?` 的话，异步端点会被**跳过**，
            #    而正则继续往下找，于是把**下一个同步函数**的名字安到这个路径上
            #    （实测：`POST /shipper/locations/image` 的 handler 被写成了 `list_locations`）。
            #    路径是对的、名字是错的——这种"对了一半"的表最容易让人照着它写出错的东西。
            found = signature_after(src, m.end())
            if not found:
                continue
            fname, sig = found
            body = None
            bm = re.search(r"body:\s*(\w+)", sig)
            if bm:
                body = bm.group(1)
            auth = []
            if "require_permission(Permission." in sig:
                auth = re.findall(r"require_permission\(Permission\.(\w+)\)", sig)
            elif "require_roles(" in sig:
                auth = ["role:" + r for r in re.findall(r"UserRole\.(\w+)", sig)]
            elif "CurrentUser" in sig:
                auth = ["仅登录"]
            # 函数体里的角色/权限守卫
            body_src = src[m.end(): m.end() + 4000]
            if re.search(r"_must_dispatcher", body_src):
                auth.append("体内:派单员")
            if re.search(r"role_has_permission\(role, Permission\.(\w+)\)", body_src):
                auth += ["体内:" + p for p in re.findall(r"role_has_permission\(role, Permission\.(\w+)\)", body_src)]
            full = (prefix + route).replace("{order_id}", "{id}").replace("{shipper_id}", "{id}")
            out.append({
                "method": method.upper(),
                "path": "/api/v1" + full,
                "handler": fname,
                "file": f"{path.parent.name}/{path.name}",
                "line": src[: m.start()].count("\n") + 1,
                "body": body,
                "auth": auth or ["?须读源码"],
            })
    return out


def main() -> None:
    schema_src = {p.name: read(p) for p in SCHEMAS.glob("*.py")}
    models = pydantic_models(schema_src)
    hs = handlers()
    for h in hs:
        b = h.get("body")
        h["bodyFields"] = models.get(b, {}).get("fields") if b else None

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(hs, ensure_ascii=False, indent=1), encoding="utf-8")

    skip = ("/auth/",)
    hs = [h for h in hs if not any(s in h["path"] for s in skip)]
    print(f"写接口 {len(hs)} 个（已排除登录/注册），明细 -> {OUT.relative_to(ROOT)}\n")
    for h in hs:
        fields = h["bodyFields"]
        fs = ""
        if fields:
            fs = "  {" + ", ".join(
                ("*" if f["required"] else "") + f["name"] for f in fields
            ) + "}"
        elif h["body"]:
            fs = f"  <{h['body']} 未找到定义>"
        print(f"{h['method']:6} {h['path']:52} {h['handler']:34} {','.join(h['auth'])}{fs}")


if __name__ == "__main__":
    sys.exit(main())
