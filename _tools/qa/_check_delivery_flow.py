"""司机「拍照送达」：点一下直接拍照、照片就长在订单页里、预览就贴在拍照按钮上面、完成按钮在导航下面、两块备注沉到最底（CHG-0045 / 台账 L-04；顺序被 2026-10-07 台账 L-49 / CHG-0079 调过一次，当天再被台账 L-50 / CHG-0080 调成现在这样）。

## 用户报的现象（2026-10-06，台账 L-04，原话七条）
1. 「点击拍照送达就**直接拍照**」；
2. 「拍完的照片就在订单界面里出现缩略图」，「然后再点击**继续拍照**」；
3. 「**完成按钮就移到内部备注的最下面**（页面最底部）」—— ⚠️ **这一条已被 2026-10-07 台账 L-49 / CHG-0079 推翻**（改到照片预览下面），**当天又被台账 L-50 / CHG-0080 再调一次**：完成按钮改到**高德导航下面**（中间隔 16dp 防误触）、两块备注一起沉到最底；下面第 3 组钉的就是 L-50 的顺序；
4. 「**只有上传最少一张照片之后才会有这个**（完成入口）」；
5. 「**送达备注就写在内部备注的上面**」——L-50 之后仍然成立（顺序＝完成按钮 →「送达备注（可选）」→ 内部备注最后）；
6. 「**内部备注只有我们司机和派单员可以看**，其他的不可见」且**不要弹窗**；
7. 弹窗里那个「**货物破损**」没必要存在 ——「因为已经有了」。

## 机制（这一条不是"把抽屉里的东西搬出来"）
1. 从前「拍照送达」= 开一个 ModalBottomSheet，**相机是抽屉里的第二颗按钮**。用户要的是
   **一步**：点入口就进相机（这是题眼，不是排版偏好）。
2. 抽屉与页面**各有一份 DamageCard**：页面上那份（紧贴商品明细）是常用的，抽屉里那份是
   第二份。两份写同一件事，早晚会出现"我在抽屉里填了、页面上没显示"这类错觉。
3. 内部备注从前是 AlertDialog + 一枚 showNoteDialog 开关；而它的写入口是 **append-only**
   （后端 POST /orders/{id}/driver-note 写 "[司机 {时间}] " 前缀**累加**到 internal_notes，
   注释明说写进去就再也改不了）。⚠️ 旧代码在打开弹窗前把 noteText **回填成 driverRemark**
   （送货备注）—— 那不是"编辑已有备注"，是把送货备注抄进历史；本事项一并去掉。
4. ~~挂车直结那条路（order.freightVisible）**不带照片**、走 completeDirect~~ —— **这一条已被
   2026-10-06 台账 L-15 推翻**（用户 m00354：「挂车……他也要拍照，同样的流程」）：所有司机一律
   拍照，界面上那个 `if (order.freightVisible)` 分支与三颗 `onDirectCompleteClick` 都撤掉了；
   `order.freightVisible` 这个字段若还要用，只能用在"显示运费"这类**与完成流程无关**的地方。

## 为什么这条必须有机器的判据
这一条几乎全是"没报错但也没发生"的毛病：抽屉删了可以再长回来（编译器很乐意）；
photos.isNotEmpty() 那道门去掉之后界面照样渲染、只是"一张没拍也能点提交"；
「内部备注」弹窗回来不会有任何编译错误，但用户说的"不要弹窗"就白说了；
DamageCard 再抄一份同样没人拦。反向破坏用例见 _reverse_verify_delivery_flow.py
（入口改回开抽屉 / 弹窗回来 / 照片门去掉 / 破损再抄一份 / 备注回填 / 后端门放松 … + 还原后逐字节比对）。

## 为什么全仓扫，而不只看这一个文件
"抽屉不许再长回来""破损只许一份""预览只许一份"都是**结构约定**：任何页面都能再写一个
DeliverySheet / DamageCard / 自写大图弹层，编译器不会有意见。所以第 1 组与第 2 组在
**所有 .kt** 上数命中数，并配 MIN_KT 防"目录被搬走 → 一个都没扫到 → 全绿"。

## R4-BOUNDARY-JUSTIFICATION: 为什么代码边界解决不了这件事
缺的不是类型，是**交互语义**：「点一下是开抽屉还是进相机」两段代码都合法；
「这一格是编辑还是追加」在类型上也没有区别（都是 (String) -> Unit）；
「两块牌子是不是同一件事」是产品判断。所以判据只能钉在源码结构、文案与两端的门上。

## 判据
1. 入口直连相机：onCaptureClick = { capture() }，且全仓没有 showDeliverySheet / showNoteDialog；
   抽屉定义（private fun DeliverySheet(）在任何 .kt 里都是 0 命中；
2. 照片长在页面里：缩略图（AsyncImage(model = File(path))）可点开唯一那一份大图预览
   （preview.open(vm.capturedPhotos.map { File(it) }, i)）、右上角可移除；拍照入口文案跟随张数；
3. 页面顺序 = 照片预览 → 拍照 → 高德导航 → 完成按钮 → 送达备注 → 内部备注最后
   （2026-10-07 台账 L-50 / CHG-0080 定稿，推翻同日 L-49 / CHG-0079 的口径；L-04 第 ③ 条已推翻）；
   预览不再单占一张「送达凭证」白卡、也不带标题，缩略图与那行小字直接贴在拍照按钮上面；
4. 完成入口至少一张照片：闸门 = 司机 + 可完成 + photos.isNotEmpty()（**不再有** `!order.freightVisible`
   那半句，2026-10-06 台账 L-15），且 VM 里那道 capturedPhotos.isEmpty() 第二道门还在；
5. 免拍照那一支不许长回来：界面里 `if (order.freightVisible) {` 命中 0、`onDirectCompleteClick(` 命中 0、
   动作卡上不再有「完成订单」这颗一步完成的按钮；VM 里的 completeDirect 仍在但**不碰** capturedPhotos
   （它成了老版本 APK / `POST /orders/{id}/complete` 的兼容路，照片门由后端守）；
6. 内部备注的两道角色门一字未松：界面 role == DRIVER || DISPATCHER 的只读显示仍在、
   输入框在司机门以内；后端 order_response.py 对货主抹空 + orders_delivery.py 的
   require_permission(ORDER_INTERNAL_NOTE) + 只放 DRIVER/DISPATCHER + 司机必须是本单司机；
7. append-only 没被写成"编辑历史"：noteText 初始为空、全仓没有回填 driverRemark；
   页面文案明说"追加/再写一条"；saveNote 成功后清空输入框；
8. 破损只剩一份：DamageCard 的调用点从 2 处降到 1 处；
9. 防静默空转：扫到的 .kt >= MIN_KT，五个关键文件都在。

用法：python _tools/qa/_check_delivery_flow.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
AND = ROOT / "android/app/src/main/java/com/tapmoay/sorders"
DETAIL = AND / "ui/order/OrderDetailScreen.kt"
VM = AND / "ui/order/OrderDetailViewModel.kt"
DELIVERY_API = ROOT / "backend/app/api/v1/orders_delivery.py"
RESPONSE = ROOT / "backend/app/services/order_response.py"
SCHEMA = ROOT / "backend/app/schemas/order.py"

#: 全仓至少要有这么多 .kt（防"目录被搬走 → 一个都没扫到 → 全绿"）。
MIN_KT = 100

#: 必须真的数到这几个文件（少一个就说明目录结构变了，判据要跟着改）。
REQUIRED_FILES = [DETAIL, VM, DELIVERY_API, RESPONSE, SCHEMA]


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def code_only(text: str) -> str:
    """去掉注释但**保留换行数**（行号才对得上）。

    ⛔ 不能图省事直接 re.sub 成空串：VM 的 KDoc 里**故意留着**历史那句
    "showDeliverySheet（拍照送达底部抽屉）"，那是给后来的人看"从前错在哪"的。
    判据要钉的是**代码**里还有没有这个开关，不是注释里提没提它。
    """
    text = re.sub(r"/\*[\s\S]*?\*/", lambda m: "\n" * m.group(0).count("\n"), text)
    return re.sub(r"//[^\n]*", "", text)


def endpoint_block(text: str, decorator: str) -> str:
    """把某个端点的**函数体**切出来（从它的 @router.<...> 那一行到下一个 @router. 之前）。

    ⚠️ 为什么非切不可（2026-10-06 反验抓到的）：@B@orders_delivery.py@B@ 里
    @B@if role not in (UserRole.DRIVER.value, UserRole.DISPATCHER.value):@B@ 这一行**出现两次** ——
    它既守着 @B@driver-note@B@（内部备注），也守着补导航信息那个端点。整文件匹配时，
    把 @B@driver-note@B@ 那份白名单放松成"只放司机"、或删掉"必须是本单司机"，判据**照样绿**
    （另一处还有同样一行）。判据钉的必须是**这个端点自己**的门。
    """
    i = text.find(decorator)
    if i < 0:
        return ""
    j = text.find("\n@router.", i + len(decorator))
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


def main() -> int:
    c = Checker()
    detail = read(DETAIL)
    detail_code = code_only(detail)
    vm = read(VM)
    vm_code = code_only(vm)

    kts = sorted(AND.rglob("*.kt"))

    print("== 1. 「拍照送达」一步进相机：抽屉与备注弹窗都退役 ==")
    c.present("入口直连相机 onCaptureClick = { capture() }", detail_code, r"onCaptureClick = \{ capture\(\) \}")
    c.absent("入口不再开抽屉（vm.showDeliverySheet = true）", detail_code, r"showDeliverySheet")
    c.absent("备注弹窗开关 showNoteDialog 也没了", detail_code + vm_code, r"showNoteDialog")
    hits_sheet = [str(p.relative_to(ROOT)) for p in kts if re.search(r"fun DeliverySheet\(", code_only(read(p)))]
    c.ok(
        f"全仓 {len(kts)} 个 .kt 里没有任何 DeliverySheet 定义",
        not hits_sheet,
        "；".join(hits_sheet[:3]),
    )
    c.absent("内部备注不再走 AlertDialog（没有那颗标题）", detail_code, r'title = \{ Text\("内部备注"\) \}')
    c.present("拍照那条链路本身没动（水印 + 落 cacheDir/photos）", detail_code,
              r"Watermark\.process\(File\(rawPath\), out, wmText\)")
    c.present("拍完进 capturedPhotos 的那一步没动", detail_code, r"vm\.addCapturedPhoto\(out\.absolutePath\)")

    print("\n== 2. 照片就长在订单页里（缩略图 / 继续拍照 / 点开唯一那一份预览） ==")
    # 2026-10-07（台账 L-50 / CHG-0080）：原来那张带标题的「送达凭证 / 送达照片（已拍 N 张）」
    # 白卡已经撤掉，预览改成「缩略图 + 一行小字」直接贴在拍照按钮上面（用户口径：不要标题、不要白卡）。
    c.present("照片预览块在页面上（缩略图 + 那行说明小字）", detail_code,
              r'"点一下看大图（可双指放大、可存相册）；右上角的 ⊗ 是删掉这一张",')
    c.present("缩略图带 contentDescription（无障碍与真机取证都认它）", detail_code,
              r'contentDescription = "已拍照片",')
    c.absent("⛔ 那张带标题的「送达凭证」白卡不许长回来（L-50 已撤）", detail_code,
             r'"送达照片（已拍 " \+ photos\.size \+ " 张）"')
    c.present("缩略图是本地 File（还没上传的那张）", detail_code, r"AsyncImage\(\s*model = File\(path\),")
    c.present("点缩略图开大图（走 ui/common/ImagePreview.kt 那一份）", detail_code,
              r"\.clickable \{ onCapturedPhotoClick\(i\) \}")
    c.present("传的是整组 + 序号（多张时才能左右翻）", detail_code,
              r"preview\.open\(vm\.capturedPhotos\.map \{ File\(it\) \}, i\)")
    c.present("右上角可以删掉这一张", detail_code, r"onClick = \{ onRemovePhoto\(i\) \}")
    c.present("同一个拍照入口拍过之后变「继续拍照（N 张）」", detail_code,
              r'Text\(if \(photos\.isEmpty\(\)\) "拍照送达" else "继续拍照（" \+ photos\.size \+ " 张）"\)')
    c.present("L-03 的收口没被推翻：服务端照片仍走 openPhoto", detail_code, r"onPhotoClick = openPhoto,")
    c.present("预览弹层仍只画一次", detail_code, r"preview\.Show\(\)")
    c.present("VM：拍完把路径记下来（addCapturedPhoto）", vm_code, r"fun addCapturedPhoto\(path: String\)")
    c.present("VM：能单独删掉某一张（removeCapturedPhoto）", vm_code, r"fun removeCapturedPhoto\(index: Int\)")

    print("\n== 3. 页面顺序（2026-10-07 台账 L-50 / CHG-0080 定稿）：照片预览 → 拍照 → 高德导航 → 完成按钮 → 送达备注 → 内部备注 ==")
    i_thumb = line_of(detail_code, "model = File(path),")
    i_photo = line_of(detail_code, '"拍照送达" else')
    i_nav = line_of(detail_code, 'Text("高德导航")')
    i_submit = line_of(detail_code, '"提交送达（" + photos.size + " 张照片）"')
    i_remark = line_of(detail_code, '"送达备注（可选）"')
    i_note = line_of(detail_code, 'SectionTitle(Icons.Default.Notes')
    c.ok("六处锚点都在页面上",
         i_photo > 0 and i_nav > 0 and i_thumb > 0 and i_remark > 0 and i_submit > 0 and i_note > 0,
         f"预览@{i_thumb} / 拍照@{i_photo} / 导航@{i_nav} / 完成@{i_submit} / 送达备注@{i_remark} / 内部备注@{i_note}")
    c.ok("照片预览在拍照按钮上面（L-50：「把那个图片预览放到那个拍照按钮的上面」）",
         0 < i_thumb < i_photo, f"{i_thumb} < {i_photo}")
    c.ok("拍照按钮在导航按钮上面（司机那一颗）", 0 < i_photo < i_nav, f"{i_photo} < {i_nav}")
    c.ok("完成按钮在导航下面（L-50：「完成订单就放在导航的下面，我画了那个圆圈的」）",
         i_nav < i_submit, f"{i_nav} < {i_submit}")
    i_gap16 = line_of(detail_code, "Spacer(Modifier.height(16.dp))")
    c.ok("完成按钮跟导航之间隔着 16dp（L-50：「稍微隔点距离，省得出现误触」）",
         i_nav < i_gap16 < i_submit,
         f"导航@{i_nav} / 16dp@{i_gap16} / 完成@{i_submit} —— 中间那道 Spacer 没了就是又贴在一起了")
    c.ok("送达备注在完成按钮下面（两块备注都在最底）", i_submit < i_remark, f"{i_submit} < {i_remark}")
    c.ok("内部备注在送达备注下面（L-49 / L-50：内部备注沉到这一页最底）", i_remark < i_note, f"{i_remark} < {i_note}")

    print("\n== 4. 完成入口：至少一张照片才出现（所有司机一律，含挂车 · 台账 L-15）==")
    # 2026-10-07（台账 L-49 / CHG-0079，真机 emulator-5554 取证）：这道闸门原来是 **DSL 级**的
    # `if (role == DRIVER && COMPLETABLE && photos.isNotEmpty()) { item { … } }`。真机上拍完一张，
    # VM 里已经是 1 张、DetailBody 也按 1 张跑了，可那个 item **压根没注册过** ⇒ 之后再也不会被组合
    # （LazyColumn 的 item 闭包不随外层参数刷新），司机看到的页面纹丝不动、交不了单。
    # 修法：完成块**留在司机动作块那个 item 里**（它首帧就注册），闸门降成块内的一道 if。
    # ⚠️ 2026-10-07 台账 L-50 / CHG-0080 之后：完成块与预览都进了司机动作块，「送达凭证」那张卡撤了，
    # 所以整页现在**只剩这一处** item 读实时值（n_live == 1）—— 它要是被挪走，拍完照那张卡就停在旧值上。
    c.present("完成块的闸门在 item 内部（没照片时那个 item 也必须已经注册）",
              detail_code,
              r"if \(photos\.isNotEmpty\(\)\) \{\s*\n\s*Spacer\(Modifier\.height\(16\.dp\)\)\s*\n"
              r"\s*Column\(verticalArrangement = Arrangement\.spacedBy\(10\.dp\)\) \{")
    c.absent("⛔ 完成块不许再退回 DSL 级闸门（那张 item 没照片时根本不会注册）",
             detail_code,
             r"photos\.isNotEmpty\(\)\s*\n\s*\) \{\s*\n\s*item \{")
    c.present("照片在 item 里读**实时值**（val photos = photosOf()）", detail_code, r"val photos = photosOf\(\)")
    n_live = detail_code.count("val photos = photosOf()")
    c.ok("司机动作块那一处 item 读了实时值（L-50 之后整页只剩这一处）",
         n_live >= 1, f"只数到 {n_live} 处 —— 这处没了，拍完照整块动作卡就停在旧值上")
    c.present("DetailBody 收的是取值函数（photosOf: () -> List<String>）", detail_code,
              r"photosOf: \(\) -> List<String> = \{ emptyList\(\) \},")
    c.present("调用处传的也是取值函数（photosOf = { vm.capturedPhotos }）", detail_code,
              r"photosOf = \{ vm\.capturedPhotos \},")
    c.absent("⛔ 不许把照片退回列表快照（photos = vm.capturedPhotos）—— 真机上司机交不了单",
             detail_code, r"photos = vm\.capturedPhotos,")
    c.present("收款方式那颗「收取现金（N 张）」还在", detail_code, r'"收取现金（" \+ photos\.size \+ " 张）"')
    c.present("「挂账（N 张）」还在", detail_code, r'"挂账（" \+ photos\.size \+ " 张）"')
    c.present("第二道门还在（VM 里那颗空照片拦截）", vm_code,
              r'if \(capturedPhotos\.isEmpty\(\)\) \{\s*\n\s*error = "请至少拍摄一张送达照片"')
    # 2026-10-06（台账 L-15）：这一组从前钉的是"挂车直结那一支仍在"—— 用户说挂车也要拍照，
    # 那一支已经撤掉了，所以断言反过来：界面里不许再有那个分支、也不许再有那三颗按钮。
    c.absent("界面里不再有「挂车直结」那一支（freightVisible 分支）", detail_code, r"if \(order\.freightVisible\) \{")
    c.absent("直结的三颗按钮都不在了（`onDirectCompleteClick` 参数行 / 调用点一律不许出现）", detail_code, r"onDirectCompleteClick")
    c.absent("动作卡上不再有「完成订单」这种一步完成的入口", detail_code, r'Text\("完成订单", style')
    c.present("拍照送达那颗入口还在（同一处闸门以内）", detail_code, r"onClick = onCaptureClick,")
    i_direct = vm_code.find("fun completeDirect(")
    i_deliver = vm_code.find("fun completeDelivery(")
    seg = vm_code[i_direct:i_deliver] if 0 <= i_direct < i_deliver else ""
    c.ok("completeDirect（老包 / 接口兼容那条路）**不**碰 capturedPhotos",
         bool(seg) and "capturedPhotos" not in seg,
         "界面已经不走它了；它反过来要求照片＝老版本 APK 直接 400（服务端那道门已经收紧）")

    print("\n== 5. 内部备注：两道角色门一字未松（台账 L-05） ==")
    c.present("界面只读门仍在（司机 / 派单员才看得到那一行）", detail_code,
              r'if \(role == Role\.DRIVER \|\| role == Role\.DISPATCHER\) \{[\s\S]{0,200}?InfoRow\("内部备注", order\.internalNotes\)')
    i_guard = detail_code.rfind("if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE) {",
                                0, detail_code.find("SectionTitle(Icons.Default.Notes"))
    # ⚠️ 用 `onClick = onSaveNote,` 那一处（卡片里真正绑按钮的地方）—— 直接找 `onSaveNote` 会先
    #    命中 DetailBody 的形参表（它在文件很前面），断言会变成"永远成立"的假绿。
    i_save = detail_code.find("onClick = onSaveNote,")
    c.ok("写备注那一格在司机门以内（不是谁都能写）", 0 < i_guard < i_save,
         f"guard@{line_of(detail_code, 'if (role == Role.DRIVER && order.status in OrderStatusModel.COMPLETABLE) {')} / onSaveNote@{line_of(detail_code, 'onSaveNote')}")
    resp = read(RESPONSE)
    c.present("后端读门：货主拿到的 internal_notes 是空串", resp, r'data\["internal_notes"\] = ""')
    api = read(DELIVERY_API)
    note_api = endpoint_block(api, '@router.post("/{order_id}/driver-note"')
    c.ok("driver-note 端点本体找得到（下面五条都只在这一段里找）",
         len(note_api) > 200, f"只切到 {len(note_api)} 字符")
    c.present("后端写门①：要 ORDER_INTERNAL_NOTE 权限", note_api,
              r"require_permission\(Permission\.ORDER_INTERNAL_NOTE\)")
    c.present("后端写门②：只放 DRIVER / DISPATCHER", note_api,
              r"role not in \(UserRole\.DRIVER\.value, UserRole\.DISPATCHER\.value\)")
    c.present("后端写门③：403 真的返回给越权角色", note_api,
              r'raise HTTPException\(status_code=403, detail="无权操作"\)')
    c.present("后端写门④：司机必须是这一单的司机", note_api, r"order\.driver_id != current\.id")
    c.present("后端写门⑤：追加前后取行锁（并发追加不许互相吃掉）", note_api,
              r"order = lock_order_row\(db, order\)")
    c.present("后端写门⑥：写进去是**累加**（append-only 的实据）", note_api,
              r'prefix = f"\[司机 \{local_stamp\(\)\}\] "[\s\S]{0,400}?order\.internal_notes \+= prefix \+ body\.note\.strip\(\)')
    c.present("字段还在（货主拿到空串而不是缺字段）", read(SCHEMA), r"internal_notes: str")

    print("\n== 6. append-only 没被写成「编辑历史」 ==")
    c.present("noteText 初始就是空（不回填）", vm_code, r'var noteText by mutableStateOf\(""\)')
    repo_backfill = []
    for p in list(kts) + [ROOT / "backend/app/api/v1/orders_delivery.py"]:
        t = code_only(read(p))
        if re.search(r"noteText = [^\n]*driverRemark", t):
            repo_backfill.append(str(p.relative_to(ROOT)))
    c.ok("全仓没有人把 driverRemark 抄进 noteText（旧代码就是这么干的）", not repo_backfill,
         "；".join(repo_backfill))
    c.present("页面文案明说这是「追加一条」", detail_code, r"写进去是追加一条")
    c.present("输入框标题明说「再写一条」", detail_code, r'"再写一条备注（与派单员可见）"')
    c.present("写成功后清空输入框（写完还能接着写）", vm_code,
              r"container\.repo\.driverNote\(orderId, note\)\s*\n\s*(?://[^\n]*\n\s*)*noteText = \"\"")
    c.present("saveNote 不再关任何弹窗", vm_code, r"fun saveNote\(\) \{[\s\S]{0,600}?\n    \}")

    print("\n== 7. 货物破损只剩一份 ==")
    total = len(re.findall(r"DamageCard\(", detail_code))
    defs = len(re.findall(r"fun DamageCard\(", detail_code))
    c.ok(f"DamageCard 的调用点只有 1 处（定义 {defs} + 调用 {total - defs}）", total - defs == 1,
         f"找到 {total - defs} 处调用（抽屉里那份不该再回来）")
    c.present("页面那份破损卡片仍然只给可完成的司机",
              detail_code,
              r"if \(role == Role\.DRIVER && order\.status in OrderStatusModel\.COMPLETABLE\) \{\s*\n\s*item \{\s*\n\s*DamageCard\(")

    print("\n== 8. 防静默空转 ==")
    c.ok(f"扫到的 .kt 数量 {len(kts)} >= {MIN_KT}", len(kts) >= MIN_KT, "目录被搬走了？")
    missing = [str(p.relative_to(ROOT)) for p in REQUIRED_FILES if not p.exists()]
    c.ok(f"{len(REQUIRED_FILES)} 个关键文件都在", not missing, "；".join(missing))

    print("\n" + "=" * 60)
    if c.fails:
        print(f"❌ {len(c.fails)} 项不通过：")
        for f in c.fails:
            print("   - " + f)
        return 1
    print(f"✅ 全部 {c.passes} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
