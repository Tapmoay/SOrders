package com.tapmoay.sorders.ai

/**
 * 撤回专用的**恢复动作**（`POST /xxx/{id}/restore`）。
 *
 * ### 为什么单独一个文件
 * 它和 [AiWriteCrudHandlers] 里的普通动作长得不一样：普通动作收**名字**（要先解析成编号），
 * 而撤回拿到的是**编号**——被软删的记录已经从名册里消失了，按名字根本找不到它。
 * 单独放还有一个实际好处：红线是靠"卡片摘要那一行"来定位会渲染到屏幕上的文案的，
 * 这里的明细是规格的一部分、不是手写卡片，分开就不会被误判。
 *
 * ### 少了 `undoOnly` 的后果
 * 模型清单里会多出一批"能看见但一定失败"的动作，而红线早就把这一类列为最坏的 bug。
 */
/**
 * 一个**只给撤回用**的恢复动作（`POST /xxx/{id}/restore`）。
 *
 * ### 它和模型用的那些动作长得不一样
 * 模型的每个动作都收**名字**（要先解析成编号），而撤回拿到的是**编号**——
 * 因为被软删的记录已经从名册里消失了，按名字根本找不到它。
 * 所以这类动作 `undoOnly = true`：只可能被 [AiWriteService.offerUndo]
 * 用**已经拼好的 payload** 调起来，永远不会出现在模型的动作清单里。
 *
 * 少了 `undoOnly` 的后果很具体：模型清单里会多出一批"能看见但一定失败"的动作，
 * 而红线早就把"能看见但用不了"列为最坏的一类 bug。
 */
internal fun restoreAction(
    cn: String,
    id: String,
    group: String,
    /** 真正的恢复调用。参数是**编号**。 */
    call: suspend (AiWriteDataSource, Long) -> Unit,
) = AiWriteAction(
    id = id,
    title = "恢复$cn",
    // 撤回的风险 = "把它加回来"：不产生新东西、也不影响别人，所以是 MEDIUM。
    risk = AiWriteRisk.MEDIUM,
    group = group,
    // ⚠️ 变量后面紧跟中文时必须写成 `${cn}`：Kotlin 的标识符允许 Unicode 字母，
    //    写成 `$cn恢复回来` 会被解析成一个叫「cn恢复回来」的变量 → 编译不过。
    blurb = "把删掉的${cn}恢复回来（撤回路径专用，模型看不到它）。",
    params = emptyList(),
    crud = CrudSpec(
        targets = listOf(
            AiTargetSpec(
                param = "target_id",
                cn = cn,
                key = "target_id",
                hint = "要恢复哪一条（内部编号，由撤回入口带过来）",
                lookup = { _, _ -> emptyList() },
            ),
        ),
        fields = emptyList(),
        headline = { c -> "恢复${cn}：${c.ref("target_id")?.label ?: "（刚才删掉的那一条）"}" },
        details = {
            listOf(
                "把刚才删掉的那一条恢复回来（后台是伪装删除：行还在，逐字段照搬）",
                "恢复之后编号、图片、坐标、备注都和删掉之前一模一样",
            )
        },
        commit = { ds, p -> p.reqLong("target_id").let { call(ds, it) } },
    ),
    undoOnly = true,
)
