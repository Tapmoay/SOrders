package com.tapmoay.sorders.ui.shipper

import com.tapmoay.sorders.data.remote.dto.UserDto

/**
 * 「下单人」这一栏该填谁 —— **全 App 唯一一份判据**。
 *
 * ## 由来（用户 2026-09-22 第二轮）
 * > 「不是说下单吗？下单会**自动填入下单的人的名称和电话号码**，户主和批发商没关系，
 * > 因为他们是**自己下**嘛。但是这里有一点要注意的就是**派单员，他是代理下单**啊，
 * > 所以他**不能填写自己的名称和电话号码**，他要填的是**自动填选的是货主的**……
 * > **选择货主之后，他写的货主的信息就会自动地填入进去**，也就是名称和电话号码。」
 *
 * 于是「下单人」的来源被收成一条：**这一单的货主**。
 * · **货主自己下单**（含批发商）：就是他自己（`/users/me` 的姓名 + 电话）；
 * · **派单员代理下单**：**跟着选中的货主走** —— 一位货主都还没选时**留空**，
 *   ⛔ **绝不回落成派单员自己的姓名/电话**（那正是这一轮要修的 bug：单子记成了派单员下的）。
 *
 * ## 为什么做成纯函数（而不是在 ViewModel 里就地写两遍）
 * 这条判断有两个入口（`init` 里的账号预填、`setShipper` 里的换货主）外加"临时货主"一条支线。
 * 写两遍必然分叉，而分叉的后果**在界面上看不出来**：典型是"换了货主，下单人还是上一位的
 * 姓名 + 电话"——下单人的电话留在单子上，司机到了现场打过去是**别人**。
 * 所以判据只有这一处，并用 JVM 单测钉着（`OrdererPrefillTest`）。
 *
 * ⚠️ 自动填**不是锁死**：这两个框仍然是可改的普通输入框（派单员接电话时"下单人是王老板"
 * 这种情况真实存在）。所以这里只回答"该填什么"，不回答"用户能不能改"。
 */
data class OrdererContact(val name: String, val phone: String)

/**
 * 算这一单的「下单人」。
 *
 * @param ownName 当前登录账号的姓名（`/users/me`；拿不到时退会话里的姓名）
 * @param ownPhone 当前登录账号的电话（`/users/me`）——⛔ 不许拿会话里的 `username` 顶替：
 *   种子/老数据里那可能是人名，填一个**打不通的号**比空着更糟
 * @param proxyMode 登录角色是**派单员**（＝代理下单）。这是整条判断的分水岭：
 *   代理下单时 [ownName]/[ownPhone] **一个字节都不用**
 * @param shipper 代理下单时选中的**已注册货主**（null ＝ 还没选，或选的是临时货主）
 * @param tempShipperName 代理下单时填的**临时货主**（未注册，只有名字）
 */
fun ordererContactFor(
    ownName: String?,
    ownPhone: String?,
    proxyMode: Boolean,
    shipper: UserDto?,
    tempShipperName: String?,
): OrdererContact {
    // ① 货主 / 批发商自己下单：下单人就是他本人（同一套规则，不分批发商与普通货主）。
    if (!proxyMode) return OrdererContact(ownName.orEmpty().trim(), ownPhone.orEmpty().trim())

    // ② 代理下单 + 临时货主（未注册）：库里没有他的号码，所以只填姓名，
    //    电话留给派单员按电话里听到的那个填 —— 编一个出来比空着危险得多。
    val temp = tempShipperName.orEmpty().trim()
    if (temp.isNotEmpty()) return OrdererContact(temp, "")

    // ③ 代理下单 + 已注册货主：姓名与电话都来自这位货主的账号资料。
    val s = shipper ?: return OrdererContact("", "") // 还没选货主 → 留空（⛔ 不是派单员自己）
    return OrdererContact(s.fullName.trim(), s.phone.trim())
}
