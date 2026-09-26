"""反向验证「读能力按角色裁剪」那几条检查**真的会红**（注入 bug → 必须报错）。

和 `_reverse_verify_ai_entry.py` 同一套思路：绿色的检查比没有检查更危险——没有检查时
你会去读代码拿一手真相，有假检查时你会相信绿灯直接动手。本脚本固定 6 种破坏方式：

  ① 服务侧不再问角色（读之前那一道门没了）
  ② 服务侧默认角色改成派单员（忘了传角色就静悄悄按派单员跑）
  ③ 角色闸门不按 roles 过滤（等于没裁）
  ④ 工具 enum 改回静态全量（说明裁了、可调集合没裁）
  ⑤ 生成物里的 roles 字段被删（手改机器生成的文件）
  ⑥ **端到端**：把生成器的角色推导改成"全给"，重新生成后跑实测对账脚本——必须报错
     （这一条验的是"角色表真的来自后端授权"，前五条都是静态文本检查）

用法：python _tools/ai/_reverse_verify_read_roles.py    # 6/6 都红 → 退出码 0
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()
HERE = Path(__file__).resolve().parent
SRC = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ai"
CHECK = HERE / "_check_ai_guardrails.py"
GEN = HERE / "_gen_ai_read_catalog.py"
PROBE = HERE / "_probe_read_roles.py"

READS = SRC / "AiReads.kt"
SVC = SRC / "AiReadService.kt"
TOOLS = SRC / "AiTools.kt"
CAT = SRC / "AiReadCatalog.kt"


def read_src(path: Path) -> tuple[str, bool]:
    data = path.read_bytes()
    return data.decode("utf-8").replace("\r\n", "\n"), b"\r\n" in data


def write_src(path: Path, text: str, crlf: bool) -> bytes:
    data = text.replace("\r\n", "\n")
    if crlf:
        data = data.replace("\n", "\r\n")
    out = data.encode("utf-8")
    path.write_bytes(out)
    return out



def restore_src(p: Path, text: str, crlf: bool) -> None:
    # 还原**当场核对**（R3-07b）：写回后**重新读回来比**，对不上就非零退出。
    # ⛔ 「写了还原」不是证明；重新读回来的内容 == 快照 才是（L2 要的就是这一句）。
    # 实测教训（2026-09-26）：有份反向验证的还原写的是**另一个文件的字节**，而它自己那句核对
    # 比的也是同一份错字节 ⇒ 恒等通过，把两个源码文件整份写坏。
    wrote = write_src(p, text, crlf)
    if p.read_bytes() != wrote:
        print('⛔ 还原后与快照不一致（注入污染了源码树）：' + str(p))
        raise SystemExit(2)

def run_rc(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run(cmd: list[str]) -> str:
    return run_rc(cmd)[1]


# (说明, 文件, 原文, 替换成, 期望变红的检查名 / None=改跑实测对账脚本)
MUTATIONS = [
    (
        "服务侧读之前不再问角色（那道门没了）",
        SVC,
        "        if (!AiReads.allows(role, action.action, enabledModules())) {",
        "        if (false) {",
        "读之前先问角色闸门",
    ),
    (
        "服务侧默认角色写成派单员（忘了传就按派单员跑）",
        SVC,
        # ⚠️ 2026-09-21 更新锚点：这一处后来从 `roleProvider: () -> AiRole?` 长成了
        #    `actorProvider: () -> AiActor?`（要一起带 `memberShipper`，不然批发商会被当成普通货主）。
        #    注入原意不变：**默认值从"不认角色"变成"按派单员跑"**。
        "private val actorProvider: () -> AiActor? = { null },",
        "private val actorProvider: () -> AiActor? = { AiActor(AiRole.DISPATCHER, false) },",
        "服务侧默认不认角色",
    ),
    (
        "角色闸门不按 roles 过滤（等于没裁）",
        READS,
        # ⚠️ 2026-09-21 更新锚点：闸门里后来多了一条 `(!it.memberOnly || member)`，
        #    所以只锚前半句（`k in it.roles &&`）——注入原意（**等于没裁**）不变。
        "k in it.roles &&",
        "true &&",
        "按 roles 过滤",
    ),
    (
        "工具 enum 改回静态全量（说明裁了、可调集合没裁）",
        TOOLS,
        "putJsonArray(\"enum\") { actions.forEach { add(JsonPrimitive(it.action)) } }",
        "putJsonArray(\"enum\") { AiReadCatalog.ACTIONS.forEach { add(JsonPrimitive(it.action)) } }",
        "read_data 的 enum 不许回落到全量目录",
    ),
    (
        "生成物里的 roles 字段被删（手改机器生成的文件）",
        CAT,
        "    val roles: Set<String>,",
        "",
        "目录里每张表都带 roles",
    ),
    (
        "生成器把角色推导改成「全给」（角色表不再来自后端授权）",
        GEN,
        "    roles = set(BACKEND_ROLES if allow is None else allow)",
        "    return set(BACKEND_ROLES)  # 故意：全给",
        None,
    ),
    # ---- read_data 的公共筛选项只许有一份（2026-09-21）----
    (
        # 反向：把**没人读的那一份**又加回静态表（当年就是这么留着的）。
        # 判据必须报红 —— 否则下一个人还会以为"两份都得改"。
        "静态 SCHEMAS 里又长出一份 read_data 定义（没人读的第二份）",
        TOOLS,
        "                REMEMBER to buildJsonObject {",
        "                READ_DATA to buildJsonObject {\n"
        "                    put(\"type\", \"object\")\n"
        "                    putJsonObject(\"properties\") {\n"
        "                        putJsonObject(\"name\") {\n"
        "                            put(\"type\", \"string\")\n"
        "                            put(\"description\", \"要筛的具体**名字**（货主名/司机名/商品名/客户名/订单号）。\")\n"
        "                        }\n"
        "                    }\n"
        "                },\n"
        "                REMEMBER to buildJsonObject {",
        "静态 SCHEMAS 里不许再有 read_data 的第二份定义",
    ),
    (
        # 反向：把唯一的定义里某个**键名**改掉（描述串还在、计数还是 1，所以只钉描述的判据会绿）。
        # ⚠️ 这条注入第一次跑是 MISS —— 它当场证明"只钉描述串"不够，于是补了键名判据（7 个键）。
        "read_data 的筛选项键名被改（模型照抄的参数名错了，描述串却还在）",
        TOOLS,
        "                        putJsonObject(\"status\") {\n"
        "                            put(\"type\", \"string\")\n",
        "                        putJsonObject(\"statusX\") {\n"
        "                            put(\"type\", \"string\")\n",
        "read_data 的 7 个筛选参数键都在 readDataSpec 里",
    ),
]


def main() -> int:
    bad = 0
    for label, path, old, new, expect in MUTATIONS:
        src, crlf = read_src(path)
        if src.count(old) != 1:
            print(f"  [SKIP] {label} —— 原文出现 {src.count(old)} 次，无法唯一替换")
            bad += 1
            continue
        write_src(path, src.replace(old, new), crlf)
        try:
            if expect is None:
                # 端到端：重新生成目录 → 跑实测对账，必须报"对不上"
                run([sys.executable, str(GEN)])
                rc, out = run_rc([sys.executable, str(PROBE)])
                # ⚠️「没跑成」≠「验过了」。探针连不上本机后端时会非零退出、输出里也没有
                #    「对不上」——旧版在这里显示「实测对账居然全过」，把环境故障读成了
                #    "检查有效"。那正是本脚本要防的假绿灯，所以单独标 [ENV] 并计为不达标。
                if "对不上" in out:
                    hit, detail, tag = True, "实测对账报错", "OK"
                elif rc != 0:
                    last = next((ln.strip() for ln in reversed(out.splitlines()) if ln.strip()), "无输出")
                    hit, tag = False, "ENV"
                    detail = f"没验成：探针退出码 {rc}（{last[:80]}）"
                else:
                    hit, detail, tag = False, "实测对账居然全过", "MISS"
            else:
                out = run([sys.executable, str(CHECK)])
                fails = [ln for ln in out.splitlines() if "[FAIL]" in ln]
                hit = any(expect in ln for ln in fails)
                tag = "OK" if hit else "MISS"
                detail = f"实际红 {len(fails)} 条"
        finally:
            restore_src(path, src, crlf)
            if expect is None:
                run([sys.executable, str(GEN)])  # 还原生成物
        print(f"  [{tag}] {label} → {detail}")
        if not hit:
            bad += 1
    # 收尾确认：还原之后应当全绿
    tail = run([sys.executable, str(CHECK)])
    ok = "项通过" in tail
    print("  [OK] 还原后红线全绿" if ok else "  [MISS] 还原后红线没恢复")
    bad += 0 if ok else 1
    total = len(MUTATIONS) + 1
    print("\n" + (f"✅ {total}/{total} 都红了：这些检查真的在检查。" if bad == 0 else f"❌ {bad}/{total} 不达标。"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
