# 整改变更报告（2026-09-25 会话：路线图剩余项全部落地）

> **本文件是快照，不是活文档。** 它记录的是 **2026-09-25 这一轮**改了什么、之前什么样、为什么这么改。
> 之后代码还会往前走，**当前状态以这两样为准**：
> `python _tools/qa/_check_all.py`（静态检查）与 `python _tools/qa/_gen_acceptance.py --full --out docs/RECTIFICATION_ACCEPTANCE.md`（逐章验收）。
> 逐轮的叙事过程在 `docs/RECTIFICATION_PLAN.md`（第 56~61 轮）。

---

## 0. 一句话

报告 `docs/ARCHITECTURE_RECTIFICATION.md` 里剩下的五项（§7 / §9 / §14 / §15 / §16），
在这一轮全部落地并**逐项有了机器可复现的验收**；其中 §14（安卓端到端进 CI）
花了 **7 轮**才真正跑通 —— 因为前 6 轮每一次"红"，暴露的都是一个**此前一直被绿灯盖住的真 bug**。

范围：**25 个提交**（`ca39345` → `124c848`，`git log --oneline ca39345^..HEAD` 可数），全部已推到 `origin/new`，每一条都单独可回退。

## 1. 一张表看全貌

| 报告章节 | 之前是什么样 | 现在是什么样 | 提交 |
| --- | --- | --- | --- |
| **§7 钱只有一处实现** | 靠"文件冻结"约定：清单里列了几个钱文件，谁都不许抄 | 显式**契约层** `services/money_contract.py`（`REEXPORTS` 15 条 + PEP 562 惰性转出），消费方一律从它 import；`PENDING` 例外表**清零** | `395226f` |
| **§9 权限统一模型** | 权限点是一张平表；dispatcher 例外写在 `role_has_permission` 函数体里；授权散在各端点函数体内 | 权限点解析成 **resource:action 两维 + Scope 第三维**（26 个点全部有交代）；例外搬进显式的 `BYPASS_ROLES` 表（带理由 + 删除条件）；新增签名级 `DispatcherUser` | `f723bc6` |
| **§15 两个业务指标** | `metrics.NOT_TRACKED` 里挂着 `AI_calls` / `AI_write_confirmed`（"算不出来，先空着"） | 两个指标都**真的能算**：审计行加 `origin` 维（迁移 004）+ AI 调用日表（迁移 005）+ `POST /ai/telemetry`；`NOT_TRACKED = {}` | `467935b` `790d4a4` `7060788` `3b9b0b3` |
| **§14 安卓集成测试进 CI** | 只有"某人在本机起三台模拟器跑一遍" | CI 里有 `常闸 · 安卓端到端`：真模拟器上跑**登录 → 导航 → 下单 → 对账**，**四段全通**；起不来时是**带理由的跳过**（`SKIP:` + 注解），跑挂是红 | `ef6854b` … `38f8ff3`（共 8 个提交） |
| **§16 多实例前置** | 迁移只有**本机文件锁**（同机多进程安全，跨主机不安全） | 加了 **DB 级锁**（MySQL `GET_LOCK`，SQLite 上诚实降级并记日志）；就绪度与剩余 5 道门写成 `docs/MULTI_INSTANCE_READINESS.md`；⛔ **没有真的切多实例** | `ca39345` |

外加一件没在报告里、但这一轮顺手做掉的：**§9 的第二层** —— 把授权从"函数体里的 if"搬成"签名上的依赖"（5 个域，体内门槛 44 → 36）。见 §2.6。

---

## 2. 逐项：之前 → 之后

### 2.1 §7 钱契约（提交 `395226f`）

**之前**：钱的计算确实已经收敛到几处（`order_money` / `driver_pay` / `shipper_settle` / `order_return`），
但"谁必须用哪一处"是靠 `_tools/qa/_check_money_contract.py` 里一张**手写的消费方清单** + 一份 `PENDING` 例外表约束的。
本质是**文件约定**：新写一个消费方，只要它算出来的数恰好对，检查就绿。

