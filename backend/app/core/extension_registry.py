# -*- coding: utf-8 -*-
"""扩展注册表（R4-03）—— 系统启动时，知道当前有哪些**合法**扩展。

指南 §15 原话：

> 注意，不是动态插件市场。而是：**系统启动时，知道当前有哪些合法扩展。**

## 这一版刻意不是什么（指南 §16，最想提前阻止的那个坑）

⛔ **不是热插拔**。指南原文：

> 生产服务器运行中 -> 上传 Python 文件 -> 立即热加载 —— 后者会突然产生版本兼容、状态迁移、
> 热加载、进程状态、安全边界、插件来源可信度、回滚、依赖冲突，复杂度瞬间爆炸。

所以 R4 第一阶段是「**可安装的模块化单体**」（deploy-time modularity），不是动态插件运行时：
扩展必须是**仓库里的代码**、随发布一起上去；注册表只在进程启动时扫一遍包目录。
⛔ 没有上传、没有文件监听、没有 exec/eval、没有运行期 reload —— 判据
`_check_extension_manifest.py` 逐条盯着这几个形状。

## 依赖方向（指南 §13，单向）

    Core Contract  <-  Extension Implementation

    Core -> ExtensionRegistry        ✅（核心**拥有**注册表）
    Extension -> ExtensionRegistry   ✅（扩展**声明**自己）
    Extension -> app.services         ❌（扩展不许碰核心私有内部）

## Manifest 的字段（指南 §15；这是**契约**，改字段要走契约流程）

id / version / kind / requires / provides / consumes / emits / config / compatibility，
涉及数据库再加 owns_tables；本项目另加两个本项目特有的字段：

* `routes` + `capability` —— 指南 §27：**路由可以由扩展提供，但鉴权必须归核心**。
  扩展只声明「我要挂一个路由，它需要哪条能力」，由核心在装配时施加 `require_permission`。
  于是扩展里**一行鉴权代码都没有**，也不可能另起一套授权世界（§31 坑 11）。
"""
from __future__ import annotations

import importlib
import os
import pkgutil
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterator, Mapping

#: 扩展必须住在这个包里（`app/extensions/<id>/`）。
EXTENSIONS_PACKAGE = "app.extensions"
#: 每个扩展的清单模块与其中的常量名。
MANIFEST_MODULE = "manifest"
MANIFEST_ATTR = "MANIFEST"

#: 四类扩展（指南 §8–§11）。⛔ 这不是"插件类型"，是**契约形状**的分类。
KINDS: tuple[str, ...] = ("pure-function", "policy", "provider", "presentation")

#: Manifest 的**必备字段**（指南 §15 列的九个 + 本项目的两个 + owns_tables）。
#: 判据 `_check_extension_manifest.py` 会拿它去核对 dataclass 与文档三方一致。
REQUIRED_FIELDS: tuple[str, ...] = (
    "id", "version", "kind", "requires", "provides", "consumes", "emits",
    "config", "compatibility", "owns_tables", "routes", "capability",
)

#: 配置前缀（指南 §26）：核心配置与扩展配置**必须分开**。
CORE_CONFIG_PREFIX = "CORE_"
EXTENSION_CONFIG_PREFIX = "EXT_"


class ExtensionRegistryError(ValueError):
    """清单不合法时抛的错（消息是一句能照着改的中文）。"""


