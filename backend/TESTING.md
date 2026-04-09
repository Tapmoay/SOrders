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

### Worker 隔离机制

每个 worker 使用独立的 SQLite 数据库文件：
- `tests/.test_dbs/sorders_test_gw0.db` (worker 0)
- `tests/.test_dbs/sorders_test_gw1.db` (worker 1)
- 依此类推

这确保测试之间完全隔离，可以安全并行运行。

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

```bash
# 清理测试数据库
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
