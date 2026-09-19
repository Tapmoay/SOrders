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


@lru_cache
def get_settings() -> Settings:
    return Settings()
