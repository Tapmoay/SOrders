from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _repo_version() -> str:
    """产品版本号的**唯一来源** = 仓库根的 `VERSION` 文件。

    2026-09-24 整改（报告 §20 第 ⑧ 项"版本号统一"）：这里原来是**硬编码** `"0.2.0"`，
    而仓库根 `VERSION` 写着 0.2.4、前端 `package.json` 也是 0.2.0 ——
    实测基线（`docs/BASELINE.md`）就把它列为一条"版本漂移"：
    **"线上到底跑的是哪一版"说不清**（`/health` 报 0.2.0，包里却是 0.2.4）。

    安卓那边早就这么做了（`android/app/build.gradle.kts` 构建时读 `../VERSION`），
    这里补上同一件事：**三处版本号共用一个文件**。

    ⚠️ 读不到时返回 `"0.0.0"` 而不是旧的 `"0.2.0"`：那是"说不清"的旧值，
    留着只会让人继续以为版本对得上；`0.0.0` 一眼就能看出"这个部署没带上 VERSION"。
    """
    try:
        version = (Path(__file__).resolve().parents[2] / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return version or "0.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "SOrders API"
    #: 产品版本（语义化）。**从仓库根 VERSION 读**，不再硬编码 —— 见上面 _repo_version() 的说明。
    #: 仍可用环境变量 `APP_VERSION` 覆盖（pydantic-settings 的常规行为）。
    app_version: str = _repo_version()
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str = "mysql+pymysql://root:password@127.0.0.1:3306/sorders"
    redis_url: str = "redis://127.0.0.1:6379/0"
    #: 业务指标端点（`GET /metrics`）的抓取口令（整改阶段 8 ②）。
    #: ⛔ **留空 = 不开放**（fail-closed）：没配口令时端点一律 403 ——
    #: 一个"默认打开"的指标端点等于把业务量白送给任何扫到它的人。
    #: 生产上只让服务器本机的监控用；**不要**在 nginx 里给它开口子。
    metrics_token: str = ""
    # Socket.IO Redis 适配器地址（多 worker 需共享连接状态；留空=进程内内存模式）
    socket_redis_url: str = ""

    # ⚠️ **刻意不给默认值**（2026-09-19 安全审计）：
    #     原来这里是 `"change-me-in-production-use-openssl-rand-hex-32"`，而这个仓库是**公开的** ——
    #     意思是"没配 JWT_SECRET_KEY"的一端（本机 backend/.env 当时就没有这一行）会落到一个人人可读的
    #     字符串上，任何人拿它离线签一个 `{"sub": "1"}` 就能以派单员身份读走全部订单/账本/手机号
    #     （审计已端到端实测：伪造 token → GET /users/me 返回 200 + dispatcher 身份）。
    #     现在的语义：留空 = 由 `core/security.get_jwt_secret()` 生成**本次进程专用**的随机密钥并大声警告。
    #     —— 不会静默弱；配置了就不能再猜；改配置要重启（本来就要）。
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    amap_key: str = ""
    amap_security_js_code: str = ""

    # ---- 测试账号的默认 AI 配置（2026-09-21 用户要求）----
    # 「只要是测试账号默认就跑，我们那个 api key」——测试号每次换手机/模拟器都要手填一次 key，
    # 太麻烦；改成由**服务端下发**给白名单里的测试号。
    #
    # ⛔ **只写在服务器 `.env` 里**（600 权限），**绝不进仓库、也绝不进 APK**：
    #    这个仓库是公开的，而 APK 就挂在 `http://8.145.40.22/apk` 上给任何人下载 ——
    #    把 key 编进包里等于公开它（2026-09-19 已经吃过一次凭据进公开仓库的教训）。
    # ⛔ 拿不到 key 时的行为必须是**干净的失败**（404），不许返回空串让客户端去猜。
    ai_default_api_key: str = ""
    ai_default_base_url: str = "https://api.deepseek.com"
    ai_default_model: str = "deepseek-flash"
    #: 哪些手机号算「测试账号」（**前缀匹配**）：用户的命名约定是 `1380000000X`
    #: （1=派单员 / 2=货主 / 3=司机(固定工资) / 4=司机(挂车) / 5=普通货主…）。
    #: 留空 = 这个能力**整体关闭**（谁都不许拿默认 key）。
    ai_test_phone_prefix: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
