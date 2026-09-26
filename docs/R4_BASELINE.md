# 真实世界基线（BASELINE）

> **本文件由 `_tools/baseline/_capture_baseline.py` 生成，不要手改**（报告 §13：会变化的数字一律不手写）。
> 重新采：`python _tools/baseline/_capture_baseline.py --tests --prod --out docs/BASELINE.md`

> 本次采集时间：2026-09-27T00:15:24　｜　快照：`_tools/baseline/r4-before/2026-09-27/baseline.json`

> 说明：这一页回答的是「现在到底是什么样」，不回答「应该改成什么样」——后者在 [RECTIFICATION_PLAN.md](RECTIFICATION_PLAN.md)。


## 1. 与报告成文时的对照（漂移一眼可见）

| 项 | 报告成文时 | 本次实测 | 差额 | 来源 |
|---|---:|---:|---:|---|
| 端点数 | 227 | 229 | +2 | L57 / L940 |
| 数据库表数（模型） | — | 47 | — | — |
| service 文件数 | 41 | 44 | +3 | L57 |
| api/v1 行数 | 13724 | 13292 | -432 | L395 |
| services 行数 | 9837 | 10326 | +489 | L396 |
| orders.py 行数 | 2055 | 30 | -2025 | L402 |
| schema_bootstrap.py 行数 | 1697 | 1773 | +76 | L142 / L234 |
| 静态检查数 | 92 | 119 | +27 | L332 / L1454 |
| 反向验证数 | 108 | 142 | +34 | L332 / L1454 |
| 后端用例数 | 820 | 1020 | +200 | L334 / L983 |
| 安卓用例数 | 1126 | 1131 | +5 | L335 / L985（源码 @Test 注解口径） |
| docs 文件数 | 502 | 530 | +28 | L915 |
| _tools Python 文件数 | 325 | 405 | +80 | L1454 |

> 报告的数字**不是错误**，它记录的是报告成文那一刻的快照；这一列留着的目的是让「文档写着 92 个检查、实际 92 个」这种话**有机器可核的依据**。


## 2. 本地基线

| 项 | 值 |
|---|---|
| 分支 | p |
| 提交 | c67b2cfea27c01f184c05f6fba60120c768d6851 |
| 最后提交时间 | 2026-09-26T23:56:47+08:00 |
| 领先上游 | 0 |
| 落后上游 | 0 |
| 版本号 VERSION | 0.2.4 |
| 版本号 android | 0.2.4（构建时读 VERSION 文件） |
| 版本号 backend(main.py) | 0.2.4（= 仓库根 VERSION，config.py 运行时读） |
| 端点数（含写） | 229 |
| 其中写端点 | 152 |
| 模型声明表数 | 47 |
| api/v1 总行数 | 13292 |
| services 总行数 | 10326 |
| 静态检查数 | 119 |
| 反向验证脚本数 | 142 |
| 后端用例数 | 1020 |
| 安卓用例数（源码 @Test 注解） | 1131 |
| 安卓最近一次跑到的用例数 | 1160 |
| 安卓用例失败数（最近一次） | 1 |
| 安卓主源码 .kt 数 | 257 |

### 最大的安卓源文件（报告 §11 点名的「大文件」）

| 行数 | 文件 |
|---:|---|
| 5796 | `android/app/src/test/java/com/tapmoay/sorders/ai/AiWriteTest.kt` |
| 2548 | `android/app/src/main/java/com/tapmoay/sorders/ai/AiWrite.kt` |
| 2257 | `android/app/src/main/java/com/tapmoay/sorders/ui/ai/AiChatScreen.kt` |
| 2086 | `android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt` |
| 1960 | `android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteDataSource.kt` |
| 1804 | `android/app/src/main/java/com/tapmoay/sorders/ui/order/OrderDetailScreen.kt` |
| 1616 | `android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt` |
| 1532 | `android/app/src/main/java/com/tapmoay/sorders/ai/AiWriteBasicData.kt` |

### 最大的后端文件

| 行数 | 文件 |
|---:|---|
| 1773 | `backend/app/core/schema_bootstrap.py` |
| 854 | `backend/app/api/v1/ledger.py` |
| 838 | `backend/app/services/accounting_service.py` |
| 780 | `backend/app/services/order_flow.py` |
| 747 | `backend/app/services/place_service.py` |
| 696 | `backend/app/services/message_center.py` |
| 633 | `backend/app/api/v1/shipper_ledger.py` |
| 630 | `backend/app/services/driver_pay.py` |

## 4. 机器判定的风险 / 漂移

| 类别 | 是什么 | 细节 |
|---|---|---|
| 版本漂移 | 版本号多处不一致 | VERSION=0.2.4 ｜ android versionName=0.2.4（构建时读 VERSION 文件） ｜ backend main.py=0.2.4（= 仓库根 VERSION，config.py 运行时读） |
| 测试 | 最近一次安卓单测报告里有失败 | failures=1 |
| 工作区 | 工作区有未提交改动（结构性改造前必须先确认归属） | ?? _tools/qa/_r4_baseline_gate.txt |


## 5. 本次没采到 / 采失败的项（**不许当「一切正常」读**）

- 取不到 frontend/package.json（Vue3 H5 已于 2026-09-25 归档删除，用户拍板不要网页版） → version_frontend 记 None；报告 §20 的「四处同值」现在是三处

