"""AI 工具脚本共用的路径基准 + 反向验证的**现场恢复**。

为什么需要它：这些脚本原本放在仓库根（`Path(__file__).parent` 就是根），
移进 `_tools/ai/` 后基准变了，会让所有相对路径失效。统一改为"向上找到含 backend/ 的目录"。

### 为什么还要"现场恢复"
所有 `_reverse_verify_*.py` 都是**改源码 → 跑检查 → 改回来**。被杀在半路
（Ctrl+C、超时、后台任务被 kill）就会把**注入的 bug 留在源码树里**，
而下一次跑检查会看到一堆真实的失败——分不清"我改坏了"还是"上次没还原"。
2026-09-16 实测踩到：一次后台反向验证被 kill，`Modules.kt` 里多了两个 AI 入口，
红线报「命中 2 次」，我一度以为是自己的改动引入了 bug。

所以：跑之前把会被注入的目录整体快照一份，跑完（或下次跑之前）比对还原。
"""
from __future__ import annotations

import filecmp
import shutil
import tempfile
from pathlib import Path


def repo_root() -> Path:
    """从当前文件向上找第一个含 backend/ 与 android/ 的目录。"""
    here = Path(__file__).resolve()
    for p in [here.parent, *here.parents]:
        if (p / "backend").is_dir() and (p / "android").is_dir():
            return p
    # 兜底：退两级（_tools/ai/ -> repo）
    return here.parent.parent.parent


ROOT = repo_root()

# 反向验证会注入到的目录（**自己列**，不含 build 产物；漏掉一个不影响安全，只是那一处还原不了）
SNAPSHOT_DIRS = (
    "android/app/src/main/java",
    "android/app/src/test/java",
    "backend/app",
    "docs",
    "_tools/ai",
)


def snapshot_dir() -> Path:
    """快照放临时目录（不进仓库，不会被 git 或红线当成产物）。"""
    return Path(tempfile.gettempdir()) / "dsh_rv_snapshot"


def take_snapshot() -> int:
    """跑反向验证之前拍一张快照。返回文件数。"""
    dst = snapshot_dir()
    if dst.exists():
        shutil.rmtree(dst)
    n = 0
    for rel in SNAPSHOT_DIRS:
        src = ROOT / rel
        if not src.is_dir():
            continue
        for p in src.rglob("*"):
            if not p.is_file() or "__pycache__" in p.parts:
                continue
            target = dst / rel / p.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            n += 1
    return n


def restore_snapshot() -> list[str]:
    """把快照里与现场**不一致**的文件写回去，返回被还原的仓库相对路径。快照用完即删。

    只覆盖"内容不同"的文件；只在现场新出现的文件**只报告不删**——那可能是这次跑
    真的新加的文件，删了就真丢了（用户的底线是「不要删了就搞不回来了」）。
    """
    src = snapshot_dir()
    if not src.is_dir():
        return []
    fixed: list[str] = []
    for rel in SNAPSHOT_DIRS:
        base = src / rel
        if not base.is_dir():
            continue
        for snap in base.rglob("*"):
            if not snap.is_file():
                continue
            live = ROOT / rel / snap.relative_to(base)
            if not live.exists() or not filecmp.cmp(snap, live, shallow=False):
                live.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(snap, live)
                fixed.append(str(live.relative_to(ROOT)))
    shutil.rmtree(src, ignore_errors=True)
    return sorted(fixed)


def extra_files() -> list[str]:
    """现场有、快照里没有的文件（注入新加的）。只报告，不删。"""
    src = snapshot_dir()
    if not src.is_dir():
        return []
    extra: list[str] = []
    for rel in SNAPSHOT_DIRS:
        base = src / rel
        live_base = ROOT / rel
        if not live_base.is_dir():
            continue
        for live in live_base.rglob("*"):
            if not live.is_file() or "__pycache__" in live.parts:
                continue
            if not (base / live.relative_to(live_base)).exists():
                extra.append(str(live.relative_to(ROOT)))
    return sorted(extra)


# ------------------------------------------------------------------ 互斥锁
#
# 反向验证是「改源码 → 跑检查 → 改回来」，所以**它跑着的时候源码树是脏的**。
# 2026-09-19 实测踩到两个后果，都很贵：
#   1. 一边跑它、一边跑红线 → 红线报「端到端钉住『刚好到上限的值必须能过』——
#      没找到 'def test_边长值被接受'」，而那个测试文件正被某份反向验证**临时改名**。
#      第一反应是"我刚改坏了什么"，而不是"有人在注入"。
#   2. 一边跑它、一边改源码 → 跑完 `restore_snapshot()` 会按**开跑前的快照**
#      把这些改动一起写回去，**并发做的修改被静默抹掉**（这次抹掉了 15 个文件）。
# 所以跑它的时候别人必须停手：锁负责让**并发的检查**停手（见 [refuse_if_injecting]），
# "别改源码"只能靠喊——`_reverse_verify_all.py` 的开头也写了一句。
LOCK = Path(tempfile.gettempdir()) / "dsh_reverse_verify.lock"
LOCK_STALE_SECONDS = 30 * 60   # 被 kill 留下的陈旧锁：超过这个时间当它不存在


def lock_reverse_verify() -> None:
    import os
    import time

    LOCK.write_text(f"{os.getpid()} {time.time()}", encoding="utf-8")
    # 反向验证自己会**调用**那些检查脚本（注入 → 跑检查 → 看是否变红），
    # 所以它的子进程必须能跑；只有"与它无关的并发调用"才该被挡住。
    os.environ["DSH_RV_CHILD"] = "1"


def unlock_reverse_verify() -> None:
    import os

    LOCK.unlink(missing_ok=True)
    os.environ.pop("DSH_RV_CHILD", None)


