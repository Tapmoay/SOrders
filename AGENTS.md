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

## 给三台模拟器装包：用**共享工具**，别各写各的（用户 2026-09-21 定的）

```
python _tools/qa/_install_all.py            # 预检 → 构建一次 → 装三台 → 各自登录 → 汇报
python _tools/qa/_install_all.py --precheck # 只跑预检，看现在能不能用
python _tools/qa/_install_all.py --only 5556 --no-build   # 只装我这一台
```

它一次做四件手工最容易出错的事：**只构建一次**（三台装同一个包）、按端口对角色装
（5554 派单员 / 5556 货主 / 5558 司机，**不是按端口排的**）、在登录页就自动登录、
并核对"这台登的是不是它该有的角色"。

⚠️ **前提（用户原话：「假如某个人他正在干活的话，则就不需要调用这个脚本了，就各装各就行了」）**：
脚本**开跑前会预检**，命中任一条就拒绝（`--force` 可强装）：
① 有别人正在跑 Gradle 构建；② **别的 DSH 会话最近 6 分钟还在干活**（看会话日志 mtime，
不是看声明页 —— 声明页「进行中」积压历史条目，拿它当门禁会天天误报）。
⛔ 别人在干活时**各装各的**：别把他正在调的那台刷成你的包 —— 他会以为自己的改动没生效。

⚠️ **但 `--only <端口>` 就是"各装各的"**（2026-09-21 修）：给了 `--only` 时，上面第 ② 条**只提醒不拦**
（都只装自己那一台了，还拦着不让装就自相矛盾）；第 ① 条**仍然拦**（两个 Gradle 撞一起是物理冲突，
跟装哪台无关，实测会把 `build/` 里的 class 写坏、报 `size in bytes: 0`）。

## 加/改功能前：**核心不动，其余插件式扩展**（用户 2026-09-21 定的准则）

> 用户原话：「我们采一个核心的准则就是**核心的逻辑代码是不要乱动、核心是不要变**，
> 然后其他的就是**以插件的形式** —— **能调方法调方法、能继承就继承、能调 API 就调 API**。」

- **核心区**＝动一下就会让钱算错 / 状态走错 / 权限漏掉 / 历史数据变样的那几处（钱、状态机、权限、
  时区、出参口径、线上库结构、AI 写闸门）。清单在 `_tools/qa/_core_files.txt`，每条都写了为什么。
- 新功能**一律走扩展点**，不要改核心：完整清单（AI 动作 / 处理器 / 批量 / 读能力 / 撤回 / 后端端点 /
  通知 / 审计码 / 页面入口 / 共用控件 / 检查）见 **[docs/CORE_AND_EXTENSION.md](docs/CORE_AND_EXTENSION.md)**。
- **确实必须动核心**时：在 `docs/AI_WORK_CLAIM.md` 的「进行中」里写一行
  `核心改动：<路径> —— 为什么必须动核心：<一句话>`，否则 `python _tools/qa/_check_core_freeze.py` 当场报红
  （判据只看未提交的改动；清单被掏空、路径不存在也都会红）。

## ⛔ 改文件只用编辑工具：**别用 PowerShell 往返**（会把中文写坏，2026-09-21 实测）

```powershell
# ⛔ 千万别这么干（本机是 Windows PowerShell 5.1）：
(Get-Content file.kt -Raw) -replace 'a', 'b' | Set-Content file.kt
```

`Get-Content` 对**没有 BOM 的 UTF-8 文件按系统 ANSI(GBK) 解码** → ① 中文全部变乱码；
② **换行会被吃掉**（UTF-8 汉字的第三个字节与后面的 `\n` 被 GBK 当成一对无效双字节吞掉）。
2026-09-21 实测代价：一个 477 行的 `ProfileScreen.kt` 被写成 374 行、**不可逆推**
（丢的是字符的第三个字节，猜不回来），只能按编辑记录整份重写。

- 改源码/文档：用编辑器工具（本仓库的编辑工具按 UTF-8 读写，不会碰编码）。
- 真要批量改：用 Python（`io.open(..., encoding="utf-8", newline="")`）——**`newline=""` 不能省**，
  否则 CRLF 文件的偏移量会对不上（`_hint_inventory.py` 那次踩过）。
- 含中文的 `.ps1` 必须存成 **UTF-8 with BOM**（否则 PS 5.1 按 ANSI 读会直接报语法错）。

## 发布前 / 出事时：备份与恢复（2026-09-24 起 · 整改报告阶段 1）

```
python _tools/backup/_pre_release.py --note "上线 X（改了什么）"   # 发布前**必做**：库 + 上传文件 + 清单
python _tools/backup/_drill_local.py                              # 恢复演练（每周一凌晨也会自动跑一次）
python _tools/backup/_install.py                                  # 把脚本/定时任务（重新）装到生产机
```

