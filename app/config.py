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

    # ===== 可靠性：超时 / 重试 / 熔断 =====
    llm_connect_timeout: float = 5.0
    llm_read_timeout: float = 30.0
    llm_max_retries: int = 3                 # 单次调用最多尝试次数（含首次）
    llm_fallback_model: str = ""             # 主模型重试耗尽后的备用模型（空则只用主模型）
    embed_timeout: float = 20.0
    tool_timeout: float = 8.0
    tool_max_retries: int = 2                # 工具最多尝试次数（含首次）
    breaker_failure_threshold: int = 5       # 连续失败多少次打开熔断
    breaker_reset_timeout: float = 30.0      # 打开后多少秒进入半开探测

    # ===== HITL =====
    hitl_enabled: bool = True                # 执行前是否暂停，等待用户确认任务清单

    # ===== 行程持久化 =====
    trip_persist_enabled: bool = True

    # ===== 可观测（OTel / Jaeger）=====
    otel_enabled: bool = False
    otel_service_name: str = "startrip-agent"
    otel_endpoint: str = "http://localhost:4317"
    otel_insecure: bool = True

    # ===== JWT 鉴权 =====
    auth_enabled: bool = False
    jwt_secret: str = ""
    jwt_expire_minutes: int = 120


@lru_cache
def get_settings() -> Settings:
    """带缓存，避免重复解析 .env。"""
    return Settings()


settings = get_settings()
