# -*- coding: utf-8 -*-
"""扩展区（Extension Zone）—— **可以新增 / 替换 / 升级 / 禁用 / 拆除** 的那一块。

指南 §1 画的结构：

    SOrders
      ├── CORE / KERNEL      固定核心（语义 / 不变量 / 生命周期 / 安全边界 / 事实模型）
      └── EXTENSION ZONE     扩展区域（Unit Conversion / Pricing / Export Provider …）

## 这一包的规矩（逐条都有判据盯着）

1. 每个扩展一个子目录 `app/extensions/<id>/`，目录名就是扩展 id；
2. 目录里**必须有** `manifest.py`，里面是一个 `MANIFEST = ExtensionManifest(...)`；
3. ⛔ **不许 import 核心私有内部**：`app.services` / `app.api` / `app.models` / `app.database` / `app.deps`
   一律不许碰。能 import 的只有 `app.core.contracts.*`、`app.core.extension_registry` 与标准库；
4. ⛔ **不许改核心拥有的数据**（订单 / 账本 / 身份 / 审计 —— 见 docs/R4_CORE_EXTENSION_MAP.md）；
5. ⛔ **不许自己写鉴权**：路由由核心装配并施加 `require_permission`，扩展只在清单里声明能力点；
6. ⛔ **不许动态加载**：没有上传、没有文件监听、没有 exec/eval/reload —— 扩展是**仓库里的代码**；
7. ⛔ **不许自己读环境变量**：配置一律经 `extension_registry.extension_config()`，且只认 `EXT_` 前缀。

判据：`python _tools/qa/_check_extension_manifest.py`、`_check_extension_dependencies.py`、
`_check_data_ownership.py`（三个都在 `_check_all.py` 的全量检查里）。

## 一个扩展长什么样

    app/extensions/unit_conversion/
        __init__.py
        manifest.py      # MANIFEST = ExtensionManifest(id="unit_conversion", kind="pure-function", ...)
        <实现>.py        # 契约的实现（UnitConversionContract v1 等）

⛔ 这一包**一行核心代码都不该有**：它是扩展区，不是第二个 core。
"""