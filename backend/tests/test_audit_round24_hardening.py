"""2026-09-19 审计（安卓专轮）里**后端**那两条低危的回归测试。

两条的形状一样：「防线写了，但没真挡住」——所以判据都拿**真实输入**打，不去读注释：

- **L-15**：`/static/uploads` 的穿越防线原来是字符串前缀比较（`str(target).startswith(str(base))`），
  而 `uploads_evil/…` 的前缀**就是** `uploads/` 的前缀 → 实测 `..%2F` 形状返回 **200 + 文件内容**。
  这里用 TestClient 真的去取兄弟目录里的文件（改前红、改后 404）。
- **P1-12**：`core/security.py` 的回落密钥是 `secrets.token_urlsafe(48)` 的**裸串**，
  当时四条正则一条都不匹配，于是"被 `git add` 进去、推上公开仓库、而所有静态检查全绿"可行。
  这里既端到端喂给 `_tools/qa/_check_secrets.py`（按文件路径加载，它不在 backend 的 import 路径上），
  也拿 `git check-ignore` / `git ls-files` 真的问 git —— 而不是读一遍 `.gitignore` 的文本。
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ L-15

@pytest.fixture
def upload_pair() -> Iterator[tuple[str, str, str]]:
    """造一对「`uploads/` 里的正常文件」与「兄弟目录里的泄露物」。

    内层故意放在 `uploads/delivery/{tag}/` 下：与线上图片 URL
    （`/static/uploads/delivery/{order_id}/{uuid}.jpg`）同形，这样"正常路径不受影响"
    那条断言测的才是线上真正在用的形状。路径相对当前工作目录（后端就是这么解析
    `Path("uploads")` 的），所以测试要从 `backend/` 跑（`pytest.ini` 的 rootdir）。

    目录名带 worker 标记：本项目 `run_tests.ps1` 默认按 CPU 起多个 worker（`-n auto`），
    写死名字的话两个 worker 会在同一个探针目录上互相删文件。
    返回 `(内层 URL, 相对 uploads/ 的 `../` 形状, 兄弟目录里的内容)`。
    """
    tag = os.environ.get("PYTEST_XDIST_WORKER") or f"p{os.getpid()}"
    inside_dir = Path("uploads") / "delivery" / tag
    sibling = Path(f"uploads_evil_{tag}")
    inside_dir.mkdir(parents=True, exist_ok=True)
    sibling.mkdir(parents=True, exist_ok=True)
    inside = inside_dir / "inside.txt"
    outside = sibling / "outside.txt"
    inside.write_text("INSIDE", encoding="utf-8")
    outside.write_text("SIBLING-SECRET", encoding="utf-8")
    try:
        yield (
            f"/static/uploads/delivery/{tag}/inside.txt",
            f"../{sibling.name}/{outside.name}",
            "SIBLING-SECRET",
        )
    finally:
        inside.unlink(missing_ok=True)
        outside.unlink(missing_ok=True)
        for d in (inside_dir, sibling):
            try:
                d.rmdir()
            except OSError:  # 目录里还有别人的东西就不动它
                pass


def test_static_uploads_still_serves_files_inside_uploads(
    client: TestClient, upload_pair: tuple[str, str, str]
) -> None:
    """收紧判据不许误伤正常路径（线上每一张送达照片都走这条路由）。"""
    url, _, _ = upload_pair
    r = client.get(url)
    assert r.status_code == 200
    assert r.text == "INSIDE"


def test_static_uploads_blocks_traversal_to_sibling_dir(
    client: TestClient, upload_pair: tuple[str, str, str]
) -> None:
    """`uploads_evil/` 不是 `uploads/` 的子路径——不管怎么写都不能读到它。"""
    _, rel, secret = upload_pair
    for shape in (
        rel,                                          # 对照组：点段交给路由归一，本来就 404
        rel.replace("/", "%2F"),                      # ⚠️ 改前就是这条以 200 读到了兄弟目录
        rel.replace(".", "%2e").replace("/", "%2F"),  # 点号也编码的同一形状
    ):
        r = client.get("/static/uploads/" + shape)
        assert r.status_code == 404, f"{shape} 没被拦住：{r.status_code}"
        assert secret not in r.text


# ----------------------------------------------------------------- P1-12

def _secrets_check():
    """按文件路径加载 `_tools/qa/_check_secrets.py`（它是脚本，不在 backend 的 import 路径上）。"""
    path = ROOT / "_tools" / "qa" / "_check_secrets.py"
    spec = importlib.util.spec_from_file_location("_qa_check_secrets_under_test", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_secrets_check_reports_a_tracked_bare_key_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """端到端：把「已经进了索引的裸密钥文件」喂给检查，它必须**按裸密钥报出来**。

    断言的是输出里那句话而不是退出码：退出码 1 还可能来自它自己的反空转判据
    （`scanned < 200`），那样这条测试就会为错误的原因变绿。
    """
    mod = _secrets_check()
    (tmp_path / ".jwt_secret.local").write_text("aB3" + "xY9" * 15, encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "tracked_files", lambda: [".jwt_secret.local"])

    assert mod.main() == 1
    assert "裸密钥串" in capsys.readouterr().out


def test_bare_secret_shape_does_not_fire_on_ordinary_lines() -> None:
    """钉住边界：只按"长"判会把常量名报成密钥，而**假阳性会让下一个人学会无视这条检查**。"""
    patterns = [rx for rx, why in _secrets_check().PATTERNS if "裸密钥" in why]
    assert len(patterns) == 1
    assert patterns[0].search("aB3" + "xY9" * 15)  # 形状同 secrets.token_urlsafe(48)
    for line in (
        "PACKAGE_SYSTEM_GUIDELINES_SECTION",
        "FALLBACK_SECRET_FILE = Path(__file__).resolve().parents[2] / '.jwt_secret.local'",
        "api_key = settings.amap_key",
    ):
        assert not patterns[0].search(line), line


def test_bare_secret_shape_matches_the_real_fallback_key() -> None:
    """把判据钉在**真产物**上：`security.py` 落盘的那串就是这条正则要抓的东西。

    只拿自己造的样例测，等于测"我以为密钥长什么样"——这里读的是本机真实
    `FALLBACK_SECRET_FILE`（不外传、不打日志，只判能不能被匹配上；配了
    `JWT_SECRET_KEY` 的环境本来就不会有这个文件，跳过）。
    """
    from app.core.security import FALLBACK_SECRET_FILE

    if not FALLBACK_SECRET_FILE.is_file():
        pytest.skip("本机没有落盘的回落密钥")
    patterns = [rx for rx, why in _secrets_check().PATTERNS if "裸密钥" in why]
    content = FALLBACK_SECRET_FILE.read_text(encoding="utf-8").strip()
    assert patterns and any(rx.search(content) for rx in patterns)


def test_fallback_secret_file_is_ignored_and_untracked() -> None:
    """`security.py` 原来那句「已被 .gitignore 覆盖」是假的：实测 `git check-ignore` 退出码 1、
    文件是未跟踪状态，`git add -A` 就会把这条**活密钥**推进这个公开仓库。

    路径从源码里的 `FALLBACK_SECRET_FILE` 取（不写死），否则搬了家两处就走散了。
    """
    from app.core.security import FALLBACK_SECRET_FILE

    rel = FALLBACK_SECRET_FILE.relative_to(ROOT).as_posix()
    ignored = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT)
    assert ignored.returncode == 0, f"{rel} 没有被 .gitignore 忽略（活密钥会被 git add 收走）"
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True, text=True
    )
    assert tracked.returncode != 0, f"{rel} 已被 git 跟踪——立刻 git rm --cached 并轮换密钥"