**之后**：新增 `backend/app/services/money_contract.py` —— 一张显式的 `REEXPORTS` 表（15 条），
每条写明 `符号 → (模块, 原名)`，配 **PEP 562 的模块级 `__getattr__` 惰性转出**
（为什么必须惰性：`order_flow ↔ order_return` 之间有成环的引用，直接 import 会炸）。
消费方现在**从契约页 import**，检查随之改成"每个钱数只有一处实现、且消费方真的在用它"。
`PENDING` 例外表**清空**（原来挂着 2 个"暂时还从别处拿"的消费方）。

**证据**：`python _tools/qa/_check_money_contract.py` → 全部通过。

⚠️ **与报告原文的偏差（如实记）**：报告点名要建 `OrderMoneyCalculator` / `DriverPayCalculator` / `SettlementService`
三个类。我**没有**建这三个类 —— 理由见 §4.1。

### 2.2 §9 权限统一模型 · 第一层（提交 `f723bc6`）

**之前**：
- 26 个权限点是一张**平表**（`Permission.ORDER_CREATE = "order:create"`），没有"resource / action"两维的结构，
  也没人说得清"这个点对应的是行级过滤还是整表可见"；
- **dispatcher 例外**写在 `role_has_permission` 的**函数体里**（`if key == UserRole.DISPATCHER.value: return True`），
  既没有理由，也没有"什么时候能删掉"的说法；
- AI 读能力裁剪只能靠猜角色。

**之后**：
- `SCOPE_KINDS` + `split()` + `SCOPES`（26 条）：每个权限点都带一个 **Scope**（`all` / `own` / `own_team` …）
  和**一句中文理由**。检查会拦"理由太短""取值不在 `SCOPE_KINDS` 里""没有 Scope 声明"；
- 例外搬进 **`BYPASS_ROLES`** 表：一条声明，带理由、带"什么时候删掉这一条"、带**化石检测**
  （表里写的角色必须真的存在）—— `role_has_permission` 现在只写 `if key in BYPASS_ROLES: return True`；
- 新增 `_tools/qa/_check_permission_model.py`（8 组判据，含"逐个权限点 × 逐个角色"的行为对账）
  + 反向验证 `_reverse_verify_permission_model.py`（**8/8**）。

**证据**：验收页那一行 `_check_permission_points.py` → 「✅ 26 个权限点都有交代（26 个在用、0 个有书面理由）」。

### 2.3 §9 第二层：授权从「函数体」搬到「签名」（提交 `cd1b8f6` `592f41a` `090f9b8` `11cee14` `e0510f1`）

**为什么多做这一层**：第一层把**模型**统一了，但**用法**还没统一 —— 全库还有 44 处
`if user_role_key(current) != UserRole.X.value: raise HTTPException(403, ...)` 散在函数体里。
它有两个真实后果：① 端点索引的「授权」列只能写出"仅登录 + 体内仅允许:派单员"，
**机器读不出真实授权**（AI 读能力裁剪就是靠这一列）；② 同一段两行判断抄几十遍，抄漏一处就是越权口子，
而当时的判据只看得到"有没有登录"。

| 域 | 之前 | 之后 | 体内门槛 |
| --- | --- | --- | --- |
| `expense_categories`（5 个端点） | 5 处 `if user_role_key(...) != DISPATCHER: raise 403` | 签名上 `current: DispatcherUser` | 44 → 41 |
| `cash_flows`（3 个） | 3 处同上 | 同上，并删掉随之无用的 3 个 import | 41 → 39 |
| `expenses`（2 个） | 2 处同上 | 同上 | 39 → 38 |
| `products`（1 个读门） | 体内 `if not role_has_permission(rk, Permission.ORDER_CREATE): raise 403` | 签名上 `Annotated[User, Depends(require_permission(Permission.ORDER_CREATE))]` —— **这就是 §9 说的「require_permission 成为唯一入口」** | 38 → 36 |
| `orders_lifecycle`（2 处无条件门） | 体内双角色判断 + 纯派单员判断 | `require_roles(SHIPPER, DISPATCHER)` + `DispatcherUser` | 36 |

