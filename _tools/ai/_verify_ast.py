"""Independent verification via ast (NOT the generator's line-regex).

Extracts every route decorator from backend/app/api/v1/*.py by walking the AST,
resolving the module APIRouter prefix, and dumping a canonical list.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402
import ast, json, re, sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = repo_root()   # ⛔ 不许写死本机路径：CI 在 /home/runner/... 上跑，写死 = 那个检查在外面永远不生效
API_DIR = ROOT / "backend" / "app" / "api" / "v1"

def const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None

def prefix_of(tree):
    # APIRouter(prefix="/x", ...) at any level; also supports prefix=VAR defined at module level
    varvals = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            v = const_str(n.value)
            if v is not None:
                varvals[n.targets[0].id] = v
    found = None
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = getattr(f, "id", None) or getattr(f, "attr", None)
            if name == "APIRouter":
                for kw in n.keywords:
                    if kw.arg == "prefix":
                        v = const_str(kw.value)
                        if v is None and isinstance(kw.value, ast.Name):
                            v = varvals.get(kw.value.id)
                        found = v
    return found

rows = []
prefixes = {}
for f in sorted(API_DIR.glob("*.py")):
    src = f.read_text(encoding="utf-8")
    tree = ast.parse(src)
    pre = prefix_of(tree)
    prefixes[f.stem] = pre
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in n.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            fn = dec.func
            if not isinstance(fn, ast.Attribute):
                continue
            if not (isinstance(fn.value, ast.Name) and fn.value.id == "router"):
                continue
            method = fn.attr
            paths = [const_str(a) for a in dec.args]
            paths = [p for p in paths if p is not None]
            if not paths:
                continue
            kwd = {k.arg: const_str(k.value) for k in dec.keywords}
            rows.append({
                "module": f.stem,
                "method": method.lower(),
                "raw_path": paths[0],
                "full_path": f"/api/v1{pre or ''}{paths[0]}",
                "handler": n.name,
                "at": f"backend/app/api/v1/{f.stem}.py:{n.lineno}",
                "decorator_line": dec.lineno,
                "responses": kwd,
            })

reads = [r for r in rows if r["method"] == "get"]
writes = [r for r in rows if r["method"] != "get"]
print(f"AST total={len(rows)}  GET(read)={len(reads)}  nonGET(write)={len(writes)}")
print(f"prefixes: {json.dumps(prefixes, ensure_ascii=False)}")

# modules with no prefix
nopre = [m for m, p in prefixes.items() if p is None and m not in ("__init__", "router")]
print("modules with NO resolvable prefix:", nopre)

# load generator output and diff
gen = json.loads((ROOT / "docs" / "ai" / "ai_toolmap.json").read_text(encoding="utf-8"))
grows = []
for mod, mv in gen["modules"].items():
    for a in mv["actions"]:
        grows.append({**a, "module": mod})
print(f"\nJSON total={len(grows)}  read={sum(1 for g in grows if g['risk']=='read')}  write={sum(1 for g in grows if g['risk']=='write')}")

def key(r):
    return (r["method"], r.get("full_path") or r.get("path"), r["handler"])

astset = {key(r): r for r in rows}
genset = {key(g): g for g in grows}
print(f"\nonly in AST (MISSING FROM JSON): {len(set(astset)-set(genset))}")
for k in sorted(set(astset) - set(genset)):
    print("   -", k, astset[k]["at"])
print(f"only in JSON (NOT IN CODE): {len(set(genset)-set(astset))}")
for k in sorted(set(genset) - set(astset)):
    print("   +", k, genset[k]["at"])

# line-number disagreements for same key
print("\nline/at mismatches on shared keys:")
bad = 0
for k in sorted(set(astset) & set(genset)):
    if astset[k]["at"] != genset[k]["at"]:
        bad += 1
        print(f"   {k}: AST={astset[k]['at']}  JSON={genset[k]['at']}")
print(f"   ({bad} mismatches)")

# risk misclassification
print("\nrisk mismatches:")
rm = 0
for k in sorted(set(astset) & set(genset)):
    want = "read" if astset[k]["method"] == "get" else "write"
    if genset[k]["risk"] != want:
        rm += 1
        print(f"   {k}: method={astset[k]['method']} JSON risk={genset[k]['risk']}")
print(f"   ({rm} mismatches)")

# module counts
from collections import Counter
print("\nper-module read/write (AST):")
c = Counter((r["module"], "read" if r["method"] == "get" else "write") for r in rows)
for m in sorted({r["module"] for r in rows}):
    print(f"   {m:<22} read={c[(m,'read')]:<3} write={c[(m,'write')]:<3}")

# duplicate full_path+method (route shadowing)
seen = {}
for r in rows:
    seen.setdefault((r["method"], r["full_path"]), []).append(r)
print("\nDUPLICATE (method, full_path) -- route shadowing:")
for k, v in sorted(seen.items()):
    if len(v) > 1:
        print(f"   {k}:")
        for x in v:
            print(f"      {x['handler']} @ {x['at']}")

# path params without type annotation
print("\npath params untyped (no ':type'):")
for r in rows:
    ps = re.findall(r"\{([^}]*)\}", r["full_path"])
    untyped = [p for p in ps if ":" not in p]
    if untyped:
        print(f"   {r['method'].upper():<6} {r['full_path']:<58} {untyped}")

# handler name collisions across modules
print("\nhandler names appearing in >1 module:")
hc = {}
for r in rows:
    hc.setdefault(r["handler"], set()).add(r["module"])
for h, ms in sorted(hc.items()):
    if len(ms) > 1:
        print(f"   {h}: {sorted(ms)}")

# same action+risk collision inside a module
print("\n(module, handler, risk) collisions:")
cc = Counter((r["module"], r["handler"], "read" if r["method"] == "get" else "write") for r in rows)
for k, n in sorted(cc.items()):
    if n > 1:
        print(f"   {k} x{n}")

json.dump(rows, open(ROOT / "_verify_ast.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
