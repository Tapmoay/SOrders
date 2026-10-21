#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_check_release_notes.py —— 「更新日志」（FEAT-0029）的判据。

### 用户要的是什么
> 「更新日志……就是每次办完更新了什么可以查看的，就在我们那个更新那个入口里有个更新日志，
>   可以查看每个版本更新了什么。」

### 这条最容易"看起来做了、其实没有"的四处
| # | 走样的写法 | 后果（界面上看不出来） |
|---|---|---|
| 1 | 拿 version.json 的 note 当历史 | 它**每次发布都被覆盖**，列表永远只有一版 —— 用户点开只看得到"本次" |
| 2 | 历史只留在服务器上 | 谁改了哪一版没人能复核；迁移/换机/重建就丢光 |
| 3 | 发布脚本不追加 | 只有当次手写的 json 里有那一版，下一次发版又是空的 |
| 4 | 拉失败给空列表 | 界面上一片空白，读起来是"这软件从没更新过"，而不是"没拉到" |

所以判据盯：**仓库里那份历史**（docs/releases.json）/ **后端那条只读入口**（含兜底）/
**发布脚本真的追加并上传** / **App 那条路走通**（DTO → Api → Repo → VM → 界面）。

用法：
    python _tools/qa/_check_release_notes.py --check   # 非零退出＝有问题（进 _check_all.py）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    _s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[2]
RELEASES = ROOT / "docs/releases.json"
MAIN = ROOT / "backend/app/main.py"
PUBLISH = ROOT / "_tools/deploy/publish_apk.py"
DTOS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/dto/Dtos.kt"
APIS = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/remote/api/Apis.kt"
REPO = ROOT / "android/app/src/main/java/com/tapmoay/sorders/data/repo/AppRepository.kt"
VM = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/profile/ProfileViewModel.kt"
SCREEN = ROOT / "android/app/src/main/java/com/tapmoay/sorders/ui/profile/ProfileScreen.kt"

MIN_RULES = 12

bad: list[str] = []
checked = 0


def _ok(m: str) -> None:
    global checked
    checked += 1
    print("  OK   " + m)


def _bad(m: str) -> None:
    global checked
    checked += 1
    print("  BAD  " + m)
    bad.append(m)


def _need(name: str, cond: bool, why: str = "") -> None:
    if cond:
        _ok(name)
    else:
        _bad(name + ("　—— " + why if why else ""))


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def main() -> int:
    main_py = _read(MAIN)
    pub = _read(PUBLISH)
    dtos = _read(DTOS)
    apis = _read(APIS)
    repo = _read(REPO)
    vm = _read(VM)
    screen = _read(SCREEN)

    print("1. 仓库里那份历史（docs/releases.json）")
    raw = _read(RELEASES)
    doc = None
    try:
        doc = json.loads(raw) if raw else None
    except Exception as e:  # noqa: BLE001
        _bad("docs/releases.json 不是合法 JSON：" + str(e))
    items = doc.get("items") if isinstance(doc, dict) else None
    _need("docs/releases.json 存在且解析得出 items", isinstance(items, list) and bool(items),
          "历史只留在服务器上 = 谁也复核不了、换机就丢")
    if isinstance(items, list) and items:
        _need("每条都有 version 与 note",
              all(isinstance(i, dict) and i.get("version") and isinstance(i.get("note"), str) for i in items))
        codes = [int(i.get("version_code") or 0) for i in items]
        _need("按构建号**新的在前**（version_code 降序）", codes == sorted(codes, reverse=True),
              "排序写在发布脚本里；这里防的是手改把顺序弄反")
        _need("每条都有日期（YYYY-MM-DD）",
              all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(i.get("date") or "")) for i in items),
              "没有日期的更新日志读不出发版时间")

    print("2. 后端那条只读入口（含兜底）")
    _need("有 GET /api/v1/system/app-releases", "/api/v1/system/app-releases" in main_py)
    _need("它读的是 uploads/app/releases.json", 'app" / "releases.json"' in main_py)
    _need("缺文件时退回 version.json 那一条（⛔ 不返回空列表）",
          "_one_from_version_json" in main_py and "app_version()" in main_py,
          "空列表在界面上等于这功能坏了")
    _need("出参字段是 version / version_code / date / note",
          all(k in main_py for k in ('"version"', '"version_code"', '"date"', '"note"')))
    _need("上限 50 条（别让一个坏文件把首页撑爆）", "[:50]" in main_py)

    print("3. 发布脚本真的追加并上传（⛔ 不是手写）")
    _need("publish_apk.py 读/写 docs/releases.json", '"docs" / "releases.json"' in pub or "docs" in pub and "releases.json" in pub)
    _need("同一个 versionCode 重发不重复追加", '!= code' in pub or "!= int" in pub)
    _need("上传之后写服务器上的 releases.json", "releases.json.tmp" in pub)

    print("4. App 那条路（DTO → Api → Repo → VM → 界面）")
    _need("DTO AppReleaseDto 带四个字段",
          "class AppReleaseDto" in dtos and '"version_code"' in dtos)
    _need("SystemApi.appReleases()", "suspend fun appReleases()" in apis and "system/app-releases" in apis)
    _need("AppRepository.appReleases()", "suspend fun appReleases()" in repo)
    _need("VM 有 openReleaseNotes / closeReleaseNotes 与拉取状态",
          "fun openReleaseNotes()" in vm and "fun closeReleaseNotes()" in vm and "releaseNotesError" in vm)
    _need("「我的」页有一行「更新日志」并打开弹层",
          '"更新日志"' in screen and "openReleaseNotes()" in screen and "ReleaseNotesDialog(" in screen)
    _need("拉失败**不装没事**（说清 + 重试），⛔ 不给空列表当结果",
          "没拉到更新日志：" in screen and '"重试"' in screen,
          "空列表读起来像是从没更新过")

    print()
    if bad:
        print("❌ 失败 %d 项（共 %d）：" % (len(bad), checked))
        for b in bad:
            print("   - " + b)
        return 1
    if checked < MIN_RULES:
        print("❌ 只跑到 %d 项（下限 %d）—— 源码形状多半变了" % (checked, MIN_RULES))
        return 1
    print("✅ 全部通过：%d 项" % checked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