**为什么是"只降不升"的棘轮，而不是"必须为 0"**：有一类门槛**依赖请求内容**，签名级表达不了，例如
`GET /users/{id}`（要么是派单员、要么是你自己）、`GET /orders?deleted_only=`（这个查询参数只有派单员能用）、
`notifications` 那三处（自己的或派单员的，而且返回的是 **404 不是 403**）。硬转只会逼出更糟的形状
（先查库再判，或把 404 改成 403 而改变对外语义）。所以定成棘轮。

**新判据 `_tools/qa/_check_inline_role_gates.py`**（AST 扫，认代码形状不认文字）：
① 总数 ≤ 台账最后一条（只许降）；② 已收敛文件体内必须为 0（防"改完又长回来"）；③ 清单防化石；
④ **台账逐条非增 + 不减必须写「理由:」**（挡"把上限自己调大"这条绕过路径）；⑤ 扫描不许空转。
配反向验证 **10/10**，其中 **2 条是「必须仍然绿」的防误报用例**（不 raise 的角色分支、不由角色决定的 403）。

### 2.4 §15 两个业务指标（提交 `467935b` `790d4a4` `7060788` `3b9b0b3`）

**之前**：`metrics.py` 里有一张 `NOT_TRACKED` 表，挂着两个指标并写明"现在算不出来"：
`AI_calls`（模型被调了几次）与 `AI_write_confirmed`（AI 真的写了几次库）。
表本身是**诚实的**（宁可空着不给假数），但报告 §15 要求把它们**真的补上**。

**之后**（分四步，每一步单独提交）：
1. **`AI_write_confirmed` 能算了**（`467935b`）：审计行加 `origin` 维（迁移 **004**）+ 中间件读 `X-SOrders-Origin` 头
   + `operation_log_service` 落库。指标 = 今日 `origin == ai` 的审计行数；
2. **`AI_calls` 能算了**（`790d4a4`）：新表 `ai_call_daily`（迁移 **005**）+ `POST /api/v1/ai/telemetry`
   （按天 upsert 累加，带 `IntegrityError` 回退）+ `NOT_TRACKED` 清零；
3. **Android 侧标注来源**（`7060788`）：`ClientOrigin`（ThreadLocal + `asContextElement`）+ Retrofit `callFactory`
   自动加头；**只包住真正的写入**（`AiWriteService.commit`），预览不包 —— 包进去只会让后端多记一堆没发生的事；
4. **Android 上报次数**（`3b9b0b3`）：`AiRunResult` 加 `steps`，聊天页把每一轮的步数累加后**一次**上报。

**证据**：`metrics.py` 现在 13 个指标（`sorders_ai_calls_today` / `sorders_ai_write_confirmed_today` 在列），
`NOT_TRACKED: dict[str, str] = {}`。

### 2.5 §14 安卓端到端进 CI —— 这一项花了 7 轮

**之前**：`.github/workflows/gate.yml` 里有快闸 / 静态检查 / 后端用例 / 安卓单测 / AI 读权限对账，
**没有**任何东西在真模拟器上跑过 App。报告 §14 点名的正是这块空白。

**之后**：新增 `常闸 · 安卓端到端（登录 → 导航 → 下单）` 作业（`ef6854b` 起，8 个提交修到通）。
它在 GitHub 托管的 runner 上：起一个空库后端 → 播开发账号与最小业务数据 → 装 App → 起模拟器 →
跑 `_tools/e2e/_flow_login_nav_order.py` → 判定四种结局。

**为什么花了 7 轮**：因为这中间**每一个"红"都是一个真 bug**，而且**前三个此前一直被绿灯盖着**。