- 口径与现场手册：[_tools/backup/README.md](_tools/backup/README.md)；这套东西**自己的**判据：
  `python _tools/backup/_check_backup.py --check`（55 条，已进 `_check_all.py` 必跑组）。
- ⛔ **恢复默认不碰生产库**：`_restore.sh` 不带 `--i-know` 只肯往 `sorders_drill_*` 里恢复。
- ⛔ **发布前先备份**：报告的原话是「不能 deploy 完了才想起来好像以前有个 mysqldump」。
- 生产事实（主机/密钥/路径）只写在 `_tools/ops/_prodssh.py` 一处，其余脚本一律 import。

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
python _tools/qa/_check_all.py          # 全部静态检查（当前 50 个脚本，约一分钟）
python _tools/qa/_check_all.py --deep   # 再加全部反向验证（⚠️ **50 分钟以上**，跑时全场冻住）
python _tools/qa/_check_all.py --list   # 只列清单不跑（看它到底都在查什么）
```

**改红线/改被测代码时，别一上来就跑全量反向验证** —— 用它的子集模式（秒级到分钟级）：

```
python _tools/ai/_reverse_verify_all.py --list        # 列会跑哪些（66 份）
python _tools/ai/_reverse_verify_all.py --changed     # 只跑「注入目标涉及本次改动文件」的
python _tools/ai/_reverse_verify_all.py --only qa     # 只跑某个域（ai / qa / notify / fuzz）
python _tools/ai/_reverse_verify_all.py --for backend/app/services/order_return.py
```

> ⚠️ 上面这些数字会随脚本增删变化（**清单是自己算的**，不手写）；
> 以 `_check_all.py` 第一行打印的"共 N 个检查脚本"为准。

⚠️ **跑 `--deep`（反向验证）的时候不要改源码**：它会先拍快照，跑完把与快照不一致的文件写回去，
并发做的修改会**被一起抹掉**（实测被抹掉过 15 个文件）。而并发的**检查**会自动拒绝出结论
（`_airepo.refuse_if_injecting`：那一刻源码里带着注入的 bug，结论不可信）。

⛔ **别硬杀它**（2026-09-21 实测代价）：被 kill 会留下三样 —— ① 注入没还原的文件（`git status` 能看见，
`git checkout --` 还原）；② **没释放的注入锁**（`%TEMP%\dsh_reverse_verify.lock`）→ 接下来**所有检查
都拒绝出结论**，最长 30 分钟；③ 开跑前的快照 `%TEMP%\dsh_rv_snapshot` —— ⚠️ **不要**直接跑
`_recover_injections.py` 去"还原"它：那会按快照把**开跑之后**的改动一起抹掉（真实状态在 git 里）。
正确做法：**删快照 + 删锁**。

⚠️ 另外：`git checkout -- <file>` **只对已提交的文件安全**。那个文件有未提交改动时，它会把你的改动
**一起抹掉**（2026-09-21 实测：注入实验后用 `git checkout --` 还原，抹掉了一个文件整轮的重构）。
注入实验请先 `Copy-Item` 备份字节、改完拷回去。

⚠️ 还有一类**假阳性**别被它骗到：注入/反向验证脚本会把文件原样写回（内容一字不差，只换了 mtime），
于是 `git status` 可能报 ` M` 而 `git diff` **一行都没有**。判据是哈希：
`git hash-object <file>` 与 `git rev-parse HEAD:<file>` 相同 → 内容没变。修法是 `git add <file>`
刷新索引（不产生任何内容差异），**不是** `git checkout --`（那会在真有改动时抹掉工作）。
同理，看到 ` M` 先跑 `git diff`，别看状态就下结论。

**为什么要有这一条**：这个仓库有过一次"红线红了整整一轮没人知道"——检查本身是对的，但**收尾清单是手写的**，新写的检查不在那张清单里。所以清单现在**自己算**（`_tools/*/_check_*.py` + 任何声明了 `--check` 的脚本），加一个新检查脚本不需要谁记得来登记。

**新增功能时同样适用**（用户 2026-09-19 的原话：「每次增加一个新功能的时候，我们都要给 AI 开一个后路」）：

- 后端新增**写端点** → `_tools/ai/_write_coverage.py --check` 会红，除非**同时**加一个 AI 动作，或在它的 `EXCLUDED` 表里写一条"不做"的理由；
- App 新增**功能模块 / 读能力 / 写能力域** → `_tools/ai/_app_feature_coverage.py --check` 会红（能力没被任何模块认领＝用户从模块看找不到它）；
- 新增**审计动作码**（`OperationAction`）→ `_tools/ai/_check_action_labels.py` 会红，除非 `ui/dispatcher/ReportCenter.kt::actionLabel` 里有中文名（否则审计卡片上直接显示原始码）。
