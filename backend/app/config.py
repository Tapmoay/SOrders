from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "SOrders API"
    #: 与仓库根目录 VERSION、前端 package.json 对齐（语义化版本，0.2.0 即产品「0.02」）
    app_version: str = "0.2.0"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    database_url: str = "mysql+pymysql://root:password@127.0.0.1:3306/sorders"
    redis_url: str = "redis://127.0.0.1:6379/0"
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
