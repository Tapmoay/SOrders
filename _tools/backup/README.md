# 备份 / 恢复 / 演练（阶段 1：先把"出事了救不回来"消掉）

> 报告原文：*「不要把它当成一张待重画的架构图，而是把它当成一个正在运行的系统进行分阶段改造」*，
> 而第一处要动的就是 **`schema_bootstrap` + 备份恢复 + CI**。这一页是**备份恢复**那一块。

## 这套东西修的是什么

改造前的事实（`docs/BASELINE.md` 里那条风险就是它）：

```text
生产机上只有一堆手敲的 /root/backup-*.sql.gz
  · 没有目录结构（daily / weekly / pre_release 分不清）
  · 没有清单（这份备份对应哪一版代码？不知道）
  · 没有保留期（682MB 的 /root 里躺着一年前的库）
  · 没有校验（"恢复出来对不对"没人验过）
  · 没有演练（脚本 exit 0 就当它能恢复）
```

报告里 R2 的风险描述是：**没有真正脚本化的 backup / rollback，恢复没有实战演练**。

## 一分钟上手（三条命令）

```bash
# ① 装到生产机（脚本 + 定时任务；装完会逐字节比对 sha256）
python _tools/backup/_install.py

# ② 发布前做一份（库 + 上传文件 + 代码版本，清单会拉回本地留档）
python _tools/backup/_pre_release.py --note "上线 0.2.5（订单拆分修复）"

# ③ 演练一次（真的恢复、真的起服务、真的打接口）
python _tools/backup/_drill_local.py
```

## 文件与职责

| 文件 | 在哪跑 | 干什么 |
|---|---|---|
| `_install.py` | 本地 | 把三个 shell 脚本装到 `/opt/sorders-backup/bin/`，装完比对 sha256，挂 `/etc/cron.d/sorders-backup`；给应用账号在 `sorders_drill_%` 上授权并**当场用应用账号建库/删库自检** |
| `_pre_release.py` | 本地 | 发布前一条命令：`git tag`（可选）→ 生产机备份 → 清单拉回 `manifests/` → 打印回滚命令 |
| `_drill_local.py` | 本地 | 遥控生产机跑一次演练，把结论（`DRILL=ok`）带回来 |
| `_backup.sh` | 生产机 | 备份库（+上传文件）→ 当场校验 → 写 `manifest.json` / `SHA256SUMS` → 保留期清理 |
| `_restore.sh` | 生产机 | 恢复到一个**指定库**；默认拒绝碰生产库；恢复前校验产物完整性 |
| `_drill.sh` | 生产机 | 恢复演练四阶段：恢复 → 库内不变式 → 启动隔离实例 → 真 token 打只读端点 |
| `_check_backup.py` | 本地/CI | 这套体系**自己的**静态判据（54 条，进 `_check_all.py` 自动跑） |
| `_tools/ops/_prodssh.py` | 本地 | 生产主机 / 密钥 / 路径的**唯一一处**定义，其余脚本一律 import |

## 备份产物长什么样

```text
/opt/sorders-backup/
├── daily/20260925T023000Z/          # 每天 4 次，只备库（快、便宜）
├── weekly/20260928T031500Z/         # 每周日一次，库 + 上传文件
├── pre_release/20260924T193000Z/    # 每次发布前，库 + 上传文件
│   ├── db.sql.gz                    # mysqldump（--single-transaction，不锁表）
│   ├── uploads.tar.gz               # 上传的图片（**不可再生**，所以必须有）
│   ├── manifest.json                # 时间/发起人/代码 commit/库行数/产物 sha256/表数
│   ├── SHA256SUMS                   # 恢复前 `sha256sum -c` 验的就是它
│   └── .FAILED                      # 只在**没跑完**时出现；带它的目录一律拒绝恢复
└── bin/                             # 上面那三个 shell 脚本（由 _install.py 装）
```

另外 `_install.py` 会给应用账号补一条**边界清晰的授权**：

