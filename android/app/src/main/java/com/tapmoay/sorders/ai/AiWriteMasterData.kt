package com.tapmoay.sorders.ai

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.put
import kotlinx.serialization.json.buildJsonObject

/**
 * 主数据管理动作（商品 / 批发商定价 / 库存 / 账号与收费规则）。
 *
 * ### 这一批的档位是怎么定的
 * 判据始终是**后果的形状**，不是"操作看起来重不重"：
 *
 * | 动作 | 档位 | 为什么 |
 * | --- | --- | --- |
 * | 新增商品、改商品名/单价/单位/报警值 | MEDIUM | 改的是**以后**怎么卖；已下的单有价格快照，不受影响；随时能改回 |
 * | 上下架商品 | MEDIUM | 一下架就不能下单了——影响面大但一眼可见、一下就能恢复 |
 * | 删除商品 | HIGH | 撤不回来 |
 * | 设/改/删批发商专属价 | MEDIUM | **只影响这一个批发商看到的价格**，可改回 |
 * | 批量调价 | HIGH | 一次动多个批发商 × 多个商品，卡片列不全，改错了也很难逐条查回来 |
 * | 库存调整 | HIGH | 直接决定"还能不能下单"，而**账面库存和实物对不上是查不出来的** |
 * | 新建账号 / 改密码 / 停用 / 换角色 / 删账号 | HIGH | 动的是**别人的登录凭据和身份** |
 * | 改司机收费规则 | HIGH | 决定这个司机以后怎么算钱——算错了要等下个月对账才发现 |
 * | 设/取消批发商身份 | HIGH | 一改，这个货主的**整个价格体系就换了** |
 * | 改账号姓名手机号 | MEDIUM | 只是资料，不影响钱和权限 |
 */

// ============================================================== 专用目标

/** 批发商专属价：按「批发商 + 商品」定位到那条规则。 */
private fun targetPriceRule() = AiTargetSpec(
    param = "rule", cn = "批发商专属价", key = "rule_id",
    hint = "「批发商名 商品名」（如「城东水果批发 红富士苹果」）。**不确定就先查一下有哪些专属价**",
    lookup = { ds, _ -> ds.priceRules() },
)

// ============================================================== 动作清单

internal object AiWriteMasterData {

