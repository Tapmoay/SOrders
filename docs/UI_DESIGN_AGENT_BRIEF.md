# SOrders UI 设计性格说明书（给 UI 设计 Agent）

本文档供 **UI 设计 Agent / 前端实现** 统一遵循，来源为产品「派单送货管理系统」与用户确认的 **方向 3（克制品牌蓝）+ 方向 4（清晰信息层级 / 可扫读）**，并与 **ui-ux-pro-max** 优先级一致：无障碍与触控 → 性能 → 布局响应 → 字体与色 → 动效。

## 产品语境

- **场景**：货主 / 司机 / 派单员在移动端与桌面窄屏下长时间查看订单、状态与表单。
- **目标**：专业、可信、**不费眼**；避免营销页式强渐变与装饰性动效。

## 设计性格（合并方向 3 + 4）

| 维度 | 要求 |
|------|------|
| **色彩** | **单一强调色**（品牌蓝 `#1677ff` / `#0958d9`）仅用于主操作、导航强调、选中态；背景以浅灰与白为主；禁止彩虹标签、大面积霓虹渐变底。 |
| **层级** | 标题与数据 **字重 / 字号** 区分明确；列表 **行高充足**；状态用 **短文案 + 低饱和辅助色**，不靠颜色单打独斗。 |
| **密度** | 可扫读优先：单屏信息分组清晰，**不堆叠**多种装饰（阴影+描边+渐变同时上）。 |
| **动效** | 仅 **150–200ms** 的微交互（透明度、背景色）；禁止无意义循环动画；尊重 `prefers-reduced-motion`。 |
| **触控** | 可点区域 **≥ 44×44px**，相邻可点元素 **≥ 8px** 间距。 |
| **图标** | 统一线性图标集（Vant 内置），**不用 emoji 充当图标**。 |

## 英文提示词（可复制给生成式 UI Agent）

```text
Restrained enterprise SaaS UI for a logistics dispatch app: single accent blue (#1677ff) for primary actions and nav only; neutral gray backgrounds (#f5f7fa / white); clear typographic hierarchy (semibold titles, regular body, muted secondary text); scannable lists with comfortable row height; minimal decoration—no rainbow tags, no hero gradients, no flashy motion; subtle shadows; WCAG-minded contrast; touch targets min 44px.
```

## 技术栈约束

- 前端：**Vue 3 + Vant 4**；主题通过 **CSS 变量**（`--van-primary-color` 等）在 `frontend/src/styles/theme-tokens.css` 统一覆盖。
- 实现时优先 **ConfigProvider / 全局 token**，避免页面级魔法数散落。

## 交付自检（对齐 ui-ux-pro-max）

- [ ] 正文与背景对比度足够（约 ≥ 4.5:1）。
- [ ] 焦点态可见（键盘/无障碍）。
- [ ] 主按钮 loading 时禁用重复提交。
- [ ] 移动端无横向滚动条（常规列表页）。