@dataclass(frozen=True)
class ExtensionManifest:
    """一个扩展的**清单**：它要什么、给什么、吃什么、吐什么、能不能拆。

    `owns_tables` 只登记**它自己的运营数据**（指南 §25 的 B 类）。
    ⛔ 核心事实表（订单 / 账本 / 身份 / 审计）永远不在扩展的 owns_tables 里 ——
    那一条由 `_check_data_ownership.py` 判。
    """

    id: str
    version: int
    kind: str
    provides: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    emits: tuple[str, ...] = ()
    config: tuple[str, ...] = ()
    compatibility: str = ""
    owns_tables: tuple[str, ...] = ()
    #: 路由模块（相对本包的模块路径，如 `unit_conversion.api`）。空 = 不挂路由。
    routes: str = ""
    #: `routes` 需要的能力点（`core.rbac.Permission` 的成员名）。⛔ 由**核心**施加，不由扩展自己写。
    capability: str = ""
    #: 一句话：这个扩展解决什么（给人看的，也是"它为什么存在"的记录）。
    why: str = ""
    #: 默认启用；关掉它 = 指南 §24 的 Disable（代码还在，只是不装）。
    enabled: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in REQUIRED_FIELDS} | {"why": self.why, "enabled": self.enabled}


class ExtensionRegistry:
    """启动时装配的扩展表。⛔ 没有运行期 add/remove —— 那是热插拔，不是本项目这一阶段要做的事。"""

    def __init__(self) -> None:
        self._by_id: dict[str, ExtensionManifest] = {}

    def register(self, manifest: ExtensionManifest) -> None:
        if not manifest.id or not manifest.id.replace("-", "").replace("_", "").isalnum():
            raise ExtensionRegistryError("扩展 id 只能是字母数字与 - _：" + repr(manifest.id))
        if manifest.id in self._by_id:
            raise ExtensionRegistryError("扩展 id 重复：" + manifest.id + "（一个 id 只能有一个实现）")
        if manifest.kind not in KINDS:
            raise ExtensionRegistryError(
                "扩展 " + manifest.id + " 的 kind=" + repr(manifest.kind) + " 不在 " + repr(list(KINDS)) + " 里"
            )
        if not isinstance(manifest.version, int) or manifest.version <= 0:
            raise ExtensionRegistryError("扩展 " + manifest.id + " 的 version 必须是正整数")
        if bool(manifest.routes) != bool(manifest.capability):
            raise ExtensionRegistryError(
                "扩展 " + manifest.id + " 要么既没有 routes/capability，要么两个都有（§27：路由必须由核心鉴权）"
            )
        self._by_id[manifest.id] = manifest

    def get(self, ext_id: str) -> ExtensionManifest | None:
        return self._by_id.get(ext_id)

    def all(self) -> tuple[ExtensionManifest, ...]:
        return tuple(self._by_id[k] for k in sorted(self._by_id))

    def enabled(self) -> tuple[ExtensionManifest, ...]:
        return tuple(m for m in self.all() if m.enabled)

    def by_kind(self, kind: str) -> tuple[ExtensionManifest, ...]:
        return tuple(m for m in self.all() if m.kind == kind)

    def by_provides(self, capability: str) -> tuple[ExtensionManifest, ...]:
        return tuple(m for m in self.all() if capability in m.provides)

    def owned_tables(self) -> dict[str, str]:
        """表名 -> 谁拥有它。⛔ 同一张表被两个扩展认领 = 报错（一个事实两个主人）。"""
        out: dict[str, str] = {}
        for m in self.all():
            for t in m.owns_tables:
                if t in out:
                    raise ExtensionRegistryError(
                        "表 " + t + " 被两个扩展同时认领：" + out[t] + " 与 " + m.id
                    )
                out[t] = m.id
        return out

    def __len__(self) -> int:
        return len(self._by_id)

    def __iter__(self) -> Iterator[ExtensionManifest]:
        return iter(self.all())


