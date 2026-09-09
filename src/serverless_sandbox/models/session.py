"""Session management data models.

注意：Session 管理为 SDK 扩展功能，阿里云官方文档中未定义此概念。
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SessionConfig(BaseModel):
    """Configuration for a session."""

    name: str
    description: str = ""
    sandbox_template: str = "base"
    auto_connect: bool = True
    ttl: int = Field(
        default=86400, ge=0, description="Session TTL in seconds, 0=infinite"
    )
    envs: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, str] = Field(default_factory=dict)


class SessionInfo(BaseModel):
    """Information about a persisted session."""

    session_id: str = Field(default="", alias="sessionId")
    name: str
    sandbox_id: str | None = Field(default=None, alias="sandboxId")
    template: str = "base"
    api_url: str = Field(default="", alias="apiUrl")
    domain: str = ""
    envd_access_token: str = Field(default="", alias="envdAccessToken")
    status: str = "active"
    created_at: datetime | None = Field(default=None, alias="createdAt")
    last_connected: datetime | None = Field(default=None, alias="lastConnected")
    metadata: dict[str, str] = Field(default_factory=dict)
    config: SessionConfig | None = None

    model_config = {"populate_by_name": True}
