# 账号规定（SOrders）

> **这一页是什么**：账号（登录账号）相关的**规定**——不是"默认参数"，是用户拍板、改之前要先问的硬规矩。
> 一条规定 = 一句原文 + 它在代码里的**唯一落点** + 机器判据。
>
> **谁该读它**：① 要改建号 / 改密码 / 账号表单的人；② 被用户问"新建的账号密码是多少"的 AI 会话；
> ③ 写判据的人（要知道哪些字符串是**锚点**，别顺手改）。

---

## 一、初始密码默认是 123321（用户 2026-10-11 定的，**规定死的**）

**用户原话（逐字）**：

> 「我们的**所有账号初始密码默认是 123321**，这是**规定死的**。**AI 也要知道** ——
> 比如说我叫它创建一个账号，它**直接帮我创建好、不要问我密码是什么**；
> 当然也可以，它也可以问我"初始密码要按默认的走吗"。这个有个要改一下，把它改一下。」

**规定本身（三句话）**：

1. **所有账号**（货主 / 司机 / 派单员 / 批发商货主，任何角色）的**初始密码**默认都是 `123321`。
2. 建号时**没给密码就用它** —— 所以问"密码设成什么"是**多余的一步**（AI 直接建，不要追问）。
3. 用户**明确给了别的密码**就以用户为准（这条是规定的另一半，不是例外）。

**唯一落点**（每一侧只有一处，⛔ 别在第二处再写一遍 `123321`）：

| 侧 | 唯一落点 | 说明 |
| --- | --- | --- |
| 后端常量 | `backend/app/core/security.py` → `DEFAULT_INITIAL_PASSWORD` | 值本身只在这里定义 |
| 后端默认 | `backend/app/schemas/user.py` → `UserCreate.password = Field(DEFAULT_INITIAL_PASSWORD, min_length=6, max_length=128)` | **唯一一处"没给就用它"**；`POST /users` 端点里不再写默认值 |
| AI 常量（App） | `android/app/src/main/java/com/tapmoay/sorders/core/AccountRules.kt` → `AccountRules.DEFAULT_INITIAL_PASSWORD` | 与后端那份**由判据对账**（两侧字符串必须一字不差） |
| AI 参数与卡片 | `ai/AiWriteMasterData.kt` 的 `users.create`：密码参数 `required = false`；卡片明细里 `AccountRules.DEFAULT_PASSWORD_NOTE` | "不填用默认"这件事必须**写在给模型看的说明里**，也**写在给用户看的卡片上** |
| AI 提示词 | `ai/AiAgentLoop.kt` 的 systemPrompt「必须遵守」第 4 条后面那段"例外" | 用户说"建一个账号"时**不要追问密码** |
| App 建号表单 | `ui/dispatcher/AccountManageViewModel.kt` / `UsersManageViewModel.kt` 的 `openCreate()` → `AccountRules.passwordDraft(isEdit = false)`；`AccountManageScreen.kt` 的占位 | 手工建号也预填默认值，**仍然可以改** |

**改密码是另一件事**（⛔ 这条规定**不适用**）：

- `PATCH /users/{id}` 的 `password`、AI 的 `users.set_password`（`AiWriteMasterData.kt` 里那个"新密码"字段）
  **仍然是必填**，仍然必须由用户明确给出 —— 没有"默认的新密码"这种东西。
- 编辑账号时密码框**必须留空**（空串 = 不改密码）；预填默认值会在"只改个手机号"时把密码**静默重置**。
  `AccountRules.passwordDraft(isEdit = true)` 返回空串就是为这条。

**⛔ 不要混淆的两件事**：

| | 是什么 | 在哪 |
| --- | --- | --- |
| **本页这条规定** | 产品规定：新建账号的初始密码 | `core/security.py` / `core/AccountRules.kt` |
| 开发库测试号的口令 | **环境事实**：本机 `13800000001/2/3` 恰好也是 `123321` | `docs/PROJECT_MAP/05_TESTING.md` |

两件事**互不引用**：开发库口令可以随环境变（`SORDERS_DEV_PASSWORD`），而这条规定不会跟着变。

**机器判据**：

```
python _tools/qa/_check_default_password.py              # 判据（含跨语言对账）
python _tools/qa/_reverse_verify_default_password.py     # 反向验证：注入 6 次，每次都必须报红
```

**判据钉住的锚点**（⛔ 顺手改这些字符串会让判据红，改之前先看这一节）：

- `backend/app/core/security.py`：`DEFAULT_INITIAL_PASSWORD = "123321"`
- `backend/app/schemas/user.py`：`Field(DEFAULT_INITIAL_PASSWORD, min_length=6, max_length=128)`
- `AiWriteMasterData.kt`：`textField("password", "初始密码", …required = false…).copy(secret = true)`、
  `"不要自己编一个"`、`"密码：已设置，不显示"`（另一条红线 `_check_ai_guardrails.py` 也钉着后两条）
- `AiAgentLoop.kt`：`不要追问密码`
- `AccountRules.kt`：`DEFAULT_INITIAL_PASSWORD` / `DEFAULT_PASSWORD_NOTE` / `passwordDraft`

---

## 二、其他账号规定（占位：以后新增的账号规定写在这里）

- （暂无）—— 新增规定时，照第一节的四件套写：**用户原话 / 唯一落点表 / 不适用与别混淆 / 机器判据**。
