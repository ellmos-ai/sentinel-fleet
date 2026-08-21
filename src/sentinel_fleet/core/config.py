"""Configuration management for SentinelFleet."""

import os
from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = "SentinelFleet"
    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    google_cloud_project: str = Field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT", "sentinel-fleet-demo"))
    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_default_model: str = Field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))
    host: str = Field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("PORT", "8080")))
    data_dir: str = Field(default_factory=lambda: os.getenv("DATA_DIR", "./data"))
    # Result metadata uses Firestore in production; bytes use a private Cloud Storage bucket.
    # The bucket remains lazy/fail-closed so a missing deployment setting cannot leak to RAM.
    result_bucket: str = Field(default_factory=lambda: os.getenv("RESULT_BUCKET", ""))
    max_result_bytes: int = Field(
        default_factory=lambda: int(os.getenv("MAX_RESULT_BYTES", str(16 * 1024 * 1024)))
    )
    # The public build demonstrates authorization without pretending the query-string identity
    # is authentication.  In demo mode, sensitive administration remains server-side locked.
    demo_mode: bool = Field(default_factory=lambda: os.getenv("DEMO_MODE", "true").lower() == "true")
    demo_workspace_write_limit: int = Field(
        default_factory=lambda: int(os.getenv("DEMO_WORKSPACE_WRITES_PER_HOUR", "30"))
    )
    demo_global_write_limit: int = Field(
        default_factory=lambda: int(os.getenv("DEMO_GLOBAL_WRITES_PER_HOUR", "240"))
    )
    demo_workspace_external_limit: int = Field(
        default_factory=lambda: int(os.getenv("DEMO_WORKSPACE_EXTERNAL_PER_HOUR", "5"))
    )
    demo_global_external_limit: int = Field(
        default_factory=lambda: int(os.getenv("DEMO_GLOBAL_EXTERNAL_PER_HOUR", "60"))
    )
    # Non-demo requests are accepted only after validating IAP's signed JWT for this audience
    # and mapping one of its immutable claims to a registered SentinelFleet user.
    iap_audience: str = Field(default_factory=lambda: os.getenv("IAP_AUDIENCE", ""))
    iap_user_map: str = Field(default_factory=lambda: os.getenv("IAP_USER_MAP", "{}"))
    max_upload_bytes: int = Field(default_factory=lambda: int(os.getenv("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024))))
    max_pdf_pages: int = Field(default_factory=lambda: int(os.getenv("MAX_PDF_PAGES", "25")))
    max_extracted_chars: int = Field(default_factory=lambda: int(os.getenv("MAX_EXTRACTED_CHARS", "500000")))
    enable_cloud_trace: bool = Field(default_factory=lambda: os.getenv("ENABLE_CLOUD_TRACE", "false").lower() == "true")
    circuit_breaker_max_loops: int = Field(default_factory=lambda: int(os.getenv("MAX_CONSECUTIVE_LOOPS", "5")))


settings = Settings()