| # | 之前（隐藏着的 bug） | 之后（修法） | 提交 |
| --- | --- | --- | --- |
| 1 | runner 上 **KVM 没开** → 模拟器以 `-accel off` 纯软件跑，16 分钟没启动完 → 作业**success**（因为"没跑"被算成通过） | 加 udev 规则开 KVM（官方 README 的修法），并**把"没跑成"改成红** | `d6ba699` |
| 2 | 那个 action 把 `script` **逐行** `sh -c` → `set +e` 管不到后面、变量活不过一行、**行尾 `\` 变成真实参数**（脚本退 2） | 整条流程压成**一行**；加判据「只能一行」 | `9f2e8a1` |
| 3 | 判定步骤分不出"模拟器没起来"与"跑了没结论"（归因错） | 脚本开头写**哨兵 `rc=9`**；加判据「哨兵在最前」 | `a0583e3` |
| 4 | `--check-env` 排在 `adb install` **之前** —— 而它体检的就是「App 装没装」→ **恒 rc=3 跳过**，从落地那天起就不可能跑过 | 先装包再体检；加判据「装包必须在体检前」 | `c13948c` |
| 5 | 后端绑 `127.0.0.1`，App 连 `10.0.2.2` → `Failed to connect`（而体检那步是绿的：**两个网络命名空间**） | 改绑 `0.0.0.0`；加判据「必须绑 0.0.0.0」 | `abe04cd` |
| 6 | 全新安装弹出**系统定位权限窗**挡住工作台（开发机上早被手点过，本地永远复现不出来） | 跑流程前 `pm grant` 四个运行时权限；加判据「预授在跑流程之前」 | `d3fd381` |
| 7 | launcher 被拖到 **ANR**（AVD 只有 2 核 + 软件渲染） | `-cores 4 -memory 4096` + 装完先 `sleep 20` | `15bf02f` |
| 8 | CI 里**选品页是空的**（只播了账号，没有商品/地址）→ 「下单」段卡住，而前两段全绿 | 新增 `backend/scripts/seed_ci_e2e.py`（最小业务数据，幂等，走真实 API）；加判据「必须播业务数据」 | `38f8ff3` |

⛔ **转折点是第 1 条里的那一个字符**：把"没跑成"从 `exit 0` 改成 `exit 1`。
在它之前，bug 1/2/4 全都以 **success** 的样子挂着；在它之后，每一轮都红着说出下一个真问题。

**最终结果**（`Gate @ 38f8ff3`，含一次基础设施重跑）：

```
✅ 环境齐，可以跑
登录  ✅ 登录后进了工作台
导航  ✅ 到了新增订单页（工作台 → 我的订单 → 新增订单）
下单  ✅ 选「红富士苹果 80#」→ 加入清单（1）→ 地址库选「解放路 88 号 3 栋 102」→ 提交订单 ¥128
对账  ✅ 下单前 0 条 → 现在接口返回 1 条（limit=1）
登录 → 导航 → 下单 → 对账 四段全通
```

整轮 `Gate` **success**、`Tests (Parallel)` **success**。

### 2.6 §16 多实例前置（提交 `ca39345`）

**之前**：迁移只有一个 `fcntl` **本机文件锁** —— 同一个容器里的多进程安全，
**跨主机不安全**（两个实例同时启，两边都以为自己是唯一的）。

**之后**：`backend/app/migrations/_runner.py` 加了 **DB 级锁** `_db_lock(engine)`：
MySQL 上走 `GET_LOCK("sorders_migrations", 60)` / `RELEASE_LOCK`，SQLite 上**诚实降级为空操作并记日志**
（不假装锁住了）。顺序写明：**本机 flock → 服务端 GET_LOCK**。
另附 `docs/MULTI_INSTANCE_READINESS.md`：逐条前置条件的证据表 + **仍然剩下的 5 道门**
（必须换 MySQL / 启动自愈每个实例都要跑 / 上传目录要共享 / 定时任务要选主 / nginx upstream）。

⛔ **明确没有做**：没有把生产切成多实例（那是要你拍板的事）。

### 2.7 附：两处「生成物被污染」的修复（提交 `124c848`）

这是我做验收时**顺手抓到的**：验收页 `docs/RECTIFICATION_ACCEPTANCE.md` 里，
「§5 CI 正式接管检查体系」那一行的**结论列填进去的是一段源码**。

真因：`_check_ci_workflows.py` 里我写的 `` `\` `` 在普通字符串里是**非法转义**，
Python 往 **stderr** 吐了两条 `SyntaxWarning`；而验收页取的是 **stdout + stderr 拼起来**的最后一行 → 取到了告警里的源码行。

两处都修了：① 转义写成 `\\`（输出不变，不再告警）；② 验收页**成功时只看 stdout**
（结论行本来就是它打的），失败时才两边都看。

---

## 3. 我**没有**做的（以及为什么）

| 没做 | 为什么 | 现在是什么状态 |
| --- | --- | --- |
| 报告 §7 点名的那三个类（`OrderMoneyCalculator` / `DriverPayCalculator` / `SettlementService`） | 见 §4.1：**数据表 + 契约页**比空壳类更机器可查，而且不用把已有的实函数包装一层 | 用 `money_contract.REEXPORTS` 达成同一目标 |
| §9 第二层剩下的 **36 处**体内角色门槛 | 大部分是**条件门槛**（依赖请求内容 / 依赖那条记录），签名级表达不了；剩下的要一个域一个域来 | 有棘轮判据守着（只许降），台账里逐条记着 |
| **锁死 `backend/requirements.txt` 的版本** | 锁死才能让"本机绿"真的等价于"CI 绿"，但那是替项目决定"停在哪个版本"，要连生产一起考虑 | 现状是开区间；这是**要你拍板**的事 |
| **部署到生产** | 动生产必须你先点头 | 一行没动 |
| `notifications` 那三个端点的权限收敛 | 「要么是你自己的、要么你是派单员」+ **404**，依赖具体那条记录 | 留在体内，棘轮台账上记着 |
| 生产机上的 root 免密、`JWT_SECRET_KEY` 默认串 | 都是要你拍板的运维改动（且轮换 JWT 会让所有人重新登录） | 未动 |

---

## 4. 为什么这么改（几条真实的设计判断）

### 4.1 §7 我没建那三个类：**能机器检查的形状 > 好看的类名**

报告想要的是"消费方依赖接口"。建三个 `Calculator` 类当然也算，但它有代价：
① 已有的钱函数是**模块级函数**（`order_pay(...)`），包成类要么写空壳转发、要么大改调用点；
② 空壳类**检查起来更弱** —— "类存在"是很容易被满足的判据（本项目栽过 12 次"判据被别处满足"）；
③ 而 `REEXPORTS` 是一张**数据表**：每个符号→模块的对应关系是可解析的，检查能断言
"每个钱数只有一处实现、且消费方真的从契约页拿"。
所以选了数据表 + 惰性转出。**这个偏差写进了提交说明**，没有偷偷换掉。

### 4.2 §9 例外要**住在表里**，不要住在函数体里

`role_has_permission` 里那句 `if key == UserRole.DISPATCHER.value: return True` 的问题不是"写错了"，
而是**它不可审计**：没有理由、没有删除条件、也没有人能列出"一共有几条例外"。
搬进 `BYPASS_ROLES` 之后，它变成一行**带理由 + 带"什么时候删掉这一条"**的声明，
而且检查能做**化石检测**（表里写的角色必须还存在）。

### 4.3 §14 为什么先改"没跑成也要红"，再修 bug

因为顺序反过来会白干：只要"没跑"还能算"通过"，你**永远不知道下一个 bug 存不存在**。
第 57 轮之前，那个作业连着几轮都是 success —— 而它一次都没跑过。
把那一行 `exit 0` 改成 `exit 1` 之后，六个 bug 在六轮里自己排队走了出来。
这条经验可以抄：**先让"没有检查"变成红，再谈修什么。**

### 4.4 判据要钉**行为形状**，不要钉"文字"

这一轮新增/改写的判据里，凡是钉文字的都被反向验证抓过：
- 「有没有调用端到端脚本」原来只要正文**提到**那个路径就满足（被 `::warning` 的提示语满足）→ 改钉调用形状；
- 「adb install 在不在」不够 → 改钉**先后顺序**（顺序反了才是那个 bug 的形状）；
- 「有没有 adb install / --check-env」不够 → 同理钉顺序。

### 4.5 生成物要**能自己证明自己**

验收页那一列的承诺是"命令自己打印的结论行"。这一轮发现它会混进 stderr —— 那它就**违背了自己的承诺**。
修它不是为了好看：一个会骗人的验收页，比没有验收页更糟（会让人相信一个不存在的绿）。

---

## 5. 这次新增/改写的判据与反向验证（全清单）

| 判据 | 守什么 | 反向验证 |
| --- | --- | --- |
| `_tools/qa/_check_permission_model.py`（8 组） | §9 三维模型 + 例外必须住表里 | `_reverse_verify_permission_model.py` **8/8** |
| `_tools/qa/_check_inline_role_gates.py`（5 组） | §9 第二层棘轮（只降不升） | `_reverse_verify_inline_role_gates.py` **10/10**（含 2 个防误报） |
| `_tools/qa/_check_ci_workflows.py`（本会话内判据 **38 → 45** 条；下限 `MIN_RULES` **17 → 44**） | CI 真的接管了检查体系 | `_reverse_verify_ci_workflows.py` **21/21** |
| `_tools/ai/_check_ai_read_limits.py` / `_check_notify_guardrails.py` 等 | 在 CI 里不再因缺依赖退化成"扫了 0 个端点" | 各自的反向验证 |
| `_tools/qa/_check_ledger_cash.py`（判据随授权一起**从体内搬到签名**） | 收支三分项的守门 | `_reverse_verify_ledger_cash.py` **17/17** |

---

## 6. 怎么自己证明它还在（复现命令）

```bash
# 一遍跑完所有静态检查（会自己数有多少个）
python _tools/qa/_check_all.py                 # 期望：全部通过（本轮为 103/103）

