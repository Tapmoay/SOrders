# 开发期专用信息索引（**上线前按这张表删/换**）

> ⚠️ **这份文档里没有任何密钥值**，只有"有什么、在哪、上线前怎么处理"。
> 原因：`Tapmoay/SOrders` 是**公开仓库**——2026-09-19 就发生过一次真实泄露
> （生产库口令随 `_test_tools/chk_mysql.py` 进了公开仓库约 20 分钟，见
> `_archive/audit/HANDOVER.md`）。**值一律放仓库外面**（本机 `C:\Users\Optimistic\.sorders\`），
> 红线 `_tools/qa/_check_secrets.py` 盯着仓库这一侧（`sk-` 形状、明文口令、内联 MySQL 口令、
> PEM、公网 IP…），谁写进来 `python _tools/qa/_check_all.py` 立刻红。

## 1. 一句话结论（给"要上线了"那一刻的人）

**要删/要换的只有三类**：① 第三方 API key（AI 助手用的）② 本地测试账号与测试数据 ③ 本机/服务器上的凭据文件。
**生产库口令不是开发期信息**——它属于生产运维，别删（要轮换是另一件事）。

## 2. 总表

| # | 是什么 | 只在开发期用的在哪 | 上线前怎么处理 |
|---|---|---|---|
| 1 | **AI 助手 API Key**（DeepSeek，`sk-…`） | 本机 `C:\Users\Optimistic\.sorders\dev-credentials.md`；运行时存在 **App 自己的加密存储**里（`ai/AiKeyStore`，SharedPreferences + 密文，**不进代码**） | **换掉并作废**：① DeepSeek 控制台删掉这把 key；② App 里换成客户自己的 key（AI 助手 → 设置）；③ 客户手机若用过开发 key，让他在设置里重新填 |
| 2 | **本地测试账号**（`13800000001/2/3`、`13810000032`，口令 `123321`） | 公开仓库里就有：`backend/tests/conftest.py`、`_tools/notify/_assign_order.py`（**本地测试数据**，不是生产账号） | 生产库里确认**不存在**这些号：`SELECT id,phone FROM users WHERE phone LIKE '1380000%';`（有就删）；⚠️ **不要**去改仓库里的测试常量（改了单测就没法跑） |
| 3 | **本机凭据文件** | `C:\Users\Optimistic\.sorders\`（`dev-credentials.md`、`prod-db-credentials.txt`、`rotate_db_password.sh`） | 交付机器前整个目录删掉（它本来就在仓库外，不会随代码走） |
| 4 | **服务器上的凭据文件** | `/root/.sorders-db-credentials.txt`（600）、`/opt/SOrders/.env`（600） | **保留**（生产要跑）；只确认权限是 600、且 `.env` 不在任何备份/公开目录里 |
| 5 | **模拟器与测试工具** | `_tools/`（含 `_archive/` 里的探针、`_tools/fuzz/`、`_tools/ai/_probe_*.py`）；`_archive/` 是 gitignored | 交付时不带走（`_tools/` 是开发/审计工具，跟着仓库走没风险，但别放进交付包） |
| 5b | **容量测试用的大库与副本后端**（2026-09-23 新增） | `_tools/perf/_perf_seed.py` 生成的 `_agent/perf/perf.db`（2 万单 / 23MB，**`_agent/` 与 `*.db` 都在 .gitignore 里**）、以及指向它的第二个后端（`DATABASE_URL=sqlite:///…/perf.db` + `--port 8001`） | 交付时删掉 `_agent/perf/` 即可（就是一份开发库的放大副本，含测试账号与演示数据）。⚠️ 量完**记得把 8001 那个后端停掉**：它比源码旧会让 `_check_backend_fresh.py` 一直报红（见该脚本注释） |
| 6 | **测试数据**（`SOTEST…` 订单、`验证-*` 地点、`probe-*` 共享地点、`测试收货地址`） | 本机 `backend/sorders.db`；生产库**曾经**清过一次（`/root/backup-testdata-20260904.sql`） | 生产库上线前再清一次：订单号 `LIKE 'SOTEST%'`、地点名 `LIKE '验证-%' OR LIKE 'probe-%'`、地址含「测试收货地址」 |
| 7 | **App 里存的会话/登录态** | 每台模拟器/真机的 `shared_prefs/session`、`ai`（加密） | 交付前 `adb shell pm clear com.tapmoay.sorders`，或让用户自己退出登录 |
| 8 | **公开仓库本身的历史** | `Tapmoay/SOrders` 历史里有：生产 IP、SSH 私钥**路径**、`_tools/deploy/` 的发布流程、**已失效**的旧库口令 | 已评估过：旧的库口令**已轮换失效**，不必改写历史；IP/路径属"知情即可"级别。若客户要求私有，把仓库转私有即可（代码本身没有现役凭据） |

## 3. 为什么密钥值不写进这份文档（写给"下次想图省事"的人）

- 仓库是**公开**的：写进来 = 立刻泄露，而且 git 历史**删不掉**（要改写历史）。
- 本项目的红线会红（`_check_secrets.py` 认 `sk-` 形状），等于每次收尾都被拦一次 ——
  **这不是障碍，是提醒**：真需要给同事/未来的 AI 看，就发给对方一个**本机路径**（上面第 2 行那一列）。
- 2026-09-20 起：拿到新的开发期密钥 → 先写 `C:\Users\Optimistic\.sorders\dev-credentials.md`，
  再在这份索引里"要不要提一句类目"（只提类目，不提值）。

## 4. 验收这条索引还活着

```powershell
python _tools/qa/_check_secrets.py            # 仓库里不许出现密钥形状
python _tools/qa/_check_all.py                # 全部静态检查（含上面那条）
```
