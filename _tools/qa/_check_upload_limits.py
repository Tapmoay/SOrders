"""红线：**收了上传文件的端点必须"限量读"**，不许先把整个请求体读进内存再判大小。

## 由来（2026-09-23 全项目复核 G8）

复核时按 `UploadFile` 数了一遍：后端收了上传文件的函数一共 6 个，其中 **5 个**是同一种写法 ——

```python
raw = await file.read()                 # ← 先把整个请求体读进内存
if len(raw) > 4 * 1024 * 1024:          # ← 然后才判"太大"
    raise HTTPException(400, "图片过大")
```

这种写法的"上限"挡的是**读进内存之后**的处理，**挡不住内存本身**：客户端传一个 2GB 的 xlsx，
进程先被撑到 OOM（生产 2 个 worker，一个被打死就掉一半容量），然后才轮到那句"文件过大"。
生产前面有 nginx `client_max_body_size 32m` 兜着，所以外部能打到的最大是 32MB；
但**本机直连 uvicorn 时没有任何上限**，而 AI 的附件通道正好走这条路。

正确写法只有一个：`app/core/upload_read.py::read_limited(file, limit)` ——
`file.read(limit + 1)`：内存占用恒定 ≤ 上限+1，多读的那 1 字节只用来分辨
"刚好等于上限"（允许）与"超过上限"（拒绝）。

## 判据（清单自己算，不手写）
1. 扫 `backend/app/**/*.py`，凡是**签名里出现 `UploadFile`** 的函数 = 上传相关函数（清单自动发现）；
2. 每个这样的函数**要么**函数体里调用了 `read_limited(`，**要么**在下面的 [DELEGATES] 里
   写清"转发给谁、那边为什么管得住"；
3. 判据本身也不许被掏空：`upload_read.py` 里必须有 `read(limit + 1)` 与那句越界 raise，
   否则"所有调用点都合规"就是一句空话（调一个不设防的函数也叫合规）；
4. 豁免表不许变化石（键必须仍是"上传相关函数"）、不许变长、理由不许是占位符；
5. 数量判据：上传相关函数 ≥ 5 个、直接限量读的 ≥ 4 个（解析失效/清单过期时先喊）。

用法：python _tools/qa/_check_upload_limits.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "backend/app"
UPLOAD_READ = APP / "core/upload_read.py"

#: 自己收 `UploadFile`、但把文件**转交**给别人处理的函数 → 理由（必须说清"那边为什么管得住"）。
#: 目前只有"送货照片/补地点图的端点 → `_save_delivery_uploads`"这一处转发。
DELEGATES: dict[str, str] = {
    "complete_order_with_upload":
        "把 files 转交给 _save_delivery_uploads（它自己是限量读的，见同一文件）",
    "upload_delivery_photos":
        "把 files 转交给 _save_delivery_uploads（它自己是限量读的，见同一文件）",
}
#: 限量读的**实现本身**（它当然"没有调用自己"）：由判据 ② 单独钉它的内容和上限。
IMPLEMENTATION_FUNC = "read_limited"
MAX_DELEGATES = 3
MIN_UPLOAD_FUNCS = 5
MIN_LIMITED_FUNCS = 4

FUNC_DEF = re.compile(r"^(?:async )?def (\w+)\s*\(")
#: ⚠️ **必须带 `await`**（2026-09-23 活体验证当场抓到的假绿）：
#:    只查 `read_limited(` 的话，漏掉 `await` 也照样绿 —— 而它的真实后果是端点 **500**
#:    （`len(<coroutine>)` TypeError）。这不是假想：我自己在 `files.py` 上就漏过一次，
#:    四条静态检查全绿、活体探针一打就 500。判据要锚在**能跑的写法**上，不是"名字出现过"。
LIMITED = re.compile(r"\bawait\s+read_limited\(")


def strip_lines(lines: list[str]) -> list[str]:
    """逐行剥注释与文档字符串（保留行数）。

    ⚠️ 必须剥：每个改过的调用点上面都留着一句注释 **原文引用了旧写法**
    `await file.read()` —— 不剥的话这条检查会被我们自己的说明文字喂饱。
    """
    out: list[str] = []
    in_doc: str | None = None
    for ln in lines:
        if in_doc is not None:
            if in_doc in ln:
                in_doc = None
            out.append("")
            continue
        s = ln.strip()
        if s.startswith('"""') or s.startswith("'''"):
            q = s[:3]
            if s.count(q) < 2:
                in_doc = q
            out.append("")
            continue
        out.append(re.sub(r"#.*$", "", ln))
    return out


