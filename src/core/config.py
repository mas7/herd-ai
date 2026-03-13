"""Loads config.yaml + env var overrides into frozen dataclasses."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _resolve_env_vars(value: str) -> str:
    """Replace ${VAR} or ${VAR:default} patterns with env values."""
    pattern = re.compile(r"\$\{(\w+)(?::([^}]*))?\}")

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default = match.group(2)
        return os.environ.get(var_name, default or match.group(0))

    return pattern.sub(replacer, value)


def _resolve_dict(data: dict) -> dict:
    """Recursively resolve env vars in a dict."""
    resolved = {}
    for key, value in data.items():
        if isinstance(value, str):
            resolved[key] = _resolve_env_vars(value)
        elif isinstance(value, dict):
            resolved[key] = _resolve_dict(value)
        elif isinstance(value, list):
            resolved[key] = [
                _resolve_env_vars(v) if isinstance(v, str) else v
                for v in value
            ]
        else:
            resolved[key] = value
    return resolved


@dataclass(frozen=True)
class ScoringWeights:
    skill_match: float = 0.30
    budget_fit: float = 0.25
    client_quality: float = 0.20
    competition: float = 0.15
    freshness: float = 0.10


@dataclass(frozen=True)
class FastScoreConfig:
    threshold: float = 40.0
    weights: ScoringWeights = field(default_factory=ScoringWeights)


@dataclass(frozen=True)
class DeepScoreConfig:
    model: str = "gpt-4o"
    temperature: float = 0.3
    min_final_score: float = 65.0


@dataclass(frozen=True)
class ScoringConfig:
    fast_score: FastScoreConfig = field(default_factory=FastScoreConfig)
    deep_score: DeepScoreConfig = field(default_factory=DeepScoreConfig)


@dataclass(frozen=True)
class UserProfile:
    name: str = ""
    skills: list[str] = field(default_factory=list)
    hourly_rate_min: float = 50.0
    hourly_rate_max: float = 150.0
    preferred_job_types: list[str] = field(
        default_factory=lambda: ["hourly", "fixed"]
    )
    experience_level: str = "expert"


@dataclass(frozen=True)
class SafetyConfig:
    human_in_the_loop: bool = True
    daily_submission_cap: int = 20
    daily_spend_cap_usd: float = 100.0
    min_confidence_auto_submit: float = 0.75


@dataclass(frozen=True)
class LLMConfig:
    default_model: str = "gpt-4o"
    fast_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"


@dataclass(frozen=True)
class DatabaseConfig:
    url: str = "sqlite+aiosqlite:///./data/herd.db"


@dataclass(frozen=True)
class HerdConfig:
    name: str = "Herd Agency"
    environment: str = "development"
    user_profile: UserProfile = field(default_factory=UserProfile)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    active_platforms: list[str] = field(default_factory=lambda: ["upwork"])


def load_config(path: str | Path = "config.yaml") -> HerdConfig:
    """Load config from YAML file with env var resolution."""
    config_path = Path(path)
    if not config_path.exists():
        return HerdConfig()

    with open(config_path) as f:
        raw = yaml.safe_load(f)

    resolved = _resolve_dict(raw)
    herd = resolved.get("herd", {})
    user = resolved.get("user_profile", {})
    scoring_raw = resolved.get("scoring", {})
    safety = resolved.get("safety", {})
    llm = resolved.get("llm", {})
    db = resolved.get("database", {})
    platforms = resolved.get("platforms", {})

    fast_weights = scoring_raw.get("fast_score", {}).get("weights", {})

    return HerdConfig(
        name=herd.get("name", "Herd Agency"),
        environment=herd.get("environment", "development"),
        active_platforms=platforms.get("active", ["upwork"]),
        user_profile=UserProfile(
            name=user.get("name", ""),
            skills=user.get("skills", []),
            hourly_rate_min=user.get("hourly_rate_min", 50.0),
            hourly_rate_max=user.get("hourly_rate_max", 150.0),
            preferred_job_types=user.get("preferred_job_types", []),
            experience_level=user.get("experience_level", "expert"),
        ),
        scoring=ScoringConfig(
            fast_score=FastScoreConfig(
                threshold=scoring_raw.get("fast_score", {}).get(
                    "threshold", 40.0
                ),
                weights=ScoringWeights(**fast_weights) if fast_weights else ScoringWeights(),
            ),
            deep_score=DeepScoreConfig(
                model=scoring_raw.get("deep_score", {}).get("model", "gpt-4o"),
                temperature=scoring_raw.get("deep_score", {}).get(
                    "temperature", 0.3
                ),
                min_final_score=scoring_raw.get("deep_score", {}).get(
                    "min_final_score", 65.0
                ),
            ),
        ),
        safety=SafetyConfig(
            human_in_the_loop=safety.get("human_in_the_loop", True),
            daily_submission_cap=safety.get("daily_submission_cap", 20),
            daily_spend_cap_usd=safety.get("daily_spend_cap_usd", 100.0),
            min_confidence_auto_submit=safety.get(
                "min_confidence_auto_submit", 0.75
            ),
        ),
        llm=LLMConfig(
            default_model=llm.get("default_model", "gpt-4o"),
            fast_model=llm.get("fast_model", "gpt-4o-mini"),
            embedding_model=llm.get("embedding_model", "text-embedding-3-small"),
        ),
        database=DatabaseConfig(
            url=db.get("url", "sqlite+aiosqlite:///./data/herd.db"),
        ),
    )