    val ALL: List<AiWriteAction> = listOf(
        // ---------------------------------------------------------- 商品
        crud(
            id = AiWrites.PRODUCTS_CREATE,
            title = "新增商品",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_PRODUCT,
            blurb = "新建一个商品（名称、默认单价、单位、初始库存、库存报警阈值）。建好后就能在订单里选到它。",
            fields = listOf(
                textField("name", "商品名", "必填，如「红富士苹果」", required = true, maxChars = 64),
                moneyField("price", "默认单价（元）", "只传数字；不填按 0 建，之后可以在商品管理里改", key = "default_unit_price"),
                textField("unit", "单位", "如「件」「斤」「箱」", maxChars = 8),
                AiFieldSpec("stock", "初始库存", AiFieldType.NON_NEGATIVE, "只传数字（0 合法）；不填按 0"),
                AiFieldSpec("alert", "库存报警阈值", AiFieldType.NON_NEGATIVE, "库存 ≤ 这个数就报警；填 0 = 不报警", key = "low_stock_alert"),
            ),
            headline = { c -> "新增商品：${c.str("name")}" },
            details = { c ->
                buildList {
                    add("默认单价：${c.str("price") ?: "0.00"} 元")
                    if (c.str("unit") != null) add("单位：${c.str("unit")}")
                    if (c.str("stock") != null) add("初始库存：${c.str("stock")}")
                    if (c.str("alert") != null) add("库存报警阈值：${c.str("alert")}")
                    // ⚠️ 成本价**故意不在这里**：成本字段是红线，不许进模型上下文，
                    // 所以也不许由模型来设。要填成本请在商品管理页面上填。
                    add("成本价：未设置（要填请在「商品管理」页面填）")
                }
            },
        ) { ds, p ->
            ds.createProduct(
                name = p.req("name"),
                defaultUnitPrice = p.str("default_unit_price") ?: "0",
                unit = p.str("unit").orEmpty(),
                stock = p.str("stock")?.toIntOrNull() ?: 0,
                lowStockAlert = p.str("low_stock_alert")?.toIntOrNull() ?: 0,
            )
        },

        crud(
            id = AiWrites.PRODUCTS_UPDATE,
            title = "改商品",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_PRODUCT,
            blurb = "改商品的名称、默认单价、单位、库存报警阈值、成本价。**只填要改的那几项，没填的不动。**",
            targets = listOf(targetProduct()),
            fields = listOf(
                textField("name", "新商品名", "要改成什么名字；不改就不填", maxChars = 64),
                moneyField("price", "新默认单价（元）", "只传数字", key = "default_unit_price"),
                textField("unit", "新单位", "如「件」「斤」", maxChars = 8),
                AiFieldSpec("alert", "新报警阈值", AiFieldType.NON_NEGATIVE, "库存 ≤ 这个数就报警；填 0 = 不报警", key = "low_stock_alert"),
                // 成本价（用户 2026-09-19：「成本价也是可以进行调整的」）。
                // ⚠️ 门在 `AiWriteService`（开关关着就不写进去），卡片上不能承诺它会生效 ——
                //    所以说明里写清"要用户先打开那个开关"。
                moneyField("cost_price", "新成本价（元/单位）", "只传数字。要生效，用户需先在 AI 设置里打开「允许 AI 查看成本与毛利」", key = "cost_price"),
            ),
            headline = { c -> "改商品：${c.ref("product")?.label}" },
            details = { c ->
                listOfNotNull(
                    c.line("name", "名称改成"),
                    c.str("default_unit_price")?.let { "默认单价改成：$it 元" },
                    c.line("unit", "单位改成"),
                    c.str("low_stock_alert")?.let { "库存报警阈值改成：$it" },
                    c.str("cost_price")?.let { "成本价改成：$it 元/单位（会记进成本价历史；开关没开则这一项不生效）" },
                )
            },
        ) { ds, p ->
            ds.updateProduct(
                p.reqLong("product_id"),
                p.pick(setOf("name", "default_unit_price", "unit", "low_stock_alert", "cost_price")),
            )
        },

        crud(
            id = AiWrites.PRODUCTS_SET_ACTIVE,
            title = "商品上架/下架",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_PRODUCT,
            // ⚠️ 措辞必须与后端一致（2026-09-19 审计「声明式 CRUD」专项，高）：
            //    原来这里写「下架后**不能再用它下单**」——**没有任何一侧拦这件事**：
            //    `order_flow.py` 下单只查 `prod.is_deleted`（全仓没有 `Product.is_active` 判定），
            //    而 App 的选品页是 `includeInactive=true` + 只画一个红色「已下架」角标、加号仍可点。
            //    所以"下架"的真实语义是「标记为停用 + 下单页显示警告」，不是"拦住下单"。
            //    卡片承诺一件后端不做的事，用户就会以为拦住 —— 这是本项目反复强调的那类谎。
            blurb = "把商品停用（下架）或重新启用。下架=**在名册里标记为停用**：" +
                "下单页仍会列出它（带「已下架」标记），系统**不会**拦住拿它下单；已有的单不受影响。",
            targets = listOf(targetProduct()),
            fields = listOf(
                boolField("active", "上架还是下架", "true=上架（可用），false=下架（标记为停用）"),
            ),
            headline = { c ->
                val on = c.bool("active") == true
                "${if (on) "上架" else "下架"}商品：${c.ref("product")?.label}"
            },
            details = { c ->
                if (c.bool("active") == true) {
                    listOf("上架后：可以正常下单")
                } else {
                    listOf(
                        "下架后：名册里标记为停用（下单页仍会列出它、并显示「已下架」）",
                        "系统不拦下单：要真拦住，得把商品「删除」（回收站可恢复）",
                        "已有的订单不受影响",
                        "随时可以再上架",
                    )
                }
            },
        ) { ds, p ->
            ds.updateProduct(p.reqLong("product_id"), buildJsonObject { put("is_active", p.bool("active") ?: true) })
        },

        crud(
            id = AiWrites.PRODUCTS_DELETE,
            title = "删除商品",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_PRODUCT,
            blurb = "把商品从商品表里删掉。**已经下过的单、账本、库存流水全都留着**，删错了还能撤回。",
            targets = listOf(targetProduct()),
            headline = { c -> "删除商品：${c.ref("product")?.label}" },
            details = {
                listOf(
                    "删掉之后这个商品在商品表和下单目录里都看不到了",
                    "已经下过的单、账本、库存流水一条都不会少（后台是伪装删除）",
                    "如果只是想让它不能下单，用「下架」更合适（下架之后不用恢复）",
                )
            },
        ) { ds, p ->
            ds.deleteProduct(p.reqLong("product_id"))
        },

        // 按表格批量建商品（用户给一张表 / 挂了一份 Excel）。行为在 [ApplyProductTableHandler]：
        // 它不是 crud（要逐行解析+逐行执行+如实汇报部分成功），所以只把规格挂进来。
        AiWriteProductTable.ACTION,

        // 撤回用的恢复动作（模型看不到，见 [restoreAction]）
        restoreAction("商品", AiWrites.PRODUCTS_RESTORE, AiWrites.G_PRODUCT) { ds, id ->
            ds.restoreProduct(id)
        },

        // -------------------------------------------------- 批发商专属价
        crud(
            id = AiWrites.PRICE_RULES_SET,
            title = "设批发商专属价",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_PRICE,
            blurb = "给**某一个批发商**设某个商品的专属单价（只影响他自己看到的价格，不影响别人）。",
            targets = listOf(targetShipper(), targetProduct()),
            fields = listOf(
                moneyField("price", "专属单价（元）", "只传数字", required = true, key = "special_unit_price"),
            ),
            headline = { c ->
                "设专属价：${c.ref("shipper")?.label} · ${c.ref("product")?.label} → ${c.str("price")} 元"
            },
            details = { c ->
                listOf(
                    "批发商：${c.ref("shipper")?.label}",
                    "商品：${c.ref("product")?.label}",
                    "专属单价：${c.str("price")} 元",
                    "只影响这一个批发商看到的价格；别人的价格不变",
                )
            },
        ) { ds, p ->
            ds.createPriceRule(p.reqLong("shipper_id"), p.reqLong("product_id"), p.req("special_unit_price"))
        },

        crud(
            id = AiWrites.PRICE_RULES_UPDATE,
            title = "改批发商专属价",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_PRICE,
            blurb = "改一条已有的批发商专属价。**只影响这一个批发商。**",
            targets = listOf(targetPriceRule()),
            fields = listOf(
                moneyField("price", "新专属单价（元）", "只传数字", required = true, key = "special_unit_price"),
            ),
            headline = { c -> "改专属价：${c.ref("rule")?.label} → ${c.str("price")} 元" },
            details = { c ->
                listOf(
                    "这一条现在是：${c.ref("rule")?.label}",
                    "改成：${c.str("price")} 元",
                )
            },
        ) { ds, p ->
            ds.updatePriceRule(p.reqLong("rule_id"), p.req("special_unit_price"))
        },

        crud(
            id = AiWrites.PRICE_RULES_DELETE,
            title = "删批发商专属价",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_PRICE,
            blurb = "删掉一条批发商专属价。删掉之后这个批发商按**通用价**买这个商品。",
            targets = listOf(targetPriceRule()),
            headline = { c -> "删除专属价：${c.ref("rule")?.label}" },
            details = { c ->
                listOf(
                    "删掉之后：${c.ref("rule")?.label} 这一条不再生效",
                    "这个批发商会回到通用价，不是不能买",
                )
            },
        ) { ds, p ->
            ds.deletePriceRule(p.reqLong("rule_id"))
        },

        // ---------------------------------------------------- 库存
        crud(
            id = AiWrites.INVENTORY_ADJUST,
            title = "库存调整",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_STOCK,
            blurb = "给某个商品做一次库存增减（入库填正数、出库/报损填负数）。会留下一条库存流水。",
            targets = listOf(targetProduct()),
            fields = listOf(
                AiFieldSpec("change", "增减量", AiFieldType.DELTA, "入库填正数（如 50），出库填负数（如 -20）；不能是 0", required = true),
                textField("note", "原因备注", "如「供应商到货」「盘点差异」——**建议填**，事后查流水全靠它"),
                // 进货价（用户 2026-09-19：「进货的时候也要输入成本价，因为可能这个时间的进货和
                // 那个时间进货的成本价是不一样的」）。
                // ⚠️ 只有用户打开了「允许 AI 查看成本与毛利」才真的写进去（门在 AiWriteService）。
                //    这里**不做条件渲染**：动作表是静态的，藏起来反而会让模型以为"这个功能不存在"，
                //    而它问一句"要我记进货价吗"是完全合理的。真传了而开关关着，后端侧会被丢掉 ——
                //    所以卡片上必须**如实写**这一条，不能承诺"成本价已更新"。
                moneyField("unit_cost", "进货价（元/单位）", "选填，只在入库时有意义；出库不要填", key = "unit_cost"),
            ),
            headline = { c ->
                val d = c.int("change") ?: 0
                "${if (d > 0) "入库" else "出库"}：${c.ref("product")?.label} ${if (d > 0) "+" else ""}$d"
            },
            details = { c ->
                listOfNotNull(
                    "商品：${c.ref("product")?.label}",
                    "增减：${c.int("change")}",
                    c.str("note")?.let { "原因：$it" } ?: "原因：没填（事后查流水会看不出为什么）",
                    c.str("unit_cost")?.let { "这批的进货价：$it 元/单位（同时更新商品成本价、记进成本价历史）" },
                    "这会直接改变「还能不能下单」",
                )
            },
        ) { ds, p ->
            ds.createMovement(
                p.reqLong("product_id"),
                p.reqInt("change"),
                p.str("note").orEmpty(),
                p.str("unit_cost"),
            )
        },

        // -------------------------------------------------- 账号与收费规则
        crud(
            id = AiWrites.USERS_CREATE,
            title = "新建账号",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_USER,
            blurb = "新建一个登录账号（货主 / 司机 / 派单员）。**需要用户提供手机号和初始密码。**",
            fields = listOf(
                textField("phone", "手机号", "必填，登录用", required = true, maxChars = 20),
                textField("password", "初始密码", "必填。必须由用户明确给出——**不要自己编一个**", required = true, maxChars = 64).copy(secret = true),
                enumField(
                    "role", "角色", "必填",
                    listOf("shipper", "driver", "dispatcher"),
                    aliases = mapOf("货主" to "shipper", "司机" to "driver", "派单员" to "dispatcher"),
                ),
                textField("name", "姓名", "如「张三」", maxChars = 32).copy(key = "full_name"),
                boolField("is_member", "是不是批发商", "true=批发商（高级货主，有专属价体系）"),
            ),
            headline = { c ->
                "新建${roleCn(c.str("role"))}账号：${c.str("name") ?: c.str("phone")}"
            },
            details = { c ->
                listOfNotNull(
                    "手机号：${c.str("phone")}",
                    c.str("name")?.let { "姓名：$it" },
                    "角色：${roleCn(c.str("role"))}",
                    if (c.bool("is_member") == true) "身份：批发商（高级货主）" else null,
                    // ⛔ 密码绝不回显，也绝不进 payload 之外的任何地方。
                    "密码：已设置，不显示",
                )
            },
        ) { ds, p ->
            ds.createUser(
                phone = p.req("phone"),
                password = p.req("password"),
                role = p.req("role"),
                // ⚠️ 这里必须用 **payload 的键**（`full_name`），不是参数字段名（`name`）：
                //    字段规格写的是 `textField("name", …).copy(key = "full_name")`，
                //    payload 里存的就是 `full_name`——按 `name` 取永远是空的。
                //    这个 bug 真机实测才暴露（库里的姓名是空的，而卡片上写着「姓名：AI测试账号」、
                //    执行完还回了「已完成：新建货主账号：AI测试账号」）。
                fullName = p.str("full_name").orEmpty(),
                isMember = p.bool("is_member") ?: false,
            )
        },

        crud(
            id = AiWrites.USERS_UPDATE_PROFILE,
            title = "改账号资料",
            risk = AiWriteRisk.MEDIUM,
            group = AiWrites.G_USER,
            blurb = "改账号的姓名或手机号。**不动角色、不动权限、不动收费规则。**",
            targets = listOf(targetUser("账号")),
            fields = listOf(
                // ⚠️ `key` 必须和后端字段名一致（`full_name`，不是 `name`）。
                // 写错的表现是**静默的**：`pick()` 认不出这个键 → payload 空 → PATCH 什么都不改，
                // 而卡片上明明写着"姓名改成 张三丰"。这个 bug 是单测抓到的。
                textField("name", "新姓名", "不改就不填", maxChars = 32).copy(key = "full_name"),
                textField("phone", "新手机号", "不改就不填", maxChars = 20),
            ),
            headline = { c -> "改资料：${c.ref("user")?.label}" },
            details = { c ->
                listOfNotNull(
                    c.line("name", "姓名改成"),
                    c.line("phone", "手机号改成"),
                )
            },
        ) { ds, p ->
            ds.updateUser(p.reqLong("user_id"), p.pick(setOf("full_name", "phone")))
        },

        crud(
            id = AiWrites.USERS_SET_BILLING,
            title = "改司机收费规则",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_USER,
            blurb = "定这个司机**以后怎么算运费**：按件计费（每单算运费）或固定工资（完全不显示运费），" +
                "以及车型和工资额。**只管以后**，已有的单用的是派单当时的快照。",
            targets = listOf(targetUser("司机", role = "driver")),
            fields = listOf(
                enumField(
                    "mode", "计费方式", "必填",
                    listOf("piece", "salary"),
                    aliases = mapOf("计件" to "piece", "按件" to "piece", "按单" to "piece", "工资" to "salary", "固定工资" to "salary"),
                    key = "billing_mode",
                ),
                enumField(
                    "vehicle", "车型", "必填",
                    listOf("small", "large", "trailer"),
                    aliases = mapOf("小货" to "small", "小货车" to "small", "大货" to "large", "大货车" to "large", "挂车" to "trailer"),
                    key = "vehicle_type",
                ),
                moneyField("salary", "月工资（元）", "固定工资时才用得上；按件计费可以不填", positive = false),
            ),
            headline = { c ->
                val m = if (c.str("mode") == "piece") "按件计费" else "固定工资"
                "改收费规则：${c.ref("user")?.label} → $m"
            },
            details = { c ->
                listOfNotNull(
                    "司机：${c.ref("user")?.label}",
                    "计费方式：${if (c.str("mode") == "piece") "按件计费（每单显示运费）" else "固定工资（**不显示运费**）"}",
                    "车型：${vehicleCn(c.str("vehicle"))}",
                    c.str("salary")?.let { "月工资：$it 元" },
                    "只影响以后派的单；已经派出去的单用的是当时的快照",
                )
            },
        ) { ds, p ->
            // ⚠️ `billing_mode` 发出去之前必须**大写**。
            //
            // 后端的消费点比的是 `"PIECE"` / `"SALARY"`（大小写敏感的就有好几处），
            // 而这里以前把小写的 `piece` 原样发出去 → 那个司机在
            // 「司机运费结算」页看不到自己的单、派单页也不给他显示运费输入框
            // （判定成工资制），**而司机账单里又算他是计件**——同一个事实两套结论。
            // 后端现在写入侧也会归一（`normalize_billing_mode`），这里做同样的事是为了
            // 「卡片上写的」和「真正发出去的」不出现两种写法。
            val picked = p.pick(setOf("billing_mode", "vehicle_type", "salary"))
            ds.updateUser(
                p.reqLong("user_id"),
                buildJsonObject {
                    picked.forEach { (k, v) ->
                        // pick() 产出的每一项都是字符串 JsonPrimitive，所以直接取 content
                        put(k, if (k == "billing_mode") JsonPrimitive(v.toString().trim('"').uppercase()) else v)
                    }
                },
            )
        },

        crud(
            id = AiWrites.USERS_SET_ACTIVE,
            title = "启用/停用账号",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_USER,
            blurb = "停用之后这个账号**不能登录**（数据保留）；重新启用就恢复。",
            targets = listOf(targetUser("账号")),
            fields = listOf(boolField("active", "启用还是停用", "true=启用（能登录），false=停用（不能登录）")),
            headline = { c ->
                val on = c.bool("active") == true
                "${if (on) "启用" else "停用"}账号：${c.ref("user")?.label}"
            },
            details = {
                listOf(
                    if (it.bool("active") == true) "启用后：可以正常登录"
                    else "停用后：这个人登录不了，但他的历史数据都还在",
                    "随时可以再改回来",
                )
            },
        ) { ds, p ->
            ds.updateUser(p.reqLong("user_id"), buildJsonObject { put("is_active", p.bool("active") ?: true) })
        },

        crud(
            id = AiWrites.USERS_SET_MEMBER,
            title = "设/取消批发商身份",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_USER,
            blurb = "把货主设成批发商（高级货主）或取消。**批发商有自己的一整套专属价**，一改价格体系就换了。",
            targets = listOf(targetUser("货主")),
            fields = listOf(boolField("member", "是不是批发商", "true=批发商，false=普通货主")),
            headline = { c ->
                val on = c.bool("member") == true
                "${if (on) "设为批发商" else "取消批发商"}：${c.ref("user")?.label}"
            },
            details = { c ->
                listOf(
                    "货主：${c.ref("user")?.label}",
                    if (c.bool("member") == true) {
                        "设成批发商后：他的价格体系换成批发商专属价那一套，已配好的专属价才开始生效"
                    } else {
                        "取消后：他按普通货主的价格买，原来配的专属价不再生效（但不会被删掉）"
                    },
                )
            },
        ) { ds, p ->
            ds.updateUser(p.reqLong("user_id"), buildJsonObject { put("is_member", p.bool("member") ?: true) })
        },

        crud(
            id = AiWrites.USERS_SWAP_ROLE,
            title = "货主↔司机互换",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_USER,
            blurb = "把一个人的身份在货主和司机之间对调。**这是身份级别的操作**，会影响他能看到什么、能做什么。",
            targets = listOf(targetUser("账号")),
            headline = { c -> "身份互换：${c.ref("user")?.label}" },
            details = {
                listOf(
                    "账号：${it.ref("user")?.label}",
                    "货主 ↔ 司机 直接对调（当前是货主就变司机，反之亦然）",
                    "互换后他的模块、能做的事、看到的单都会变",
                )
            },
        ) { ds, p ->
            ds.swapUserRole(p.reqLong("user_id"))
        },

        crud(
            id = AiWrites.USERS_SET_PASSWORD,
            title = "改登录密码",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_USER,
            blurb = "重置某个账号的登录密码。**新密码必须由用户明确给出。**",
            targets = listOf(targetUser("账号")),
            fields = listOf(
                textField("password", "新密码", "必填。必须由用户明确给出——**不要自己编一个**", required = true, maxChars = 64).copy(secret = true),
            ),
            headline = { c -> "改密码：${c.ref("user")?.label}" },
            details = {
                listOf(
                    "账号：${it.ref("user")?.label}",
                    "新密码：已设置，不显示",
                    "改完之后这个人要用新密码登录",
                )
            },
        ) { ds, p ->
            ds.updateUser(p.reqLong("user_id"), p.pick(setOf("password")))
        },

        crud(
            id = AiWrites.USERS_DELETE,
            title = "删除账号",
            risk = AiWriteRisk.HIGH,
            group = AiWrites.G_USER,
            blurb = "删除一个登录账号（软删，删错了可以撤回）。会**释放手机号**，同号可以重新建号。",
            targets = listOf(targetUser("账号")),
            headline = { c -> "删除账号：${c.ref("user")?.label}" },
            details = {
                // ⚠️ 这段文案原来写的是「如果他还有订单/账目，建议改成「停用」而不是删除——
                //    停用不删数据」。**后半句是错的**：后端的 DELETE 其实是**软删**
                //    （`is_active=False` + 把手机号/用户名改成 `xxx_del{id}`，行仍留在库里可追溯）。
                //    两者真正的区别是：**删除会释放手机号（同号可以重新建号）**。
                //    卡片上写错这一句，用户就没法在「停用」和「删除」之间做对选择。
                //    （真机实测：删完账号还在库里、手机号变成 `13900001234_del160`。）
                listOf(
                    "账号：${it.ref("user")?.label}",
                    "删掉之后：立刻不能登录，并释放手机号（同一个号可以重新建一个）",
                    "账号数据仍留在库里可追溯（这一点和「停用」一样）",
                    "区别：停用会保留原手机号，以后可以直接再启用；删掉之后这个号就空出来了",
                )
            },
        ) { ds, p ->
            ds.deleteUser(p.reqLong("user_id"))
        },

        // 撤回用的恢复动作：手机号会去掉 `_del{id}` 后缀还回来（冲突时保留现号并写日志）
        restoreAction("账号", AiWrites.USERS_RESTORE, AiWrites.G_USER) { ds, id ->
            ds.restoreUser(id)
        },
    )

