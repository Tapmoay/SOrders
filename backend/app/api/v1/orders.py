"""orders 路由的**装配层**（2026-09-24 整改阶段 4 纯搬迁的收尾）。

这个文件原来是 **2056 行**、25 个端点、50 个函数（报告 §6 点名的"API 层过厚"里最大的一处）。
按报告的办法（**纯搬迁**：URL / 入参 / 出参 / 权限 / 状态机 / 数据库全不变，只改代码组织）拆成 7 个模块：

| 模块 | 装什么 |
|---|---|
| `orders_query.py` | 列表 / 待派计数 / 详情 |
| `orders_assignment.py` | 批量派单 / 派单 / 撤回 / 拆单 / 定价 / 改运费 |
| `orders_delivery.py` | 完成 / 完成带图 / 接单 / 司机备注 / 补导航 / 撤销 |
| `orders_payment.py` | 付款 / 收款（+ 付款家族私有助手） |
| `orders_media.py` | 地址图 / 送达照片 |
| `orders_lifecycle.py` | 创建 / 编辑 / 异常标记 / 回收站恢复 / 删除 |
| `orders_return.py` | 退货（唯一的执行入口） |
| `orders_common.py` | 各模块共用的助手（router **不在**里面，理由见该文件开头） |

每个模块**自己声明** `router = APIRouter(prefix="/orders", tags=["orders"])`，由 `api/v1/router.py` 并列挂载
（报告 §6 的原话就是"统一由 router.py 挂载"）。

⚠️ 为什么拆成"平级的 8 个文件"而不是 `orders/` 包：包形式会改变 `gen_endpoint_index` /
`_gen_ai_read_catalog` 这些**按文件**解析的 AST 工具的口径，而"纯搬迁不许改契约"这条同样适用于
机器读的那份契约（端点索引 / AI 能力表）——实测过：共享 router 会让整批端点从索引里消失。

本模块现在**一个端点都没有**，只保留一个空 `router` 给历史引用用（`api/v1/router.py` 仍挂它，挂空的无害）；
真正的端点全在上面那 7 个模块里。搬迁的等价性证据：`_tools/qa/_api_contract_snapshot.py --diff …`（契约零差异）。
"""

from fastapi import APIRouter

router = APIRouter(prefix="/orders", tags=["orders"])
