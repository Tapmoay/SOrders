"""扫一遍**被跟踪的文件里有没有秘密**（本地也要扫：这条分支迟早要推上去）。

为什么要它：这个仓库里既有 `.env.example`（示例）也有 `android/local.properties.example`，
而后者的 `amap_key` 是**真 key**（客户端 key，跟包名绑定，但仍然是凭据）。
"某次改配置顺手把真值写进 example"是这类事故最常见的形态，肉眼 review 10 万行 diff 不现实。

⚠️ 文件名以 `_check_` 开头是**故意的**：`_tools/qa/_check_all.py` 的清单按这个前缀算，
于是它会自动进"每次都要跑"的那一组（叫别的名字，它就只是一份没人跑的脚本）。

用法：
    python _tools/qa/_check_secrets.py            # 扫全部被跟踪的文件
"""
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ai"))
from _airepo import repo_root  # noqa: E402

ROOT = repo_root()

# 已知的真凭据（本机 local.properties 里的高德 key）。出现在**任何被跟踪的文件**里都要报。
# ⚠️ 拆成两半写：**判据文件自己不能包含那个整串**，否则它每次都会把自己报成泄露
#    （第一版就是整串写在这里，于是"扫出 1 处可疑：_check_secrets.py"）。
KNOWN = ["06393ebf" + "50284409" + "b532ef517b5e63cf"]
# 通用形状：赋值语句右边像凭据，而左边是凭据字段名
PATTERNS = [
    (re.compile(r"(?i)\b(api[_-]?key|secret|access[_-]?token|private[_-]?key)\b\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{16,})"),
     "凭据字段被赋了长字符串"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}"), "OpenAI 风格 key"),
    # ⚠️ 这条**必须有捕获组**：判值的逻辑取的是"正则里最后那个组"，
    #    没有组时它只能拿到整个匹配（`PASSWORD = "123321"`），于是"123321 是开发值"这条豁免
    #    永远不生效（实测：加了豁免还是照报）。
    (re.compile(r"(?i)\bpassword\b\s*[:=]\s*[\"']([^\"']{6,})[\"']"), "明文密码字面量"),
]
# 这些路径天然带示例/测试值，命中不算
# ⚠️ 必须包含 `/test/`（单元测试里的 `apiKey = "sk-unit-test-key…"` 是假值）——
#    第一版只写了 `test_`，于是 5 个测试文件被当成"泄露"报出来，
#    而**假阳性会让下一个人学会无视这条检查**（比漏报更常见的死法）。
#
# ⚠️⚠️ 第二版把整棵 `_tools/` 也豁免了，那是个**真窟窿**：`_tools/deploy/` 正是
#      部署脚本住的地方（远端 IP、SSH 私钥路径、"怎么连生产"的注释都在那儿）。
#      现在只豁免"看起来像占位/开发值"的**值**（见 DEV_VALUES），不再按目录豁免。
ALLOW_PATH = ("example", "/test/", "test_", ".md", "docs/", "conftest")
# 这些值本身是占位符/本地开发口令，出现不算泄露（本项目的本地后端就是 13800000001/123321）
DEV_VALUES = {
    "password", "root", "123456", "123321", "test1234", "pass12345", "sorders",
    "changeme", "your_password", "yourpassword", "secret", "xxx",
}
# 形如手机号的"值"多半是 `PHONE, PASSWORD = "138…", "123321"` 这种元组位置错位，不算密码
PHONE_LIKE = re.compile(r"^1\d{10}$")
# 公网 IP：**不是秘密**，但仓库是公开的，值得在收尾时提醒一句（只警告、不判失败）。
# ⚠️ 光看"四个点分数字"会把**版本号**也认成 IP（`1.0.0.10`、`1.0.0.9` 就出现在 Dtos.kt 里），
#    而"狼来了"式的警告等于没有警告。所以要求它出现在**像主机的地方**：
#    同一行里有 http / host / ip 这些词，或者后面跟着 `:端口`。
PUBLIC_IP = re.compile(
    r"\b(?!0\.0\.0\.0|10\.|127\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)"
    r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"
)
HOSTISH = re.compile(r"(?i)https?|host|\bip\b|server|8\.145\.40\.22")
PORT_AFTER = re.compile(r"^\s*:\d{2,5}")


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    return [ln for ln in out.splitlines() if ln.strip()]


def main() -> int:
    # ⚠️ **不要**在这里读命令行位置参数：`_check_all.py` 会把"要位置参数的脚本"当成工具排掉
    #    （那种脚本不带参数跑只会打印一行用法），于是这条检查就进不了"每次都要跑"的那一组。
    #    （踩过一次：连**这句注释**里照抄那个表达式都会被它的正则命中——判据是扫源码文本的。）
    files = tracked_files()
    print(f"当前分支被跟踪的文件 {len(files)} 个")

    hits: list[str] = []
    ips: dict[str, str] = {}
    scanned = 0
    me = "tools/qa/_check_secrets.py"
    for f in files:
        p = ROOT / f
        if not p.is_file():
            continue
        # 判据文件自己跳过：它必须**包含那些模式的样子**（注释里就有 `apiKey = "sk-…"` 这种例子），
        # 不跳过的话它每次都会把自己报成泄露（实测：改完豁免规则后第一次跑就是这个结果）。
        if f.replace("\\", "/").endswith(me):
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        scanned += 1
        for k in KNOWN:
            if k in txt:
                hits.append(f"{f}: 命中已知凭据（高德 key）")
        for rx, why in PATTERNS:
            if any(a in f for a in ALLOW_PATH):
                continue
            for m in rx.finditer(txt):
                # ⚠️ 取值要取**正则里最后那个组**（= 被赋的字面量），不能取整个匹配：
                #    否则 `PHONE, PASSWORD = "13800000001", "123321"` 这种元组会被读成
                #    `password = "13800000001"`，把手机号当成密码报出来（实测踩到）。
                val = (m.group(m.lastindex) if m.lastindex else m.group(0)).strip("\"'")
                if val.lower() in DEV_VALUES or PHONE_LIKE.match(val):
                    continue
                hits.append(f"{f}: {why} —— {m.group(0)[:60]}")
        for m in PUBLIC_IP.finditer(txt):
            line = txt[txt.rfind("\n", 0, m.start()) + 1: txt.find("\n", m.end()) if txt.find("\n", m.end()) > 0 else len(txt)]
            if not (HOSTISH.search(line) or PORT_AFTER.match(txt[m.end():m.end() + 8])):
                continue   # 像版本号/编号，不算主机名
            ips.setdefault(m.group(1), f)

    if hits:
        print(f"❌ {len(hits)} 处可疑：")
        for h in hits:
            print("   - " + h)
        return 1
    # 反空转：一个文件都没读到的话上面什么都不会报
    if scanned < 200:
        print(f"❌ 只读到 {scanned} 个被跟踪文件——清单过期了，这条检查在空转")
        return 1
    print("✅ 被跟踪的文件里没有已知凭据、也没有凭据形状的赋值")
    if ips:
        # 只警告不失败：IP 不是秘密，而这个仓库**是公开的**（匿名 ls-remote 能读到）。
        # 值不值得写进公开仓库由人判断，但至少别在不知情的情况下写进去。
        print(f"⚠️ 有 {len(ips)} 个公网 IP 出现在被跟踪的文件里（仓库是公开的，确认是有意的）：")
        for ip, where in sorted(ips.items()):
            print(f"   - {ip}  例如 {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
