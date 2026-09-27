# 测试指南

## 快速开始

### 安装依赖

```bash
cd backend
pip install -r requirements-all.txt
```

### 运行所有测试（自动并行）

```bash
# Windows
.\run_tests.ps1

# Linux/macOS
chmod +x run_tests.sh
./run_tests.sh
```

### 运行特定测试

```bash
# 快速测试（< 200ms）
pytest -n auto -m "fast"

# 冒烟测试（核心功能）
pytest -n auto -m "smoke"

# 按角色
pytest -n auto -m "shipper"
pytest -n auto -m "driver"
pytest -n auto -m "dispatcher"

# 按模块
pytest -n auto -m "orders"
pytest -n auto -m "ledger"
pytest -n auto -m "batch"

# 集成测试
pytest -n auto -m "integration"

# 单元测试
pytest -n auto -m "unit"
```

## 并行测试配置

### 自动检测 CPU 核心数

```bash
pytest -n auto
```

### 指定 worker 数量

```bash
pytest -n 4
```

### 进程隔离机制

每个 **进程** 使用独立的 SQLite 数据库文件：

- `tests/.test_dbs/sorders_test_gw0_<pid>.db`（xdist worker 0）
- `tests/.test_dbs/sorders_test_gw1_<pid>.db`（xdist worker 1）
- `tests/.test_dbs/sorders_test_master_<pid>.db`（**没开 xdist**）
- 依此类推

⚠️ **PID 是 R4-47 加的**（原来只有 worker id）。原因：
`PYTEST_XDIST_WORKER` 在没有 xdist 时**恒为 `master`**，于是两个并发的 pytest 会话
会算出**同一个文件**、双双 `create_all()` 互相踩。实测「同一份代码、同一条命令、
只是并发跑」：

    A → 1099 passed (142s)
    B → 1099 errors (317s)

这类红看起来像回归，其实**被测代码一个字都没改** —— 所以它值得一个正式修复，
而不只是"记得别并发跑"。

⛔ 退出时**只删自己那一份**（原来是 `rmtree` 整个目录，会把**别的 worker 的库**一起删掉）。

**判据**：`python _tools/qa/_probe_test_db_isolation.py`
—— 让每个子进程**真的连上自己算出来的那个库、写一行、再读回来**，判
「每个进程只看得见自己写的那一行」。⛔ **不是比路径字符串**：字符串不同而真实连接
仍指向同一份文件的写法多得是。`--force-shared` 是**阴性对照**，必须在同一份判据下判红。

### ⚠️ 一条已知遗留：**全量跑会在 `.test_dbs` 留一份库**（R4-47 如实记）

收尾时删自己那一份——**短跑（子集）能删掉，全量跑删不掉**：某个用例把句柄一直占到
进程退出，实测 `dispose` 两个 engine + `gc.collect()` + 重试 4 轮仍然 `PermissionError`。

- ⛔ **这不影响正确性**：文件名带 PID ⇒ 不会与任何别的进程撞（那才是 R4-47 修的缺陷）；
- ⛔ 也不影响标准入口：`run_tests.ps1` / `run_tests.sh` **开局就会清空** `.test_dbs`
  （所以用它们跑不会累积）；只有像 `pytest -q` 这样手敲才会一次多一份；
- ⛔ 收尾删不掉时**会打一行 `[conftest]` 说明**，⛔ 不静默吞（吞掉的后果实测过：
  「一直涨、而没有任何人知道」）。
- **什么时候要修**：如果哪天有人需要长期跑全量而磁盘要紧 ——
  方向是**开局按 PID/mtime 清掉已经死掉的进程留下的那些**（而不是继续在收尾较劲）。

## 测试标记说明

| 标记 | 说明 | 示例 |
|------|------|------|
| `auth` | 认证与授权测试 | 登录、权限验证 |
| `shipper` | 货主端功能测试 | 下单、撤销、账本 |
| `driver` | 司机端功能测试 | 接单、完成订单 |
| `dispatcher` | 派单员端测试 | 派单、撤回、编辑 |
| `orders` | 订单流程测试 | 全流程、状态机 |
| `ledger` | 账本相关测试 | 同步、编辑、导出 |
| `batch` | 批量操作测试 | 批量派单、日志 |
| `socket` | WebSocket 测试 | 实时推送 |
| `fast` | 快速测试（<200ms） | 简单断言 |
| `slow` | 慢速测试（>2s） | 复杂流程 |
| `unit` | 单元测试 | 无外部依赖 |
| `integration` | 集成测试 | 多模块交互 |
| `smoke` | 冒烟测试 | 核心功能 |
| `regression` | 回归测试 | 缺陷修复验证 |

## 覆盖率报告

```bash
# 生成覆盖率报告
pytest -n auto --cov=app --cov-report=term-missing

# HTML 报告
pytest -n auto --cov=app --cov-report=html

# 查看报告
# Linux/macOS
open htmlcov/index.html
# Windows
start htmlcov/index.html
```

## HTML 测试报告

```bash
pytest -n auto --html=report.html --self-contained-html
```

## CI/CD

GitHub Actions 配置见 `.github/workflows/test-parallel.yml`。

### 工作流说明

1. **test-fast**: 快速测试（smoke + unit）并行执行
2. **test-integration**: 集成测试并行执行
3. **test-slow**: 慢速测试顺序执行（避免资源争用）
4. **test-full**: 完整测试套件 + 覆盖率
5. **test-role-summary**: 按角色分组测试摘要

## 故障排除

### 问题：测试数据库锁定

⛔ **先确认没有第二个 pytest 会话在跑**（`Get-Process python`）。并发两个会话本来是能踩到
同一份库的 —— 那条缺陷已在 R4-47 修掉（路径带 PID，见上面的「进程隔离机制」）。
**如果你现在还能复现，别再手动清库**：跑 `python _tools/qa/_probe_test_db_isolation.py`
并把输出附上，那说明隔离又坏了。

```bash
# 清理残留的测试数据库（⚠️ 只有在确认没有 pytest 在跑的时候才做）
rm -rf tests/.test_dbs

# 重新运行
pytest -n auto
```

### 问题：Worker 数量过多

```bash
# 减少 worker 数量
pytest -n 2
```

### 问题：内存不足

```bash
# 使用文件数据库而非内存数据库
# conftest.py 会自动处理
pytest -n 2
```

## 性能基准

| 配置 | 预估时间 | 说明 |
|------|----------|------|
| 单线程 | ~30s | 基线 |
| `-n auto` | ~8s | 4 核机器 |
| `-n 4` | ~8s | 4 workers |

## 相关文档

- [pytest-xdist 文档](https://pytest-xdist.readthedocs.io/)
- [pytest 标记文档](https://docs.pytest.org/en/stable/mark.html)
- [coverage.py 文档](https://coverage.readthedocs.io/)
