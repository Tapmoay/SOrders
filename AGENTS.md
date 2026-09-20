# AI / 代码生成上下文

实现本仓库「派单送货管理系统」时，请先阅读并按以下文档执行业务与集成约定：

1. [docs/PROJECT_OVERVIEW.md](docs/PROJECT_OVERVIEW.md) — 三端职责、主流程、推荐技术栈与非功能基线  
2. [docs/DOMAIN_MODEL.md](docs/DOMAIN_MODEL.md) — 订单状态机、权限矩阵、派单员审计字段  
3. [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) — 高德、导出、WebSocket/消息队列、消息中心、离线队列  

完整需求原文：[requirements.md](requirements.md)。

## ⚠️ 动手前先看：这个仓库**同时有多个 AI 会话在改代码**

用户 2026-09-20 明确要求：**谁要改什么，必须先声明**（否则会出现"你在这个文件、他在那个文件"最后互相覆盖）。

→ [docs/AI_WORK_CLAIM.md](docs/AI_WORK_CLAIM.md) — **改动声明页**：谁正在进行、改哪些文件、明确不碰哪些文件、共享文件的交叉改动记录。

三条约定（细则见该文件）：

1. 动手前在「进行中」追加一行（谁 / 什么时候 / 改什么 / 文件清单）；做完移到「已完成」。
2. 别人正在改的文件**不要同时改**；非改不可的共享文件（`Apis.kt` / `Dtos.kt` / `AppRepository.kt` / `enums.py` / `ReportCenter.kt` …）先重读最新内容、**只做追加式改动**，并在「交叉点」记一笔。
3. 声明里写了「明确不碰」的文件，等于对方正在改——即使你只改一行，也先问用户。

## 项目地图（了解全貌）

[docs/PROJECT_MAP/INDEX.md](docs/PROJECT_MAP/INDEX.md) — 地图索引与文档导航（架构、后端 API、Android、测试、设计系统、端到端流程）。

## 刚接手 / 要动核心代码前：先看审计交接

工作区里有**大量未提交改动**，其中很大一部分来自一轮全系统漏洞审计（2026-09-19）。
动核心循环、钱、AI 写链路之前，先花两分钟看这两份：

1. [**_archive/audit/HANDOVER.md**](_archive/audit/HANDOVER.md) — **审计交接文档**：
   改了什么、为什么；**知道但没改**的（等你拍板的产品决策 + 排在后面的缺陷）；**没探查**的范围（明确空白）。
2. [_archive/audit/FINDINGS.md](_archive/audit/FINDINGS.md) — 逐轮台账（证据 `文件:行号`、修法、待拍板 15 条）。

## 改动前必做：先查定位表，不要先全库 grep

**接手任何"改某个功能"的需求，第一步是查 [docs/PROJECT_MAP/08_CODE_LOCATOR.md](docs/PROJECT_MAP/08_CODE_LOCATOR.md)，不是全库搜索。**

原因：同一个业务概念在代码里通常散落 4~14 个文件，grep 只给候选，要读完才知道哪个是核心——这正是"读了十几个文件才找到该改哪个"的根源。定位表直接给出「核心文件 / 附带文件 / 注意」。

三条硬约定：

1. **先查表 → 只读核心文件**。表里没覆盖的功能，再去 grep，并顺手把该功能补进表里。
2. **改动了表里列出的「核心文件」时，同步更新对应行**。过期地图比没有地图更糟：没有地图时你会去读代码拿一手真相，有错地图时你会相信结论直接动手。
3. **想知道"状态/枚举/业务分类叫什么"，先读 `backend/app/models/enums.py`**——整个领域词汇表都在那 126 行里，胜过读 10 个 API 文件。

## 查接口/权限：用端点索引，不要通读 API 文件

**问"某个 URL 落在哪个函数""这个接口谁能调" → grep [docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md](docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md)（155 个端点 / 精确行号 / 授权列）。**

它是机器生成的（改动后端 API 后重跑 `cd backend && python -m scripts.gen_endpoint_index --out ../docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md`，加 `--check` 可校验是否过期）。**grep 命中一行就够，不要通读**——它比定位表大。

## 改完必跑：一条命令跑完所有静态检查

```
python _tools/qa/_check_all.py          # 全部静态检查（当前 34 个脚本，约一分钟）
python _tools/qa/_check_all.py --deep   # 再加 48 份反向验证（几分钟，改红线时才要）
python _tools/qa/_check_all.py --list   # 只列清单不跑（看它到底都在查什么）
```

> ⚠️ 上面这两个数字会随脚本增删变化（**清单是自己算的**，不手写）；
> 以 `_check_all.py` 第一行打印的"共 N 个检查脚本"为准。

⚠️ **跑 `--deep`（反向验证）的时候不要改源码**：它会先拍快照，跑完把与快照不一致的文件写回去，
并发做的修改会**被一起抹掉**（实测被抹掉过 15 个文件）。而并发的**检查**会自动拒绝出结论
（`_airepo.refuse_if_injecting`：那一刻源码里带着注入的 bug，结论不可信）。

**为什么要有这一条**：这个仓库有过一次"红线红了整整一轮没人知道"——检查本身是对的，但**收尾清单是手写的**，新写的检查不在那张清单里。所以清单现在**自己算**（`_tools/*/_check_*.py` + 任何声明了 `--check` 的脚本），加一个新检查脚本不需要谁记得来登记。

**新增功能时同样适用**（用户 2026-09-19 的原话：「每次增加一个新功能的时候，我们都要给 AI 开一个后路」）：

- 后端新增**写端点** → `_tools/ai/_write_coverage.py --check` 会红，除非**同时**加一个 AI 动作，或在它的 `EXCLUDED` 表里写一条"不做"的理由；
- App 新增**功能模块 / 读能力 / 写能力域** → `_tools/ai/_app_feature_coverage.py --check` 会红（能力没被任何模块认领＝用户从模块看找不到它）；
- 新增**审计动作码**（`OperationAction`）→ `_tools/ai/_check_action_labels.py` 会红，除非 `ui/dispatcher/ReportCenter.kt::actionLabel` 里有中文名（否则审计卡片上直接显示原始码）。
