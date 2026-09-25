# 依赖可复现性：证据与待拍板（R3-07d）

> 这份文档存在的理由：指南 §二十二 的退出条件是「依赖可复现性决策（开区间 vs pin，三处版本是否一致）」。
> 它**要用户拍板**，所以本轮只能把**事实**摆齐、把选项和代价写清 —— ⛔ 不自己决定。
> 生成日期：2026-09-26。所有数字都是**实测**（命令写在每一节里，可复现）。

## 一、事实：三处版本，摆在一起看

### 1) 声明（仓库里的那份）

```
backend/requirements.txt        15 条运行依赖 + 1 条说明   ← 全部开区间（>=x,<y）
backend/requirements-dev.txt     9 条开发/测试依赖          ← 全部开区间
backend/requirements-all.txt    只是把上面两份拼起来（-r ×2）
```

复现：`type backend\requirements.txt` / `type backend\requirements-dev.txt`

⛔ **没有 lock 文件**（`requirements*.txt` 之外没有任何 pin 清单）。

### 2) 本机（跑出 `1018 passed` 的那个环境）

判据：`python _tools/qa/_check_dep_declaration.py`（R3-07d 新加的，进 `_check_all.py` 必跑组）

```
依赖声明对账：5 通过 / 0 失败（声明 24 条，例外 1 条）
  ⚠️  已登记的例外：cryptography cryptography>=42,<44 —— …
```

**24 条声明里 23 条在本机成立，1 条不成立**：

| 包 | 声明 | 本机实际 | 差多少 |
|---|---|---|---|
| `cryptography` | `>=42,<44` | **48.0.0** | 高 **5 个大版本**，压根不在区间里 |

这条上限的来历：`git log -S 'cryptography' -- backend/requirements.txt` →
**只有 `f20b93a`「chore: initial commit, release v0.01」（2026-04-09）一次提交**，
仓库里**找不到任何**说明它为什么卡在 44（`passlib`/`bcrypt` 那条是有注释的，`cryptography` 这条没有）。

后果不是「少装一个包」，而是三件事同时成立：
① 读这份文件的人以为项目跑在 43 上；② 新机器按这份文件装 → **把 48 降到 43**；
③ 生产上到底是哪个版本，**没有任何地方说得清**。

### 3) CI（`.github/workflows/gate.yml`）

```yaml
pip install -r requirements-all.txt        # 4 个 job 都是这一句
cache-dependency-path: backend/requirements*.txt
```

所以 CI 是**运行时解析开区间**：文件不变则命中缓存（同一次装的结果），
但**清一次缓存或换一台 runner，拿到的就可能是一组新版本** —— 而 CI 绿了不代表版本固定。

### 4) 生产（`/opt/SOrders/backend/.venv`，systemd `sorders-api.service`）

⚠️ **还没核**：要上机器跑 `pip freeze`（属 R3-05「现场验证」，需要用户批准）。
在核到之前，这份文档里关于生产的那一格**空着**，不填猜测值。

## 二、已经机器化的那一半（不管选哪个选项都成立）

`python _tools/qa/_check_dep_declaration.py`（新增，已进必跑组）：

1. 三份 requirements 解析得出来，且声明条数 ≥ 20（解析器坏了先喊）；
2. ⭐ 每条声明都要在**本机实际安装的版本**上成立（版本号取自 `importlib.metadata`，不读人写的表）；
3. ⭐ 不成立的必须登记在 `EXCEPTIONS` 里，每条写清「为什么」+「什么时候删掉这一条」；
4. 棘轮 `EXCEPTION_RATCHET = 1`（**只减不增**）+ 防化石（键必须还是当前真出现的违反）。

反验证：`python _tools/qa/_reverse_verify_dep_declaration.py`（6/6：声明被改成装不到 / 例外没写退出条件 /
例外表变化石 / 棘轮被越过 / 负面对照（把声明改成本机满足的区间必须仍然全绿）/ 还原后逐字节一致）。

⛔ 它证不了生产上是哪个版本 —— 见上面第 4 格。

## 三、三个选项（代价写在每一条里）

| | 做法 | 好处 | 代价 |
|---|---|---|---|
| **A. 保持开区间** | 只保留上面那条判据 + 把不成立的声明改对 | 改动最小；不新增文件 | 每次装依赖拿到的可能是一组新版本；出问题只能等 CI/生产发现 |
| **B. 提交 lock（全量 pin）** | `pip freeze` 出 `requirements.lock`，CI 与生产**都按 lock 装** | 可复现性最高（同一份 lock ＝ 同一棵依赖树） | 升级要显式改 lock；**本机与生产都要按 lock 重装一次**，否则 lock 只是第三份真相 |
| **C. 只 pin 直接依赖** | 把 24 条直接依赖写成 `==`，传递依赖仍由 pip 解析 | 折中；升级看得见 | 仍然拿不到「完全相同的依赖树」（传递依赖会飘） |

## 四、我的建议（一句话）

**先做 B 的前半步，再做 A 的收尾。**
理由：现在三处（声明 / 本机 / 生产）**没有任何一处是权威**，先建 lock 等于凭空选一个基准；
正确的基准是**生产上实际装的那一份** —— 所以先上机器 `pip freeze`（R3-05），拿回来当 lock 的底稿，
CI 改成按 lock 装、本机按 lock 重装一次。在那之前，`cryptography` 这条按 A 收尾（见下）。

## 五、⛔ 我没有自己决定的三件事（等你拍板）

1. **`cryptography` 往哪边对齐**：把声明改成 `>=42,<49`（承认本机的 48），
   还是把本机/CI 装回 `43.x`（承认声明）？
   —— 两边都动不了「生产是哪一版」这个空白；如果你知道生产是按 requirements 装的，选后者更保守。
2. **要不要引入 lock 文件**（B），还是维持开区间（A/C）。
3. **允不允许我上生产跑只读的 `pip freeze`**（只读、不改任何东西）—— 这是把第 4 格填上的唯一办法。

## 六、拍板后要做的动作（照做即可，不用再想）

- 选「改声明」→ 改 `backend/requirements.txt` 那一行 → 删掉 `_check_dep_declaration.py` 的 `EXCEPTIONS` 那一条
  → 把 `EXCEPTION_RATCHET` **降回 0**（棘轮只减不增）→ 跑 `python _tools/qa/_check_all.py`；
- 选「降环境」→ `pip install 'cryptography>=42,<44'` → 跑 `cd backend; python -m pytest -q`（1018 个用例）
  → 同样删例外、降棘轮到 0；
- 选 lock → 先 `pip freeze > backend/requirements.lock`（**用生产的那一份**），CI 改成 `pip install -r requirements.lock`，
  本机按 lock 重装一次 → 在 `_check_dep_declaration.py` 里加一条「lock 与声明不许打架」的判据。
