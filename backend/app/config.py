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

    jwt_secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    amap_key: str = ""
    amap_security_js_code: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
