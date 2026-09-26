# R4 扩展区：清单 / 注册表 / 配置 / 装配

> **R4-03 的产物**。依据 R4 指南 §15（Extension Registry 与 Manifest）、§16（⛔ 不要马上做动态安装/热插拔）、
> §26（配置也要模块化）、§27（API 不要"插一个功能改主路由总表"）、§29（建立模块依赖图）。
> **代码**：[backend/app/core/extension_registry.py](../backend/app/core/extension_registry.py)（核心侧）、
> [backend/app/extensions/](../backend/app/extensions/)（扩展区）。

---

## 0. 一句话

指南 §15 把「插块」的意思限定得很死：

> 注意，**不是动态插件市场**。而是：**系统启动时，知道当前有哪些合法扩展。**

所以这一页描述的是**可安装的模块化单体**（deploy-time modularity）：扩展是**仓库里的代码**，
随发布一起上去；进程启动时扫一遍包目录，把清单登记进 [注册表](#3-注册表extension_registry)。

## 1. 清单（Manifest）的字段

一个扩展 = `app/extensions/<id>/` 一个目录，里面必须有 `manifest.py`：

```python
MANIFEST = ExtensionManifest(
    id="unit_conversion",
    version=1,
    kind="pure-function",
    provides=("unit.convert",),
    requires=("quantity.core",),
    consumes=(),
    emits=(),
    config=("UNIT_SYSTEM",),
    compatibility="UnitConversionContract v1",
    owns_tables=(),
    routes="",
    capability="",
    why="把用户自己填的换算率与量纲感知的换算统一成一条纯函数契约",
)
```

| 字段 | 类型 | 意思 | 缺了会怎样 |
| --- | --- | --- | --- |
| `id` | str | 扩展的唯一短名，**必须与目录名一致** | 目录名与清单对不上时，找不到它该信谁 |
| `version` | int | 扩展自己的版本（正整数） | 升级时说不清"现在跑的是哪一版" |
| `kind` | str | 四类之一，见 §2 | 注册表直接拒绝 |
| `requires` | tuple | 它依赖的**核心契约**（如 `quantity.core`、`money.core`） | 依赖变成隐形的 |
| `provides` | tuple | 它提供的**能力名**（如 `unit.convert`、`pricing.calculate`） | 谁提供这个能力就无人可查 |
| `consumes` | tuple | 它消费的**事件类型**（本项目目前一律为空，见 §7） | 隐性订阅没人看得见 |
| `emits` | tuple | 它会产生的**事件类型** | 同上 |
| `config` | tuple | 它需要的配置键（值一律走 `EXT_` 前缀，见 §4） | 配置散落在 `os.environ` 里 |
| `compatibility` | str | 它按**哪个契约的哪个版本**写的（如 `PricingContract v1`） | 契约升级时不知道谁会坏 |
| `owns_tables` | tuple | 它**自己的运营数据**表（指南 §25 的 B 类） | 一张表两个主人没人发现 |
| `routes` | str | 它要挂的路由模块（相对本包，如 `unit_conversion.api`）；空 = 不挂 | 路由要改主路由总表 |
| `capability` | str | 那条路由需要的**能力点**（`core.rbac.Permission` 的成员名） | 见 §5：鉴权必须归核心 |

另外两个非契约字段（给人看的）：`why`（≥20 字：写不出为什么存在，就不该存在）与 `enabled`（默认 True）。

## 2. 四类扩展（指南 §8–§11）

| `kind` | 适合什么 | 本项目现状 |
| --- | --- | --- |
| `pure-function` | 单位换算、税率、数学、格式转换、纯规则 | Unit Conversion（R4-04） |
| `policy` | 定价、折扣、运费、税费、佣金、特殊业务规则 | Pricing（R4-05） |
| `provider` | AI、短信、邮件、推送、对象存储、第三方地图 | 只登记在边界图，没有第二个实现 |
| `presentation` | Excel、PDF、CSV、特殊报表 | 同上 |

⛔ 这**不是**"插件类型"，是**契约形状**的分类 —— 指南 §7 明确否掉了「一个万能插件基类」。

## 3. 注册表（extension_registry）

`app/core/extension_registry.py` 提供：

- `ExtensionManifest` —— 上面那张表的 dataclass（**字段清单的唯一一处**，判据从这里读）；
- `ExtensionRegistry` —— `register / get / all / enabled / by_kind / by_provides / owned_tables`；
- `discover()` —— **部署期**扫一遍 `app/extensions/*/manifest.py`；
- `extension_config()` —— 按清单声明的键取配置（见 §4）。

注册表在**登记时就拒绝**四种坏清单：id 不合法、id 重复、`kind` 不在四类里、
`version` 不是正整数、`routes` 与 `capability` 不成对。⛔ 这些错误不允许"先收下以后再发现"。

### ⛔ 为什么没有 add / remove / reload

指南 §16 点名了这个坑：运行期上传 Python 文件并热加载会瞬间产生版本兼容、状态迁移、进程状态、
安全边界、插件来源可信度、回滚、依赖冲突。所以注册表**只在启动时装配一次**，
`discover()` 用的是 `pkgutil` 包扫描 —— 那是部署期行为，不是运行期热加载。
判据 `_check_extension_manifest.py` 第 4 组盯着 `exec` / `eval` / `reload` / 文件监听 / `subprocess`。

## 4. 配置也要模块化（指南 §26）

核心配置与扩展配置**必须分开**，前缀是硬约定：

```text
CORE_DATABASE_URL / CORE_SECRET ...        <- 核心
EXT_<ID>_<KEY> ...                          <- 扩展（如 EXT_UNIT_CONVERSION_UNIT_SYSTEM）
```

扩展**不许直接读环境变量**（`os.environ` / `os.getenv`）—— 读得到 `JWT_SECRET_KEY` / `DATABASE_URL`
就等于拿到了核心机密，而"一个扩展的环境变量污染整个系统"正是指南 §26 要防的事。
取配置的唯一入口是 `extension_config(manifest)`，它只认清单里声明过的键、只认 `EXT_` 前缀，
返回的是**只读**映射。

## 5. 路由与鉴权（指南 §27）

指南把这条画成了一张单向图：

```text
Extension declares capability
        ↓
Core authorization
        ↓
route
```

而不是「Extension 自己写一套权限」。落到本项目：

1. 扩展在清单里写 `routes` + `capability`（能力点是 `core.rbac.Permission` 的成员名）；
2. **核心**在装配时施加 `require_permission(...)` —— 扩展代码里**一行鉴权都没有**；
3. 于是也不可能出现 `extension_permission.py` 那种"另起一套授权世界"（§31 坑 11）。

判据 `_check_extension_dependencies.py` 第 3 组核两件事：扩展代码里没有任何鉴权形状；
声明了路由的扩展，其 `capability` 必须是**真实存在**的权限点。

## 6. 模块依赖图（指南 §29）

```text
python _tools/qa/_check_extension_dependencies.py --graph
```

它回答四个问题（指南原文）：**谁依赖谁 / 谁拥有这个表 / 谁提供这个 capability / 谁监听这个 event**。
数据来源是清单本身（`requires` / `provides` / `owns_tables` / `consumes`）加注册表的登记，
⛔ 不是一张手写的图。

## 7. ⛔ 扩展不许做的事（动/静两条线）

**代码线**（判据在 `_check_extension_dependencies.py` / `_check_data_ownership.py`）：

1. ⛔ 不许 import 核心私有内部（`app.services` / `app.api` / `app.models` / `app.database` / `app.deps`）
   —— 能 import 的只有 `app.core.contracts.*` 与 `app.core.extension_registry`；
2. ⛔ 不许改核心拥有的数据（订单 / 账本 / 身份 / 审计 —— 见 [R4_CORE_EXTENSION_MAP.md](R4_CORE_EXTENSION_MAP.md)）；
3. ⛔ 不许写账本（`ledgers` / `cash_flows` / 结算服务）—— 只能算出 `Money`，事实交给核心事务；
4. ⛔ 不许自己写鉴权（见 §5）。

**运行线**：

5. ⛔ 不许动态加载（没有上传、没有文件监听、没有 `exec` / `eval` / `reload`）；
6. ⛔ 不许自己读环境变量（见 §4）；
7. ⛔ 不许把 `consumes` / `emits` 当作**业务流程**用 —— 指南 §28：
   「Event 是事实通知，不是隐藏调用」。本项目 18 个事件**全部**是事实通知，
   核心事实不依赖任何事件消费者（出口在 `_check_core_extension_boundary.py` 第 4 组）。

## 8. 判据

```text
python _tools/qa/_check_extension_manifest.py        # 清单契约三方一致 / 禁止动态加载 / 配置前缀
python _tools/qa/_check_extension_dependencies.py    # 四条防火墙规则 + 依赖图（--graph）
python _tools/qa/_check_data_ownership.py            # 扩展不许碰核心事实表与账本 + 历史快照
python _tools/qa/_reverse_verify_r4_all.py           # 反向破坏用例
```