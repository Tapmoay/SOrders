"""红线：**PATCH 体里「有非空默认值」的字段必须显式回填**（2026-09-19 审计「声明式 CRUD」专项 W1 形状）。

## 缺陷形状（本轮真抓到的一条，高）
`AiWriteService.updateAddress` 用 `AddressCreateRequest` 当 PATCH 体，但没传 `imageUrls`：

```kotlin
AddressCreateRequest(receiverName = …, phone = …, detailAddress = …, remark = …,
                     isDefault = …, addressLat = …, addressLng = …, originAddress = …)
```

而 `AddressCreateRequest.imageUrls` 的默认值是 **`emptyList()`（非空默认值）**，
`ApiClient` 的 Json 配置又是 **`encodeDefaults = true`** ——
于是"只改电话"的请求里**永远带着 `"image_urls": []`**，
后端 `_apply_images` 把 `[]` 当"清空"（只有 `None` 才是"不改"）→ **这条线路的照片全没了**，
卡片照样回「已完成」，而且撤回救不回来（`AiResources` 的 readKeys 里没有 image_urls）。

## 判据（清单自己算，不手写）
1. 从 `Dtos.kt` 解析出所有 `data class …Request` 的**非空默认值**字段
   （`= emptyList()` / `= ""` / `= 0` / `= false` …；`= null` 不算 —— `explicitNulls = false` 会把它省掉）；
2. 在 `ai/` 下找这些 DTO 的**构造点**；
3. 落在 `update*` / `patch*` 函数里的构造点，必须把该 DTO 的每个非空默认值字段**显式传值**
   （不显式传 = 把用户没提到的字段覆盖成默认值）；
4. 白名单里的例外要写清理由（例如"这个字段本来就该被这次更新重置"）。

用法：python _tools/qa/_check_ai_dto_defaults.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
DTOS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"
AI_DIR = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"

#: 允许"在 update* 里不显式传非空默认值字段"的例外 —— 键 `DTO.字段`，值=理由。
ALLOW: dict[str, str] = {}

fails: list[str] = []
passes = 0


def ok(label: str, cond: bool, detail: str = "") -> None:
    global passes
    if cond:
        passes += 1
        print(f"  [OK]   {label}")
    else:
        fails.append(label + (f" —— {detail}" if detail else ""))
        print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))


def strip_kt(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)^\s*//.*$", "", src)
    # ⚠️ 注解里的括号会把"配平括号找 data class 参数表"这件事带偏：
    #    `@SerialName("x") val a: String = ""` 的第一个 `)` 会被当成参数表的收尾，
    #    于是**参数表在第一个带注解的字段处就被截断**（实测：给 DTO 末尾加一个字段，
    #    判据完全没反应 —— 反向验证抓到的）。这里把注解换成等长空格，缩进/行号都不动。
    src = re.sub(r"@\w+(\([^)]*\))?", lambda m: " " * len(m.group(0)), src)
    return src


def dto_nonnull_defaults() -> dict[str, set[str]]:
    """{DTO 名: {非空默认值字段}}。"""
    src = strip_kt(DTOS.read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for m in re.finditer(r"data class (\w*Request)\(", src):
        name = m.group(1)
        # 取这个 data class 的括号内参数列表
        i = m.end() - 1
        depth = 0
        for j in range(i, len(src)):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    body = src[i + 1 : j]
                    break
        else:
            continue
        fields: set[str] = set()
        for fm in re.finditer(r"\bval (\w+)\s*:\s*([^=,\n]+?)\s*=\s*([^,\n]+)", body):
            fname, ftype, default = fm.group(1), fm.group(2), fm.group(3).strip()
            if default == "null":
                continue  # null 默认值会被 `explicitNulls = false` 省掉，不会误覆盖
            fields.add(fname)
        if fields:
            out[name] = fields
    return out


def kt_functions(src: str) -> list[tuple[str, str]]:
    """[(函数名, 函数体)]。"""
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"\n\s*(?:override\s+)?(?:suspend\s+)?fun (\w+)\s*\(", src):
        name = m.group(1)
        rest = src[m.end() :]
        # 函数体到下一个同缩进的 fun / 结尾
        nxt = re.search(r"\n\s{4}(?:override\s+)?(?:suspend\s+)?fun \w+\s*\(", rest)
        out.append((name, rest[: nxt.start()] if nxt else rest))
    return out


def main() -> int:
    if not DTOS.exists() or not AI_DIR.exists():
        print("❌ 找不到 Dtos.kt 或 ai/ 目录（路径改了？判据要跟着改，不许静默跳过）")
        return 1
    defaults = dto_nonnull_defaults()
    ok("从 Dtos.kt 解析出 >=5 个带非空默认值的 *Request（防解析失效后空转）",
       len(defaults) >= 5, f"实际 {len(defaults)}：{sorted(defaults)[:6]}")

    sites = 0
    for p in sorted(AI_DIR.rglob("*.kt")):
        src = strip_kt(p.read_text(encoding="utf-8", errors="replace"))
        for fname, body in kt_functions(src):
            if not (fname.startswith("update") or fname.startswith("patch")):
                continue
            for dto, fields in defaults.items():
                for ctor in re.finditer(rf"\b{dto}\(", body):
                    # 收集这个构造调用里显式传的字段名
                    i = ctor.end() - 1
                    depth = 0
                    for j in range(i, len(body)):
                        if body[j] == "(":
                            depth += 1
                        elif body[j] == ")":
                            depth -= 1
                            if depth == 0:
                                args = body[i + 1 : j]
                                break
                    else:
                        continue
                    sites += 1
                    passed = set(re.findall(r"(\w+)\s*=", args))
                    missing = sorted(
                        f for f in fields if f not in passed and f"{dto}.{f}" not in ALLOW
                    )
                    ok(
                        f"{p.name}::{fname} 里 {dto} 的每个非空默认值字段都显式回填"
                        f"（{len(fields)} 个）",
                        not missing,
                        "没回填：" + "、".join(missing)
                        + "（`encodeDefaults=true` 会把默认值永远发出去 → 把用户没提到的字段覆盖掉）",
                    )
    ok("扫到 >=1 个 update*/patch* 里的 DTO 构造点（清单自己算，防路径写错后空转）",
       sites >= 1, f"实际 {sites}")

    print("\n" + "=" * 60)
    if fails:
        print(f"❌ {len(fails)} 项不通过：")
        for f in fails:
            print("   - " + f[:200])
        return 1
    print(f"✅ 全部 {passes} 项通过：PATCH 体不会把没提到的字段覆盖成默认值。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