def discover(package: str = EXTENSIONS_PACKAGE) -> ExtensionRegistry:
    """扫描扩展包，把每个 `manifest.py` 里的 MANIFEST 登记进来。

    ⚠️ 这里用 pkgutil + importlib 是**部署期**的包扫描（代码随发布一起上去），
    ⛔ 不是运行期热加载：没有文件监听、没有上传、没有 exec/eval、没有 reload。
    「扩展必须是仓库里的代码」这条由 `_check_extension_manifest.py` 盯着。
    """
    registry = ExtensionRegistry()
    try:
        pkg = importlib.import_module(package)
    except ImportError:
        return registry          # 还没有任何扩展：空表是合法状态
    for info in pkgutil.iter_modules(list(getattr(pkg, "__path__", []))):
        if not info.ispkg:
            continue
        try:
            mod = importlib.import_module(package + "." + info.name + "." + MANIFEST_MODULE)
        except ImportError as exc:
            raise ExtensionRegistryError(
                "扩展目录 " + info.name + " 没有 " + MANIFEST_MODULE + ".py —— 每个扩展都必须声明清单"
            ) from exc
        manifest = getattr(mod, MANIFEST_ATTR, None)
        if not isinstance(manifest, ExtensionManifest):
            raise ExtensionRegistryError(
                "扩展 " + info.name + " 的 " + MANIFEST_MODULE + ".py 里没有 ExtensionManifest 类型的 " + MANIFEST_ATTR
            )
        if manifest.id != info.name:
            raise ExtensionRegistryError(
                "扩展目录名 " + info.name + " 与清单 id " + manifest.id + " 不一致（找不到它时该信谁？）"
            )
        registry.register(manifest)
    return registry


def mount_extension_routes(app: Any, registry: ExtensionRegistry, *, prefix: str = "") -> list[str]:
    """把扩展声明的路由挂到应用上 —— **鉴权由核心施加**（指南 §27）。

    指南 §27 要的是一条单向链：

        Extension declares capability  ->  Core authorization  ->  route

    而不是「Extension 自己写一套权限」。落到代码就是这一句：

        app.include_router(router, prefix=prefix, dependencies=[Depends(require_permission(perm))])

    于是扩展的路由模块里**一行鉴权都没有**（判据 _check_extension_dependencies.py 第 3 组核），
    也不可能出现 extension_permission.py 那种另起一套授权世界的写法（§31 坑 11）。

    返回挂上的扩展 id 列表（给启动日志用）。⛔ 只在启动时调用一次。
    """
    from fastapi import Depends

    from app.core.rbac import Permission
    from app.deps import require_permission

    mounted: list[str] = []
    for manifest in registry.enabled():
        if not manifest.routes:
            continue
        module = importlib.import_module(EXTENSIONS_PACKAGE + "." + manifest.id + "." + manifest.routes)
        router = getattr(module, "router", None)
        if router is None:
            raise ExtensionRegistryError(
                "扩展 " + manifest.id + " 声明了 routes=" + repr(manifest.routes)
                + "，但那个模块里没有 router"
            )
        permission = getattr(Permission, manifest.capability, None)
        if permission is None:
            raise ExtensionRegistryError(
                "扩展 " + manifest.id + " 的能力点 " + repr(manifest.capability)
                + " 不是 core.rbac.Permission 的成员 —— 路由不能拿一个不存在的能力点当门槛"
            )
        app.include_router(router, prefix=prefix, dependencies=[Depends(require_permission(permission))])
        mounted.append(manifest.id)
    return mounted


def extension_config(manifest: ExtensionManifest, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """按清单声明的 `config` 取配置，**只认 `EXT_<ID>_<KEY>` 前缀**（指南 §26）。

    ⛔ 扩展不许自己去读 `os.environ`：读得到 `JWT_SECRET_KEY` / `DATABASE_URL` 就等于
    拿到了核心机密；而"一个扩展的环境变量污染整个系统"正是指南 §26 点名要防的事。
    返回的是**只读**映射 —— 取到之后就地改，配置就成了第二份真相。
    """
    env = os.environ if environ is None else environ
    prefix = EXTENSION_CONFIG_PREFIX + manifest.id.upper().replace("-", "_") + "_"
    out: dict[str, str] = {}
    for key in manifest.config:
        name = prefix + key.upper()
        if name in env:
            out[key] = env[name]
    return MappingProxyType(out)  # type: ignore[return-value]