    // -------------------------------------------------------------- 小工具

    private fun roleCn(raw: String?): String = when (raw) {
        "shipper" -> "货主"
        "driver" -> "司机"
        "dispatcher" -> "派单员"
        else -> "（未知角色）"
    }

    private fun vehicleCn(raw: String?): String = when (raw) {
        "small" -> "小货车"
        "large" -> "大货车"
        "trailer" -> "挂车"
        null, "" -> "未设置"
        else -> raw
    }

    /**
     * 把「目标 + 字段」的规格装成一个动作。
     *
     * 关键：**`params`（喂给模型的参数表）由规格推导出来**，不是另写一份。
     * 两份写法一定会走散，而走散的表现是"模型按清单传参、代码说不认识"。
     * 推导本体在 [crudParams]（与 `AiWriteBasicData` 里那个同名工厂**共用同一份**）。
     */
    private fun crud(
        id: String,
        title: String,
        risk: AiWriteRisk,
        group: String,
        blurb: String,
        targets: List<AiTargetSpec> = emptyList(),
        fields: List<AiFieldSpec> = emptyList(),
        headline: (AiWriteCard) -> String,
        details: (AiWriteCard) -> List<String>,
        commit: suspend (AiWriteDataSource, JsonObject) -> Unit,
    ): AiWriteAction = AiWriteAction(
        id = id,
        title = title,
        risk = risk,
        group = group,
        blurb = blurb,
        params = crudParams(targets, fields),
        crud = CrudSpec(targets, fields, headline, details, commit),
    )
}

// ------------------------------------------------------------------ payload 取值

internal fun JsonObject.str(key: String): String? =
    (this[key] as? JsonPrimitive)?.contentOrNull?.takeIf { it.isNotBlank() }

internal fun JsonObject.req(key: String): String =
    str(key) ?: error("payload 缺少必填字段 $key（App 内部错误，不该发生）")

internal fun JsonObject.reqLong(key: String): Long =
    str(key)?.toLongOrNull() ?: error("payload 缺少必填字段 $key（App 内部错误，不该发生）")

internal fun JsonObject.reqInt(key: String): Int =
    str(key)?.toIntOrNull() ?: error("payload 缺少必填字段 $key（App 内部错误，不该发生）")

internal fun JsonObject.bool(key: String): Boolean? = str(key)?.toBooleanStrictOrNull()

/** 只挑指定键、且只挑填了的，拼成 PATCH 用的部分更新体（null/缺省 = 不改这一项）。 */
internal fun JsonObject.pick(keys: Set<String>): JsonObject = buildJsonObject {
    for (k in keys) str(k)?.let { put(k, it) }
}
