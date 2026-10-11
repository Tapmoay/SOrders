# AI 默认值清单（「能推断就执行」· CHG-0120）

> **这一页是什么**：用户 2026-10-11 的口径 ——
> 「这个 AI 啊**太过繁琐**了 —— 教他执行任务了，他**老是反复确定**，但其实任务其实**也全都已经写好了、基本是已经确认的**。」
> 于是有了这句话：**凡是从下面这张单子（或表格 / 资料 / 既有记录）能推断出来的，AI 直接做，不再追问**；
> 它用到的**假设写在确认卡上**（用户一眼就能看出 AI 替他定了什么、要在哪儿改口）。
>
> **谁该读它**：① 改 AI 提示词 / 改 AI 写动作 / 写确认卡的人；② 被用户说"反复确认"的会话；
> ③ 写判据的人（提示词里那段文字的**正文**在 `android/app/src/main/java/com/tapmoay/sorders/ai/AiRolePrompt.kt` 的 `AiDefaults.RULES`，
> 这一页是**给人读的完整版**，两边同源、由一个判据对账）。
>
> ⛔ **这不是"可以随手改的默认参数"**：改任一条 = 改 AI 的执行口径，**先问用户**。
> ⛔ **确认卡没有被取消**：仍然要用户点「确认」才写进系统（本单不动那套结构，也不动风险分级 `AiWriteRisk`）。

---

## 一、清单：能推断 ⇒ 直接做

| # | 场合 | 默认值（直接照做，并把假设写在卡上） | 出处 |
| --- | --- | --- | --- |
| 1 | 建账号的**初始密码** | **所有账号默认 `123321`**（规定死的，不是"随手挑一个"） | `docs/ACCOUNT_RULES.md` 的唯一落点表 → `backend/app/core/security.py::DEFAULT_INITIAL_PASSWORD`、`android/app/src/main/java/com/tapmoay/sorders/core/AccountRules.kt::DEFAULT_INITIAL_PASSWORD`；提示词侧见 `android/app/src/main/java/com/tapmoay/sorders/ai/AiAgentLoop.kt` 的「例外：建账号时的初始密码」，渲染时**引用常量**（⛔ 不许手抄数字） |
| 2 | 商品的**成本价**填哪一格 | 填**进货成本**（实际进价）。**「返点后成本」是算账时才用的口径**，⛔ 不占成本价那一格 | 字段 `backend/app/models/product.py`（`cost_price`；唯一写入口 `backend/app/services/cost_history.py::record_cost`）。口径来自用户 2026-10-11：「成本价肯定是进货成本，那个返点后的成本价是我们在算账的时候会用到的」 |
| 3 | 商品的**默认单价** | 表格 / 资料里给了**零售价（建议零售价、售价）⇒ 就用它**；给了就不要再问"单价填多少" | 字段 `backend/app/models/product.py`（`default_unit_price`）。用户原话：「默认售价就是按那个来的，已经写在表格里了」 |
| 4 | **单位**没写 | 沿用**同类 / 既有商品**的单位（同系列商品用同一个单位，例如「跟 M325 一致 = 包」） | 读侧 `android/app/src/main/java/com/tapmoay/sorders/ai/AiReads.kt`（商品表里本来就有单位那一栏） |
| 5 | **专属价**要不要设 | 表格里**逐家给了价 ⇒ 直接按表格设专属价**，⛔ 不再问"要不要设专属价"；**没给价的那几行照建、专属价留空** | 落点 `price_rules`（批发商 × 商品 × `special_unit_price`，见 `backend/app/models/product.py`）；"专属价优先、否则默认价"的唯一判断处在 `android/app/src/main/java/com/tapmoay/sorders/ai/AiEffectivePrice.kt`。用户原话：表格里本来就写着每家两栏价 |
| 6 | 其它能查到的既有写法 | 分类、是不是会员、既有记录里的写法……**一律先取来用**，不要拿这些去问用户 | `android/app/src/main/java/com/tapmoay/sorders/ai/AiReads.kt`（按角色的只读能力）、`docs/PROJECT_MAP/01_ARCHITECTURE.md` |

**用到的假设必须写在确认卡上**，例如「初始密码按 `123321`」「成本价按进货成本 15.25 元/包」——
确认卡是用户唯一能核对"AI 替他定了什么"的地方。

---

## 二、边界：单子上**没有**默认值的，仍然必须问（而且一次问全）

- **动到钱**：金额、单价（表格里没给的那个）、成本、收款、结算、返点……
- **身份 / 权限**：谁能登录、谁能看什么、角色，以及**改一个已有账号的密码**（那没有默认值）。
- **撤不回来**：删除、作废、确认、付款。
- 判据一句话：**单子上有的 ⇒ 直接用（把假设写在卡上）；单子上没有的 ⇒ 问**。
  拿不准某样东西算不算"有默认值" ⇒ **按没有处理**，⛔ 不许猜一个数字填进钱或身份那一格。
- **真要问就一次问全**：把这次任务缺的**全部**未知项列成一个编号清单**一次问完**；
  ⛔ **不许一轮问一个、来回磨**（用户最烦的就是这个）；单子上已经有的不要再列进去。

---

## 三、⛔ 本单**没有**做的事（别顺手扩大）

- 确认卡（`preview_write` → 用户点确认才写）**仍然在**，一个字没动；
- 风险分级（LOW 直接执行、MEDIUM / HIGH 必须确认）**没有改**；
- 「不知道就去问、绝不许替他决定」那条**没有被删掉** —— 它被**收窄**成上面第二节的三种情形；
  `android/app/src/main/java/com/tapmoay/sorders/ai/AiAgentLoop.kt` 里那句话还在，判据 `_tools/qa/_check_default_password.py` 也钉着它。

---

## 四、机器判据

```
python _tools/qa/_check_ai_ask_less.py            # 判据：清单进了提示词 + 三条规则 + 边界 + 同源 + 文书单测
python _tools/qa/_reverse_verify_ai_ask_less.py   # 反向验证：注入若干次，每次都必须报红，且逐字节还原
```

单测（App 侧，直接读那段提示词正文）：`android/app/src/test/java/com/tapmoay/sorders/ai/AiAskLessTest.kt`。

---

## 五、判据钉住的锚点（⛔ 顺手改这些字符串会让判据红）

- `android/app/src/main/java/com/tapmoay/sorders/ai/AiRolePrompt.kt`：`internal object AiDefaults` / `val RULES: String`，
  以及清单里的字面量（`能按下面这张单子推断出来的，不要问`、`进货成本`、`真要问，就一次问全`、`不许一轮问一个`、`假设写在`）；
  这个文件里**只引用** `AccountRules.DEFAULT_INITIAL_PASSWORD`，⛔ 文件里不许出现字面量 `123321`。
- `android/app/src/main/java/com/tapmoay/sorders/ai/AiAgentLoop.kt`：`append(AiDefaults.RULES)`（把它拼进 systemPrompt）、
  `绝不许替他决定`（原有那条，仍在）。
- 这一页本身：`docs/PROJECT_MAP/INDEX.md` 里必须有一行指向它（否则 `backend/scripts/check_reachability.py` 会说它是孤儿文档）。
- 文书：`docs/changes/CHG-0120.md`（九节）、`docs/changes/README.md`（登记一行）、`docs/AI_WORK_CLAIM.md`（开工声明）。