def scan() -> tuple[list[tuple[str, str, bool]], int]:
    """返回 ([(文件, 函数名, 是否限量读)], 扫到的文件数)。"""
    found: list[tuple[str, str, bool]] = []
    files = 0
    for f in sorted(APP.rglob("*.py")):
        files += 1
        keep = strip_lines(f.read_text(encoding="utf-8").splitlines())
        rel = str(f.relative_to(ROOT))
        name: str | None = None
        sig: list[str] = []
        seg: list[str] = []
        in_sig = False
        for i, ln in enumerate(keep):
            m = FUNC_DEF.match(ln)
            if m:
                if name is not None and any("UploadFile" in x for x in sig):
                    found.append((rel, name, any(LIMITED.search(x) for x in seg)))
                name, sig, seg, in_sig = m.group(1), [ln], [], not ln.rstrip().endswith(":")
                continue
            if name is None:
                continue
            if in_sig:
                sig.append(ln)
                if ln.rstrip().endswith(":"):
                    in_sig = False
                continue
            seg.append(ln)
        if name is not None and any("UploadFile" in x for x in sig):
            found.append((rel, name, any(LIMITED.search(x) for x in seg)))
    return found, files


def main() -> int:
    fails: list[str] = []
    funcs, files = scan()
    limited = [f for f in funcs if f[2]]
    print(f"扫了 {files} 个 .py：收了上传文件的函数 {len(funcs)} 个，其中限量读的 {len(limited)} 个")
    for rel, name, ok in funcs:
        if ok:
            mark = "✓ 限量读"
        elif name in DELEGATES:
            mark = "（转发）"
        elif name == IMPLEMENTATION_FUNC:
            mark = "（限量读的实现本身，判据 ② 单独钉它）"
        else:
            mark = "❌ 没有上限地读"
        print(f"   · {rel:38} {name:32} {mark}")

    # ① 每个上传函数要么自己限量读，要么写明转发（实现本身除外，判据 ② 单独钉它）
    offenders = [
        f"{rel}::{name}"
        for rel, name, ok in funcs
        if not ok and name not in DELEGATES and name != IMPLEMENTATION_FUNC
    ]
    if offenders:
        fails.append(
            "这些函数收了上传文件却**没有限量读**（会把整个请求体先读进内存）："
            + "、".join(offenders)
            + " —— 改成 `await read_limited(file, 上限)`（app/core/upload_read.py）"
        )

    # ② 判据本身：upload_read.py 必须真的设了上限
    guard = UPLOAD_READ.read_text(encoding="utf-8") if UPLOAD_READ.exists() else ""
    if not guard:
        fails.append(f"{UPLOAD_READ.relative_to(ROOT)} 不存在 —— 限量读的唯一实现被删了")
    else:
        if not re.search(r"file\.read\(limit \+ 1\)", guard):
            fails.append("upload_read.py 里不再是「读 limit+1 字节」（上限判据被改坏了）")
        if not re.search(r"if len\(raw\) > limit:", guard):
            fails.append("upload_read.py 里没有越界就拒绝那一句（读了也不拦）")

    # ③ 豁免表：不许变化石、不许变长、理由要真的是一句话
    names = {name for _rel, name, _ok in funcs}
    fossils = [n for n in DELEGATES if n not in names]
    if fossils:
        fails.append("DELEGATES 里的函数已经不存在了（化石条目）：" + "、".join(fossils))
    thin = [n for n, why in DELEGATES.items() if len(why.strip()) < 15]
    if thin:
        fails.append("DELEGATES 的理由太短、等于没写：" + "、".join(thin))
    if len(DELEGATES) > MAX_DELEGATES:
        fails.append(f"DELEGATES 有 {len(DELEGATES)} 条（上限 {MAX_DELEGATES}）——这个口子开太大了")
    # 豁免的必须**真的**是"没自己限量读"的那些（自己读了的挂在表上＝假豁免）
    lying = [n for n in DELEGATES if any(x[1] == n and x[2] for x in funcs)]
    if lying:
        fails.append("这些函数其实自己就限量读了，却还挂在 DELEGATES 上（假豁免）：" + "、".join(lying))

    # ④ 数量判据（防空转/清单过期）
    if len(funcs) < MIN_UPLOAD_FUNCS:
        fails.append(f"只认出 {len(funcs)} 个上传相关函数（<{MIN_UPLOAD_FUNCS}）——判据可能已空转")
    if len(limited) < MIN_LIMITED_FUNCS:
        fails.append(f"只有 {len(limited)} 个是限量读（<{MIN_LIMITED_FUNCS}）——判据可能已空转")

    if fails:
        print("\n❌ 上传读取不设防：")
        for f in fails:
            print("   - " + f)
        print("\n（上限必须在**读之前**生效：`file.read(n)` 最多读 n 字节。）")
        return 1
    print(
        f"\n✅ {len(funcs)} 个上传相关函数都有上限：{len(limited)} 个自己限量读，"
        f"{len(DELEGATES)} 个转发给已限量读的辅助函数。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