def is_rv_child() -> bool:
    """当前进程是不是「反向验证叫起来的」（它跑检查时源码是故意脏的）。"""
    import os

    return os.environ.get("DSH_RV_CHILD") == "1"


def reverse_verify_running() -> bool:
    """反向验证正在跑吗（陈旧的锁不算）。判据是"锁在 + 我不是它叫起来的"，见 [is_rv_child]。"""
    import time

    if not LOCK.exists():
        return False
    try:
        started = float(LOCK.read_text(encoding="utf-8").split()[1])
    except (OSError, ValueError, IndexError):
        return False
    return (time.time() - started) < LOCK_STALE_SECONDS


def refuse_if_injecting(who: str) -> bool:
    """在注入状态下拒绝出结论。返回 True = 该停手。"""
    if reverse_verify_running() and not is_rv_child():
        print(
            f"❌ 反向验证正在跑（源码是**注入状态**，注入的 bug 就在树里）："
            f"{who} 现在给不出可信结论，等它跑完再跑。",
        )
        return True
    return False



#: orders 路由现在由**三个模块**组成（2026-09-24 整改阶段 4 纯搬迁：查询组去了 orders_query.py、
#: 共用助手去了 orders_common.py）。读它的判据一律读**并集** ——
#: "锚点落在哪个文件"不是这些判据要管的事，而搬迁不该让一打判据红一遍。
ORDERS_API_MODULES = (
    "orders.py",
    "orders_query.py",
    "orders_common.py",
    "orders_payment.py",
    "orders_media.py",
    "orders_assignment.py",
    "orders_delivery.py",
    "orders_lifecycle.py",
    "orders_return.py",
)


def orders_api_files(root: Path | None = None) -> list[Path]:
    """orders 三个模块里**实际存在**的那些（按声明顺序，报错时便于定位）。"""
    base = (root or ROOT) / "backend/app/api/v1"
    return [base / n for n in ORDERS_API_MODULES if (base / n).is_file()]


def orders_api_source(root: Path | None = None) -> str:
    """三个模块的源码并集，段间带文件名注释（判据报错时能看出锚点在哪一份里）。"""
    parts = [f"# ===== {p.name} =====" + chr(10) + p.read_text(encoding="utf-8", errors="replace")
             for p in orders_api_files(root)]
    return (chr(10) * 2).join(parts)



#: 文件名 → AI 动作里的**逻辑模块名**。
#: orders 在 2026-09-24（整改阶段 4 纯搬迁）拆成了三个文件，但 `orders.list_orders` 这种动作名是
#: **对模型与客户端可见的契约**（安卓侧 AiReadCatalog.kt 与四个测试都写着它）——
#: 搬迁不许改契约，所以拆出来的文件在这里**折回同一个模块名**。
MODULE_ALIAS = {
    "orders_query": "orders",
    "orders_common": "orders",
    "orders_payment": "orders",
    "orders_media": "orders",
    "orders_assignment": "orders",
    "orders_delivery": "orders",
    "orders_lifecycle": "orders",
    "orders_return": "orders",
}


def module_key(stem: str) -> str:
    """取的模块名（拆出去的兄弟文件折回原模块）。"""
    return MODULE_ALIAS.get(stem, stem)



#: 报表的源码现在可能分成两份（2026-09-24 整改阶段 4「reports.py 下沉」）：
#: 路由在 api/v1/reports.py、聚合在 services/reports_service.py。
REPORTS_MODULES = ("api/v1/reports.py", "services/reports_service.py")


#: AI 写链路（写闸门）的**家族文件名**。整改报告 §11「客户端按职责拆，不是按行数拆」——
#: 与 orders.py / reports.py 两次搬迁同形：**先让判据读并集，再搬代码**。
#: ⛔ 顺序不能反：先搬代码而没有并集口径，每搬一块就要改一打判据，改漏一个就是"静默不查"。
#: 这里用 glob（`ai/AiWrite*.kt`）而不是写死清单：拆出来的新文件**自动**进并集，
#: 不需要谁记得来登记（这与"清单要自己算"是同一条规矩）。
AI_WRITE_MAIN = "android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteService.kt"


def ai_write_source(root: Path | None = None) -> str:
    """AI 写链路那一族源码的**并集**（按文件名排序，段间带文件注释，便于报错时定位）。

    目前只有 `AiWriteService.kt` 一份，所以今天它的返回值＝那一份的内容（**行为零变化**）；
    §11 拆出来的 `AiWrite*.kt` 会自动并进来。
    ⚠️ 只跳过**还不存在**的文件；主文件 `AiWriteService.kt` 不在时说明路径写错了，照旧报错。
    """
    base = (root or ROOT) / "android" / "app" / "src" / "main" / "java" / "com" / "tapmoay" / "sorders" / "ai"
    main = (root or ROOT) / AI_WRITE_MAIN
    if not main.is_file():
        raise FileNotFoundError("找不到 AI 写链路主文件：" + str(main))
    parts = [
        "# ===== " + p.name + " =====" + chr(10) + p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(base.glob("AiWrite*.kt"))
    ]
    return (chr(10) * 2).join(parts)


def reports_source(root: Path | None = None) -> str:
    """报表的源码**并集**（缺哪一份就跳过哪一份）。

    ⚠️ 缺文件不报错是**故意**的：搬迁必须拆成两步走（先改判据读取口径、再下沉），
    第①步做完时 service 文件还不存在 —— 那时这条判据必须照样是绿的。
    """
    base = (root or ROOT) / "backend" / "app"
    parts = []
    for rel in REPORTS_MODULES:
        f = base / rel
        if f.is_file():
            parts.append(f"# ===== {rel} =====" + chr(10) + f.read_text(encoding="utf-8", errors="replace"))
    return (chr(10) * 2).join(parts)
