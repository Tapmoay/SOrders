# 报表中心改造 · 样板存档（非生产代码）

> **这是什么**：2026-10-05 为「报表中心改成看钱 + 经营状态」做的**手机版样板**与两路只读接口盘点。
> ⛔ 这里的东西**不进 App、不参与构建**，只作为改造真实项目（Android 报表中心）时的对照物。
>
> **为什么在仓库里**：样板的版式、口径说明、下钻链路是被用户逐轮点过、改过的结论；
> 丢掉它就只剩聊天记录。改造时按这里的屏与文案对齐，⛔ 不要再各写一套。

## 目录

| 目录 | 内容 | 说明 |
| --- | --- | --- |
| `web/` | 手机版测试网页（真连后端） | [index.html](web/index.html) + `js/`（core / pages1-3 / shell / dash2 / chart2 / tree / tree2 / orders / stock / drawer / docs / look）+ `css/`；`shots/` 是逐轮截图 |
| `static-sample/` | 最早那版**纯静态**样板 | 单文件 [index.html](static-sample/index.html)（假数据），版式与选色说明见 [DESIGN.md](static-sample/DESIGN.md)；`shots/` 是截图 |
| `research/` | 两路只读接口盘点 | [backend_surface.md](research/backend_surface.md)（reports/stats/cash/expense/invoice/…）、[api_stock_payable.md](research/api_stock_payable.md)（库存/采购/应付/成本价）、[api_drilldown.md](research/api_drilldown.md)（订单与下钻链路）、[android_ui_surface.md](research/android_ui_surface.md)（App 报表中心现状） |

## 样板里已经定下来的东西（改造时照这个来）

1. **第一页 = 会计五个标准**：利润表 / 资产负债表 / 现金流量表 / 运营分析表 / 关键指标表。合并成**一张卡**，每行一个图标 + 名称 + 一句人话 + 一个主数字 + 迷你条，整行可点。
2. **时间控件**：一个药丸（日历图标 + 当前区间 + 下拉箭头），八个档位（今天/本周/上周/本月/上月/本季/本年/全部）+ 自选起止；真库无数据的窗口要自动退到最近有数据的窗口并说明。
3. **逐层下钻，最底层是订单**：报表数字 → 单据（费用单 / 现金流水 / 应付单 / 库存流水 / 发票 / 车辆台账）→ 订单 → 商品行。接口没有的（购车价、发票 ↔ 订单）**如实标注原因**，不装作有。
4. **数字不挂多余尾零**（`3,700.00` → `3,700`）。
5. **以图标 + 语义色表达为主，但保留视觉重心**：只有「要处理」的上红/橙，正常项一律中性；⛔ 不满屏彩色、⛔ 页面上不出现 JSON 原文。
6. **左侧抽屉**保留原有入口，点进原来的页面照旧看数据。

## 怎么跑（要重新看样板时）

```powershell
python -m http.server 8090 --bind 127.0.0.1   # workdir 指到 web/ 或 static-sample/
```

浏览器打开 `http://127.0.0.1:8090/index.html`，用 `13800000001 / pass12345`（派单员）登录；
报表接口只对派单员开放，后端默认在 `http://127.0.0.1:8000`（CORS 允许任意来源）。