# 逐章验收（每条都打印"命令自己的结论行"）
python _tools/qa/_gen_acceptance.py --full --out docs/RECTIFICATION_ACCEPTANCE.md

# 单独看这几条
python _tools/qa/_check_money_contract.py      # §7 钱
python _tools/qa/_check_permission_points.py   # §9 权限点都有交代
python _tools/qa/_check_inline_role_gates.py   # §9 第二层棘轮（当前 36 处 / 10 个文件）
python _tools/qa/_check_ci_workflows.py        # §14 CI 接管（45 条）
cd backend && python -m app.migrations status  # §16 迁移版本（当前 5）

# 后端用例
cd backend && python -m pytest -q              # 期望 1015 passed
```

CI 上（推 `new` 分支即触发）：`Gate` 六个作业 + `Tests (Parallel)` 全绿；
`常闸 · 安卓端到端` 会打印上面那段"四段全通"。

---

## 7. 我自己的两次失误（如实记）

1. **`abe04cd` 是在检查红着的时候提交的**。红的是我自己的一次性脚本 `_agent/ci_watch2.ps1`（有中文却没 BOM）——
   提交内容不含它（`_agent/` 不入库），但"全绿才提交"这条纪律我没守住。已删文件、复跑 103/103。
2. **一次误诊**：我写了个脚本扫全仓"非法字符串转义"，报了 9 个文件 —— 复核发现那 9 个只是 **BOM**，
   Python 按字节读完全正常，**是我的扫描方法错了**（用 `str` 而不是 `bytes` 去 `compile`）。真实非法转义 = 0。

两件都写在这份报告和提交历史里，不留暗账。

---

## 8. 接手的人先看这几条

1. **端到端红了先分清是谁的问题**：第 61 轮那次红是 `actions/setup-java` 报 Maven 仓库不可达（runner 的），
   用 API 重跑失败 job 就好 —— ⛔ 别因为一次红就改代码。
2. **"job 的 success"不等于"通过"**：这个作业现在四种结局分得很开（跑通=绿 / 跑挂=红 / `SKIP:`=黄 / 没跑=红），
   但**任何**作业都值得翻一眼日志再下结论。
3. **体内角色门槛只许降**：新增端点请用签名级 `Depends`（`DispatcherUser` 或 `require_permission(...)`）。
   真要留在体内，就往 `_check_inline_role_gates.py` 的 `HISTORY` 追加一条并写明理由。
4. **改了后端鉴权要重跑两样产物**：端点索引与 AI 读目录
   （`cd backend && python -m scripts.gen_endpoint_index --out ../docs/PROJECT_MAP/08A_ENDPOINT_INDEX.md`、
   `python _tools/ai/_gen_ai_read_catalog.py`），否则 `_check_all.py` 会报"产物已过期"。
5. **`docs/RECTIFICATION_PLAN.md`** 是逐轮叙事（第 56~61 轮都在里面），出问题时从那里往回翻最快。