```sql
GRANT ALL PRIVILEGES ON `sorders\_drill\_%`.* TO 'sorders'@'%' / @'localhost';
```

为什么需要它：应用账号原来只有 `sorders.*` 的权限，第一次真跑演练就撞上 `ERROR 1044 Access denied`。
修法**不是**"演练改用 root"，而是只给这一个命名空间 —— 演练仍然用应用自己的账号，
这本身还是一条更强的验证（应用账号必须真的能在这份恢复出来的库上跑起来）。

保留期：daily 14 份 / weekly 8 份 / pre_release 20 份（`_backup.sh --keep-*` 可调）。
清理只在 `/opt/sorders-backup/` 下做，脚本里有一道显式的路径护栏。

## 真的出事时怎么恢复

```bash
# 0. 先再备一份当前状态 —— 否则覆盖掉的就再也回不来了
bash /opt/sorders-backup/bin/_backup.sh --kind pre_release --note "恢复前的现状"

# 1. 挑一份备份（manifest.json 里能对代码版本）
ls -1t /opt/sorders-backup/pre_release/

# 2. 恢复
bash /opt/sorders-backup/bin/_restore.sh \
     --backup /opt/sorders-backup/pre_release/<戳> \
     --target-db sorders --i-know

# 3. 重启后端并看日志
systemctl restart sorders-api && journalctl -u sorders-api -n 50 --no-pager
```

⛔ `--i-know` 那道门是故意的：没有它，`_restore.sh` **只肯往 `sorders_drill_*` 里恢复**。

## 演练（`_drill.sh`）到底验了什么

报告对演练的要求是"不是脚本 exit 0"，四个阶段逐一对应：

| 阶段 | 做什么 | 通过判据 |
|---|---|---|
| ① 恢复 | `_restore.sh` 恢复到 `sorders_drill_<UTC 戳>` | 表数/行数与 manifest 一致 |
| ② 库内不变式 | 状态枚举 / 金额非负 / 外键孤儿 / 时间基准 | 每条违规行数 = 0（判据取自 `app.models.enums`，不手写） |
| ③ 启动 | 隔离端口 + 隔离 Redis + 隔离工作目录，真起 uvicorn | `/health` 200 且 `openapi.json` 全部路由导入成功 |
| ④ 接口 | 用真实 token 打订单 / 商品 / 账本 / 用户 | 全部 200 |

三样隔离不是洁癖，各有具体后果：

- **端口**：生产 uvicorn 在 8000，演练用 8011 —— 撞端口会把生产顶掉；
- **Redis**：pub/sub 通道是全库共享的（db index 不隔离它），演练连生产 Redis 就可能往真实客户端推事件；
- **工作目录**：`data_retention` 用相对路径 `Path("uploads")`，在生产目录里跑演练会去压缩**生产的图片**。
- **JWT 密钥**：演练自己生成一把，否则签出来的令牌对**生产**同样有效。

## 定时任务（`_install.py` 挂的）

```cron
30 2,8,14,20 * * *   daily 备份（只备库）
15 3 * * 0           weekly 备份（库 + 上传文件）
45 3 * * 1           恢复演练（每周一次 —— 演练也要定时做，否则它就是摆设）
```

日志：`/var/log/sorders-backup.log`、`/var/log/sorders-drill.log`。

## 纪律（写进脚本里，不是写在文档里）

1. **口令不进源码、不进命令行**：生产 `.env` 现读 → `MYSQL_PWD` 环境变量（`ps` 看不见）。
2. **备份失败要留痕**：任何中途失败都在目录里写 `.FAILED`，恢复时一律拒绝它。
3. **备份要当场自证**：`gzip -t` + `sha256sum -c` + 与 manifest 对行数。
4. **生产库有门**：`_restore.sh` 不认 `--i-know` 就只肯写演练库。
5. **这套东西自己也要被检查**：`python _tools/backup/_check_backup.py --check`（54 条判据，
   已经在 `_check_all.py` 的必跑组里 —— 新增检查脚本加个 `--check` 就自动进组）。

