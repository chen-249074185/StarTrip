from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置：从 .env 读取，字段对齐 .env.example。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ===== LLM / Embedding =====
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    dashscope_api_key: str = ""

    # ===== 高德（后端 Web 服务 key + 前端 JS key）=====
    amap_key: str = ""
    amap_js_key: str = ""
    amap_js_security_code: str = ""

    # ===== 天气（心知天气）=====
    seniverse_api_key: str = ""

    # ===== PostgreSQL（pgvector + Checkpoint）=====
    postgres_db: str = "startrip"
    postgres_user: str = "user"
    postgres_password: str = "pass"
    database_url: str = "postgresql://user:pass@localhost:5432/startrip"

    # ===== Redis =====
    redis_url: str = "redis://localhost:6379/0"

    # ===== RAG =====
    rag_sim_threshold: float = 0.6   # dense 检索余弦相似度阈值（低于则丢弃，防无关资料注入）

    # ===== JWT 鉴权 =====
    jwt_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    """带缓存，避免重复解析 .env。"""
    return Settings()


settings = get_settings()
