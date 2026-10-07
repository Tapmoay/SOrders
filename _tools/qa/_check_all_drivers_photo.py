"""司机「拍照送达」是**所有司机一律**的：挂着挂车/整车的师傅也得拍照（台账 L-15，2026-10-06）。

## 用户口径（原话）
「挂车……他也要拍照，同样的流程。」（用户 m00354）

## 机制：从前为什么会有"挂车免拍照"这么一条支
1. 钱那一侧，一张单要么"按单结"（PIECE：有运费 ⇒ 司机跑一趟拿一笔），要么"工资制"
   （SALARY：不按单结）。判据是 `driver_pay.has_per_order_pay(order)`。**挂车默认按单计费。**
2. 界面把"按单计费"顺手当成了"这个人不用拍照"：`order.freightVisible` 为真时动作卡上直接摆
   三颗按钮（完成订单 / 收取现金 / 挂账），点一下走 `vm.completeDirect` →
   `POST /orders/{id}/complete`（**空照片列表**）→ 服务端 `if not has_per_order_pay(order)` 放行。
3. 换句话说：**计费方式**这一个字段，同时在管"怎么给司机结账"和"要不要留送达凭证"两件事。
   用户要的是把后者收回来 —— 所有司机一条流程。

## 这一条撤掉的是哪一半、留的是哪一半（别顺手多删）
- **撤**：界面上那条免拍照支（`if (order.freightVisible)` 里三颗按钮 + `onDirectCompleteClick`
  参数与调用点），以及服务端那道"工资制单可以不带照片"的豁免。
- **留**：`driver_pay.has_per_order_pay` / `order_mode` / `rule_of_user` 这一整套**计费口径**
  （账单、运费提醒仍在用它们）；`vm.completeDirect` / `repo.completeDirect` /
  `POST /orders/{id}/complete` 这条**端点**也留着（老版本 APK / 外部调用方要走它，
  只是它现在同样受照片门约束：不带照片一律 400，所以客户端界面不再走它）。
- `freight_visible` 这个**出参/DTO 字段**也还在（判据在 `_check_driver_money.py`）：本事项只动了
  "完成流程"，没动"司机端显示运费"那件事。

## 判据
1. 客户端那条免拍照支不在了：全仓 `.kt` 的**代码**里 `if (order.freightVisible) {` 命中 0、
   `onDirectCompleteClick` 命中 0、`Text("完成订单", style` 命中 0；动作卡只剩「拍照送达」一颗入口；
2. 三处闸门都不看计费方式：动作卡（画拍照入口）、送达凭证块（画照片与备注）、完成块
   （= 司机 + 可完成 + `photos.isNotEmpty()`）；收款方式仍在完成块里的 `order.collectCash` 里选；
3. 第二道门还在：VM `completeDelivery` 里 `capturedPhotos.isEmpty()` → error + return；
4. 兼容路仍在但界面不走它：VM / repo 的 `completeDirect`、`POST /orders/{id}/complete` 与
   `complete-with-upload` 都还在，且**两条端点都汇入 `complete_delivery`**（同一道照片门）；
5. 服务端一律要照片：`order_flow.complete_delivery` 里空照片列表**无条件** raise；这个文件的
   **代码**里不再引用 `has_per_order_pay`（撤的只是照片豁免）；
6. 计费口径没动：`driver_pay` 里 `PayRule.has_per_order_pay` / `has_per_order_pay(order)` /
   `order_mode` / `rule_of_user` 都还在，且仍被 `driver_bills.py` / `message_center.py` 用着
   —— 这一条同时是"别把 L-15 执行成把计费方式一起删掉"的护栏；
7. 文档与既有判据随动：`docs/DOMAIN_MODEL.md` 的 `DELIVERED` 那格写了"所有司机一律"；
   `_check_delivery_flow.py` / `_check_driver_money.py` 的说明里都点了 L-15；
   `docs/changes/CHG-0050.md` 在；
8. 防静默空转：扫到的 .kt >= MIN_KT，关键文件都在。

## 为什么这条必须有机器的判据
"挂车免拍照"是**一条分支**，不是一处排版：把它删掉不会有任何编译错误，加回来也不会有；
服务端那道豁免更是只有一个 `if` 的距离，而且删掉它之后**所有既有用例照样绿**
（夹具里都带着照片 URL）。反向破坏用例见 _reverse_verify_all_drivers_photo.py
（免拍照支长回来 / 三处闸门各加回计费判据 / 服务端豁免长回来 / `completeDirect` 被删 /
计费口径被顺手改掉 / 文档口径被改回去 … + 还原后逐字节比对）。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
`delivery_photo_urls: list[str]` 里"空列表"与"一张照片"在类型上都是 `list[str]`；
"这一单该不该免拍照"是**业务口径**（挂车按单计费 ⇒ 从前顺带免了拍照），任何类型都表达不出
"所有司机一律"。所以判据只能钉在两端的分支结构、两条端点的汇流点与文档口径上。

用法：python _tools/qa/_check_all_drivers_photo.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
VM = AND / "ui/order/OrderDetailViewModel.kt"
REPO = AND / "data/repo/AppRepository.kt"
FLOW = ROOT / "backend/app/services/order_flow.py"
DELIVERY_API = ROOT / "backend/app/api/v1/orders_delivery.py"
DRIVER_PAY = ROOT / "backend/app/services/driver_pay.py"
BILLS = ROOT / "backend/app/api/v1/driver_bills.py"
MESSAGES = ROOT / "backend/app/services/message_center.py"
DOMAIN_MODEL = ROOT / "docs/DOMAIN_MODEL.md"
CHG = ROOT / "docs/changes/CHG-0050.md"
FLOW_CHECK = ROOT / "_tools/qa/_check_delivery_flow.py"
MONEY_CHECK = ROOT / "_tools/qa/_check_driver_money.py"

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100

#: 必须真的数到这几个文件（少一个就说明目录结构变了，判据要跟着改）。
REQUIRED_FILES = [DETAIL, VM, REPO, FLOW, DELIVERY_API, DRIVER_PAY, BILLS, MESSAGES, DOMAIN_MODEL]


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def code_only(text: str) -> str:
    """去掉注释但**保留换行数**（行号才对得上）。

    ⛔ 不能图省事直接 re.sub 成空串：这条事项在源码里**故意写着**"从前那支是怎么走的"
    （``if (order.freightVisible)`` / ``onDirectCompleteClick`` 都出现在留痕注释里）。
    判据要钉的是**代码**里还有没有这条分支，不是注释里提没提它。
    """
    text = re.sub(r"/\*[\s\S]*?\*/", lambda m: "\n" * m.group(0).count("\n"), text)
    return re.sub(r"//[^\n]*", "", text)


def endpoint_block(text: str, decorator: str) -> str:
    """把某个端点的**函数体**切出来（从它的 @router.<...> 那一行到下一个 @router. 之前）。"""
    i = text.find(decorator)
    if i < 0:
        return ""
    j = text.find("\n@router.", i + len(decorator))
    return text[i:] if j < 0 else text[i:j]


def func_block(text: str, head: str) -> str:
    """切出 Kotlin 里某个 `fun` 的函数体（从 `head` 那一行到下一个同缩进的 `fun` 之前）。

    ⚠️ 为什么要切：`completeDirect` 与 `completeDelivery` 是同一个文件里紧挨着的两兄弟，
    整文件匹配时"`completeDirect` 不碰 capturedPhotos"这类断言永远绿（隔壁那个函数有）。
    """
    i = text.find(head)
    if i < 0:
        return ""
    j = text.find("\n    fun ", i + len(head))
    return text[i:] if j < 0 else text[i:j]


def line_of(text: str, needle: str) -> int:
    i = text.find(needle)
    return 0 if i < 0 else text[:i].count("\n") + 1


class Checker:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.passes = 0

    def ok(self, label: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passes += 1
            print(f"  [OK]   {label}")
        else:
            self.fails.append(label + (f" —— {detail}" if detail else ""))
            print(f"  [FAIL] {label}" + (f" —— {detail}" if detail else ""))

    def present(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is not None, f"没找到 {pattern!r}")

    def absent(self, label: str, text: str, pattern: str) -> None:
        m = re.search(pattern, text)
        self.ok(label, m is None, f"不该出现却出现了 {pattern!r}")

def py_code_only(text: str) -> str:
    """Python 版去注释（保留换行数）。

    ⛔ 上面那个 `code_only` 只认 Kotlin 的 `//` 与 `/* */`；Python 的注释是 `#`，
    而 `order_flow.py` **故意**在注释里写着"从前这里看 `has_per_order_pay`"——
    不清掉的话"代码里不再引用它"永远红、"空照片一律 raise"也会被注释里的旧代码喂绿。
    """
    return re.sub(r"#[^\n]*", "", text)


def main() -> int:
    c = Checker()
    detail = read(DETAIL)
    detail_code = code_only(detail)
    vm_code = code_only(read(VM))
    repo_code = code_only(read(REPO))
    flow = read(FLOW)
    flow_py = py_code_only(flow)
    # ⚠️ 判"送达那道门还在不在"必须先切出 complete_delivery 这一段：整文件 present 会被**别的函数**
    #    里的同名写法救活（order_flow.py:133 那张单也写着 `if order.deleted_at is not None:`）——
    #    反验里"把送达那道软删门删掉"的注入就因此静默变绿（实测抓到，改判据后成立）。
    d0 = flow_py.find("def complete_delivery(")
    deliv = flow_py[d0:] if d0 >= 0 else ""
    d1 = deliv.find("\ndef ")
    if d1 >= 0:
        deliv = deliv[:d1]
    api = read(DELIVERY_API)
    dp_code = code_only(read(DRIVER_PAY))
    bills = read(BILLS)
    messages = read(MESSAGES)
    domain = read(DOMAIN_MODEL)
    dto = read(AND / "data/remote/dto/Dtos.kt")
    kts = sorted(AND.rglob("*.kt"))
    all_kt_code = "\n".join(code_only(read(p)) for p in kts)

    print("== 1. 客户端那条「挂车免拍照」的支已经撤掉 ==")
    c.absent("全仓 .kt 代码里不再有 `if (order.freightVisible) {` 这条支", all_kt_code,
             r"if \(order\.freightVisible\) \{")
    c.absent("全仓 .kt 代码里不再有 `onDirectCompleteClick`（参数行 / 调用点都不许回来）", all_kt_code,
             r"onDirectCompleteClick")
    c.absent("动作卡上不再有「完成订单」这颗一步完成的按钮", all_kt_code,
             r'Text\("完成订单", style')
    c.present("动作卡只剩一颗拍照入口（拍过之后变「继续拍照（N 张）」）", detail_code,
              r'Text\(if \(photos\.isEmpty\(\)\) "拍照送达" else "继续拍照（" \+ photos\.size \+ " 张）"\)')
    c.present("那颗入口点一下**直接进相机**（L-04 第 ① 条没被这次改动碰掉）", detail_code,
              r"onClick = onCaptureClick,")
    c.present("拍照按钮后面跟着导航那颗（动作卡还是原来的顺序）", detail_code,
              r"onClick = onNavigate,")

    print("\n== 2. 三处闸门都不看计费方式（都是「司机 + 可完成」） ==")
    # 2026-10-07（台账 L-49 / CHG-0079）：三道闸门中间现在各夹着一行 `val photos = photosOf()` ——
    # 真机取证的修法：item 闭包只吃外层传进来的**参数快照**，拍照后不刷新，必须在 item 里读实时值。
    # ⚠️ 2026-10-07 台账 L-50 / CHG-0080 之后：照片预览与完成块都并进了**司机动作块那一个 item**
    # （预览自己一道 `if (photos.isNotEmpty())`，且整页只剩那一处读实时值），原来那张带标题的
    # 「送达凭证」卡撤掉了 ⇒ 闸门② 改钉「送达备注自己那张卡」的门，闸门③ 的锚也随间距换成 16dp。
    c.present("闸门① 动作卡：司机 + 可完成（块内第一件事就是读实时值）", detail_code,
              r"if \(role == Role\.DRIVER && order\.status in OrderStatusModel\.COMPLETABLE\) \{\s*\n"
              r"\s*val photos = photosOf\(\)\s*\n")
    c.present("闸门② 送达备注卡：司机 + 可完成（不再对挂车整块不画）", detail_code,
              r"if \(role == Role\.DRIVER && order\.status in OrderStatusModel\.COMPLETABLE\) \{\s*\n"
              r"\s*item \{\s*\n\s*SectionCard \{\s*\n\s*OutlinedTextField\(\s*\n"
              r"\s*value = remark,")
    c.present("闸门③ 完成块：至少一张照片才画（没有计费判据；闸门在司机动作块那个 item 内部）", detail_code,
              r"if \(photos\.isNotEmpty\(\)\) \{\s*\n\s*Spacer\(Modifier\.height\(16\.dp\)\)\s*\n"
              r"\s*Column\(verticalArrangement = Arrangement\.spacedBy\(10\.dp\)\) \{")
    c.present("完成块里收款方式仍在 `order.collectCash` 里选（收现金 / 挂账）", detail_code,
              r"if \(order\.collectCash\) \{")
    c.present("「收取现金（N 张）」那颗还在", detail_code, r'"收取现金（" \+ photos\.size \+ " 张）"')
    c.present("「挂账（N 张）」那颗还在", detail_code, r'"挂账（" \+ photos\.size \+ " 张）"')

    print("\n== 3. 第二道门还在：拍不到照片就不许提交 ==")
    c.ok("VM 里有 completeDelivery（拍照那条完成路）",
         "fun completeDelivery(onDone: () -> Unit, payment: String? = null) {" in vm_code)
    c.present("VM：空照片列表 → 报错 + 直接 return（第二道门）", vm_code,
              r'if \(capturedPhotos\.isEmpty\(\)\) \{\s*\n\s*error = "请至少拍摄一张送达照片"\s*\n\s*return\s*\n\s*\}')
    c.present("VM：completeDelivery 走的是带照片的上传端点", vm_code, r"container\.repo\.completeWithUpload\(")

    print("\n== 4. 兼容路仍在，但界面不走它，且两条端点共用同一道照片门 ==")
    c.present("VM：completeDirect 仍在（老包 / 外部调用方的那条路）", vm_code,
              r"fun completeDirect\(onDone: \(\) -> Unit, payment: String\? = null\) \{")
    direct_vm = func_block(vm_code, "fun completeDirect(onDone: () -> Unit, payment: String? = null) {")
    c.ok("VM 的 completeDirect **不碰** capturedPhotos（它带不了照片）",
         direct_vm != "" and "capturedPhotos" not in direct_vm, "它自己或隔壁那个函数带了照片")
    c.present("VM 的 completeDirect 调 repo 的 completeDirect", direct_vm, r"repo\.completeDirect\(")
    c.present("repo：completeDirect 送的是**空照片列表**（所以它过不了新那道门）", repo_code,
              r"completeOrder\(orderId, com\.tapmoay\.sorders\.data\.remote\.dto\.OrderCompleteBody\(emptyList\(\), remark, payment")
    c.present("repo：completeWithUpload 仍在（带照片那条）", repo_code, r"suspend fun completeWithUpload\(")
    c.present("后端：POST /{order_id}/complete 还在（老版本 APK 要走它）", api,
              r'@router\.post\("/\{order_id\}/complete"')
    c.present("后端：POST /{order_id}/complete-with-upload 还在", api,
              r'@router\.post\("/\{order_id\}/complete-with-upload"')
    blk_upload = endpoint_block(api, '@router.post("/{order_id}/complete-with-upload"')
    blk_plain = endpoint_block(api, '@router.post("/{order_id}/complete"')
    c.ok("两条端点都汇入 complete_delivery（同一道门，没有第二条旁路）",
         "complete_delivery(" in blk_upload and "complete_delivery(" in blk_plain,
         "有一条没走那个函数")

    print("\n== 5. 服务端：空照片列表一律拒（不再看这一单怎么给司机结账） ==")
    c.present("order_flow：`if not delivery_photo_urls:` 后**无条件** raise（中间没有别的判据）", flow_py,
              r'if not delivery_photo_urls:\s*\n\s*raise ValueError\("请至少上传一张送达照片"\)')
    c.absent("order_flow 的**代码**里不再引用 has_per_order_pay（撤的只是照片豁免）", flow_py,
             r"has_per_order_pay")
    c.present("order_flow 仍在用计费口径的 rule_of_user（钱那一侧一个字没动）", flow_py,
              r"from app\.services\.money_contract import rule_of_user")
    c.present("order_flow 里那个调用点也还在", flow_py, r"rule = rule_of_user\(driver\)")
    c.present("L-14 那道凭证形状门还在（照片必须来自本系统上传端点）", flow_py,
              r'bad_photos = \[u for u in delivery_photo_urls if not str\(u\)\.startswith\("/static/uploads/delivery/"\)\]')
    c.present("软删那条门还在（回收站里的单不许送达）", deliv, r"if order\.deleted_at is not None:")
    c.present("状态门也在里面（仅「已接单」可完成配送）", deliv, r"if order\.status != OrderStatus\.ACCEPTED:")
    c.present("本单司机门也在里面（非本单司机不许送达）", deliv, r"if order\.driver_id != driver\.id:")
    # ⚠️ 必须**先切到 complete_delivery 里面**再比位置：派单那条路（assign）里也有一个
    #    `claimed = db.execute(` 的 CAS 占位，整文件 find 会拿它第一个出现的位置（在文件的几千字符处），
    #    于是这条判据永远红 —— 而它想说的恰恰是"照片门先于**这一单**的状态变更"。
    cl = flow_py.find("def complete_delivery(")
    i_photo = flow_py.find('raise ValueError("请至少上传一张送达照片")', cl)
    i_claim = flow_py.find("claimed = db.execute(", cl)
    c.ok("照片门拦在状态变更（CAS 占位）之前 —— 拒的时候这一单一个字段都没动过",
         cl >= 0 and cl <= i_photo < i_claim, f"complete_delivery={cl} photo={i_photo} claim={i_claim}")
    c.present("留痕注释里点了老客户端的兼容后果（老 APK 会拿到 400）", flow,
              r"老版本 APK 走 `POST /orders/\{id\}/complete`")

    print("\n== 6. 计费口径没动（L-15 撤的只是照片豁免，别顺手删计费方式） ==")
    c.present("driver_pay：PayRule.has_per_order_pay 还在", dp_code, r"def has_per_order_pay\(self\) -> bool:")
    c.present("driver_pay：模块级 has_per_order_pay(order) 还在", dp_code,
              r"def has_per_order_pay\(order\) -> bool:")
    c.present("driver_pay：order_mode(order) 还在", dp_code, r"def order_mode\(order\) -> str:")
    c.present("driver_pay：rule_of_user(user) 还在", dp_code, r"def rule_of_user\(user\) -> PayRule \| None:")
    c.present("driver_bills 仍在用 has_per_order_pay（按单账单判据）", bills, r"if not has_per_order_pay\(o\):")
    c.present("message_center 仍在用 has_per_order_pay（运费提醒判据）", messages,
              r"if not has_per_order_pay\(order\):")
    c.present("freight_visible 出参 / DTO 字段仍在（本事项没动「司机端显示运费」）", dto,
              r'@SerialName\("freight_visible"\) val freightVisible: Boolean = false,')

    print("\n== 7. 文档与既有判据随动 ==")
    c.present("DOMAIN_MODEL：DELIVERED 那格写了「所有司机一律」", domain,
              r"\| `DELIVERED` \| 已送达 \| 司机完成且至少上传一张送达照片（\*\*所有司机一律\*\*")
    c.present("DOMAIN_MODEL：那一格点得出台账编号（可追溯到用户原话）", domain, r"台账 L-15")
    c.present("_check_delivery_flow.py 的说明里点了 L-15", read(FLOW_CHECK), r"台账 L-15")
    c.present("_check_driver_money.py 的说明里指到本判据", read(MONEY_CHECK),
              r"_check_all_drivers_photo\.py")
    c.ok("docs/changes/CHG-0050.md 在（本事项的立项文档）", CHG.exists())
    c.present("CHG-0050 写的是「所有司机」这个口径", read(CHG) if CHG.exists() else "", r"所有司机")

    print("\n== 8. 防静默空转 ==")
    c.ok(f"扫到的 .kt 有 {len(kts)} 份（>= {MIN_KT}）", len(kts) >= MIN_KT)
    for p in REQUIRED_FILES:
        c.ok(f"关键文件在：{p.relative_to(ROOT).as_posix()}", p.exists())

    print()
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print(f"  - {f}")
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

