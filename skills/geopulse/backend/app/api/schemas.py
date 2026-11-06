"""Versioned request contracts shared by the API and frontend."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(Model):
    email: str
    password: str


class PasswordIn(Model):
    current_password: str
    new_password: str = Field(min_length=10)


class ProjectIn(Model):
    client_name: str
    name: str
    category: str = ""
    market: str = "CN"
    language: str = "zh-CN"
    timezone: str = "Asia/Shanghai"
    service_package: Literal["diagnosis", "coaching", "monitoring", "private"] = "diagnosis"


class SettingsIn(Model):
    settings: dict[str, Any]


class PromptSetIn(Model):
    name: str
    weights: dict[str, Any] = {}


class ItemsIn(Model):
    items: list[dict[str, Any]]
    redact: bool = False


class ScaffoldIn(Model):
    brand: str
    category: str
    competitors: list[str] = []
    market: str = "CN"


class StatusIn(Model):
    status: str
    reason: str = ""


class ItemReviewIn(Model):
    status: Literal["reviewed", "rejected", "draft"]
    eligibility: str | None = None


class EntityIn(Model):
    name: str
    role: Literal["primary", "competitor", "candidate"] = "competitor"
    entity_card: dict[str, Any] = {}
    logical_id: str | None = None
    allow_conflicts: bool = False
    review_reason: str = ""


class EntityReviewIn(Model):
    decision: Literal["confirmed", "rejected"]
    reason: str
    role: Literal["primary", "competitor"] | None = None


class WaveIn(Model):
    prompt_set_id: int
    label: str
    engine_ids: list[int]
    repeats: int = Field(default=3, ge=1, le=5)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=700, ge=100, le=8000)
    system_prompt: str | None = None
    use_judge: bool = True
    anchor_at: str | None = None
    stats: dict[str, Any] = {}


class ObservationRevisionIn(Model):
    entity_status: Literal["confirmed", "ambiguous", "wrong_entity", "unknown"]
    mentioned: bool
    depth: Literal["absent", "mentioned", "described", "recommended"]
    sentiment: Literal["positive", "neutral", "negative", "unknown"]
    top_choice: bool = False
    evidence: str = ""
    reason: str
    arbitrate: bool = False


class OpportunityReviewIn(Model):
    decision: Literal["eligibility_pending", "confirmed", "rejected"]
    eligibility: Literal["eligible", "client_confirmed"] | None = None
    business_value: float = Field(default=3, ge=1, le=5)
    executability: float = Field(default=3, ge=1, le=5)
    reason: str = ""


class ActionIn(Model):
    title: str
    geo_step: int = Field(ge=1, le=7)
    owner: str = ""
    reviewer: str = ""
    target_url: str = ""
    artifact_version: str = "v1"
    target_wave_id: int | None = None


class ActionStatusIn(Model):
    status: str
    reason: str = ""
    published_at: str | None = None
    published_url: str | None = None
    artifact_version: str | None = None
    target_wave_id: int | None = None


class ReportIn(Model):
    wave_ids: list[int]


class EngineIn(Model):
    name: str
    vendor: str
    kind: Literal["demo", "openai_compat", "kimi_search"]
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    mode: Literal["memory", "search"] = "memory"
    measurement_target: Literal["provider_api", "consumer_web", "consumer_app"] = "provider_api"
    region: str = ""
    cost_rule: dict[str, Any] = {}
    timeout: int = Field(default=60, ge=1, le=300)
    rate_limit: float = Field(default=12, gt=0, le=600)
    enabled: bool = True


class HealthCheckIn(Model):
    confirm: bool = False


class UserIn(Model):
    email: str
    password: str = Field(min_length=10)


class MembershipIn(Model):
    user_id: int
    role: Literal["admin", "analyst", "reviewer", "viewer"]


class ScheduleIn(Model):
    wave_id: int
    scheduled_at: str


class EventIn(Model):
    event_at: str
    kind: str
    description: str
    source: str = ""


class WorkLogIn(Model):
    hours: float = Field(ge=0, le=24)
    kind: str
    note: str = ""
