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

    jwt_secret_key: str = "change-me-in-production-use-openssl-rand-hex-32"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    amap_key: str = ""
    amap_security_js_code: str = ""

    #: 为 true 时发送验证码接口在响应中返回明文 code；生产务必 false。本地若已设 DEBUG=true 也会回显
    sms_reveal_code: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
