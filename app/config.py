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
    db_pool_timeout: float = 5.0        # 取连接/建连超时（秒），防 PG 卡住拖垮请求

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
    mcp_connect_timeout: float = 30.0        # MCP 子进程冷启动超时（和单次工具超时分开）
    executor_deadline: float = 60.0          # 单轮所有工具的总预算，防任务扇出拖死请求
    breaker_failure_threshold: int = 5       # 连续失败多少次打开熔断
    breaker_reset_timeout: float = 30.0      # 打开后多少秒进入半开探测

    # ===== 编排护栏 =====
    max_tasks: int = 12                      # 单轮最多执行多少个工具任务（防 LLM 扇出）
    max_tool_results_per_tool: int = 10      # 同名工具最多保留多少条结果
    max_tool_result_chars: int = 8000        # 单条工具结果最大字符数（防 checkpoint 膨胀）
    sse_heartbeat_seconds: float = 15.0      # SSE 心跳间隔

    # ===== 质量校验 =====
    travel_speed_kmh: float = 18.0           # 城市内驾车平均速度（用于无路线数据时的通勤估算）
    grounding_max_ungrounded_ratio: float = 0.34  # 未接地景点占比超过该值直接压分

    # ===== HITL =====
    hitl_enabled: bool = True                # 执行前是否暂停，等待用户确认任务清单

    # ===== 行程持久化 =====
    trip_persist_enabled: bool = True

    # ===== Redis 偏好 =====
    pref_ttl_seconds: int = 7 * 24 * 3600

    # ===== 可观测（OTel / Jaeger）=====
    otel_enabled: bool = False
    otel_service_name: str = "startrip-agent"
    otel_endpoint: str = "http://localhost:4317"
    otel_insecure: bool = True

    # ===== JWT 鉴权 =====
    auth_enabled: bool = False
    jwt_secret: str = ""
    jwt_expire_minutes: int = 120

    # ===== 会话（AUTH_ENABLED=false 的公开 Demo 也建议开启） =====
    # require_signed_session=true 时，客户端必须先用 /api/session 换取带签名的
    # session_id，避免"猜到 session_id 就能读别人行程"。
    require_signed_session: bool = False
    session_secret: str = ""                 # 为空时回退 JWT_SECRET；再为空则启动警告


@lru_cache
def get_settings() -> Settings:
    """带缓存，避免重复解析 .env。"""
    return Settings()


settings = get_settings()
