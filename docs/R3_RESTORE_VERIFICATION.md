# R3 备份隔离恢复验证（C 段前置 · 2026-09-26）

> **这份回答一个具体问题**：**这份生产备份恢复出来之后，得到的是一个真正可查询、结构完整、业务数据仍然成立的数据库吗？**
> 在它之前我们只证过「备份存在 + sha256 正确」—— 那**不等于**恢复得出来、更不等于恢复出来的库能用。
> ⛔ 范围**只做数据库**（uploads 是另一条独立证据，不揉进来）。

---

## 一、验的是**哪一份**备份（⛔ 不是随便挑一份）

要验的是「**今天真会拿来恢复的那一份**」：迁移之后的、当前状态的备份。
⚠️ A1 那份（`pre_release/20260926T133009Z`）是**迁移之前**的快照（44 表、**没有** `schema_versions`）——
拿它验会得到一个「结构本来就不对」的假结论，所以**重新取了一份**：

```text
python _tools/backup/_pre_release.py --note "R3 备份隔离恢复验证（C 段前置，B 之后：48 表 / schema_versions 8）"
=== 备份完成：/opt/sorders-backup/pre_release/20260926T145643Z ===
db.sql.gz：531,250 字节 ／ uploads.tar.gz：105,962,426 字节 / 2115 个文件  ｜ sha256 校验通过
清单：_tools/backup/manifests/20260926T145653Z-pre_release.json
   库行数：{"orders": 2403, "ledgers": 4648, "users": 60, "products": 37, "tables": 48}
```

⚠️ **2403 不是 2402**：A 段 A6 的验收测试单（`SO202609264191401979`，已撤销）在库里 —— 它**本来就该在**这份备份里。
⛔ 这不是「数据多了」，是「这一份备份比 A1 那份新」。

## 二、怎么验的：项目自己的四阶段演练（⛔ 不是新写一个脚本）

```text
python _tools/backup/_drill_local.py --backup /opt/sorders-backup/pre_release/20260926T145643Z --keep
```

`_drill.sh` 的四阶段（口径写在 `_tools/backup/README.md` §演练）：

| 阶段 | 做什么 | 本次结果 |
|---|---|---|
| ① 恢复 | 恢复到 `sorders_drill_<UTC 戳>`，与 manifest 对账 | ✅ 表数/行数一致 |
| ② 库内不变式 | 状态枚举 / 金额非负 / 软删一致性 / 时间基准（判据取自 `app.models.enums`，不手写）| ✅ 逐条 **违规 0 行**（`INVARIANTS=OK`）|
| ③ 启动 | 隔离端口 8011 + 隔离 Redis 6390 + 隔离工作目录 + **自己的 JWT 密钥**，真起 uvicorn | ✅ `/health` 200、`openapi` **165 条路径**全导入、**`schema_versions` 1..8 全在** |
| ④ 接口 | 用真 token 打订单 / 商品 / 账本 / 用户 | ✅ 四条全 200 |

```text
DRILL=ok（不变式通过 + /health 200 + 只读端点 ok）
```

⭐ 三样隔离各有具体后果（README 里写了）：端口撞生产会把生产顶掉；演练连生产 Redis 会往真实客户端推事件；
工作目录用相对路径 ⇒ 在生产目录里跑演练会去压缩**生产的图片**；JWT 密钥不隔离则签出来的令牌对生产同样有效。

## 三、按用户列的不变量逐条对（演练库用 `--keep` 留着）

```text
(1) 结构：schema_versions → 8 行，min=1 max=8     ／ information_schema 表数 → 48
(2) 行数：orders=2403  ledgers=4648  users=60  products=37      （与 manifest 逐项相同）
(3) 关键查询 1（读一张订单）：20846 ｜ SO202609264191401979 ｜ CANCELLED ｜ 0.01 ｜ 2026-09-26 13:39:42
(4) 关键查询 2（账本 join 订单）：5034 ORDER 2160.0000 SO202609222864904837 DELIVERED
                                   5033 ORDER 28.8000 SO202609219132886573 DELIVERED
(5) 关键查询 3（身份）：SHIPPER 34 ／ DRIVER 24 ／ DISPATCHER 2      （合计 60 = users）
(6) 关键查询 4（跨表：订单 + 审计行数）：SO202609264191401979 CANCELLED 4 ／ … 5 ／ 3 ／ 2 ／ 4
(7) 关键查询 5（新结构真的在）：outbox=13 行 ｜ 带 request_id 4 行 ｜ 带 command_id 3 行 ｜ ai_call_daily=0
```

与用户给的不变量对照：**schema_versions 1..8 ✅ ｜ 表 48 ✅ ｜ orders 2403（他写 2402，差的是 A6 那张已撤销的测试单，已说明）｜ ledgers 4648 ✅ ｜ users 60 ✅ ｜ products 37 ✅**。

## 四、清理

```text
mysql -e "drop database sorders_drill_20260926T145701Z"   → drill_db_dropped
rm -rf /opt/sorders-backup/drill-run                      → drill_dir_removed
databases left: information_schema mysql performance_schema sorders sys
```

⛔ 只删演练库与演练目录；**`sorders`（生产库）与所有备份一份没动**。

## 五、⛔ 这份证据证不了什么

- ⛔ **不证 uploads**：这次只验数据库。上传文件是同一份备份里的另一个产物（105,962,426 B / 2115 文件），
  它**能不能恢复**是**另一条独立证据** —— 「DB 恢复 ≠ uploads 恢复」，不揉成一个结论；
- ⛔ **不证 RTO**：没有量「从决定恢复到服务可用」要多久（演练是分批跑的，中间的等待时间不算生产口径）；
- ⛔ **不证演练（C 段）**：这是 C 的**前置**，不是 C 本身 —— 破坏性演练（停服务 / 断 Redis / 塞磁盘）还没开始；
- ⛔ **不证备份保留策略**：库里现在 14 份备份、磁盘 30%，但「保留多久、什么时候能删旧的」没验。