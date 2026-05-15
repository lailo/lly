"""User-tunable settings, persisted to `config.toml` via pydantic-settings."""

from __future__ import annotations

from enum import StrEnum

from pydantic import SecretStr, field_serializer
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)


class LogLevel(StrEnum):
    """How much detail lly writes to its JSON-Lines log file.

    `off` disables file logging entirely; the others map directly to the
    standard `logging` levels and gate everything at that level or higher.
    """

    OFF = "off"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"


class Settings(BaseSettings):
    """User-tunable config.

    Source precedence (highest → lowest) — pydantic-settings reads from:
      1. explicit kwargs (e.g. `Settings(refresh_interval_s=2.0)`)
      2. `LLY_*` env vars (e.g. `LLY_DEFAULT_PASSWORD=hunter2`)
      3. `~/Library/Application Support/lly/config.toml`
         (or whatever `lly.paths.settings_path()` resolves to)
      4. defaults declared below
    """

    model_config = SettingsConfigDict(env_prefix="LLY_", extra="ignore")

    default_password: SecretStr | None = None
    scan_timeout_s: float = 5.0
    refresh_interval_s: float = 5.0
    request_timeout_s: float = 4.0
    refresh_concurrency: int = 8
    # Errors land in the log file + stderr by default; bump to `info`/`debug`
    # for verbose tracing, or set `off` to silence everything.
    log_level: LogLevel = LogLevel.ERROR

    @field_serializer("default_password", when_used="always")
    def _ser_default_password(self, value: SecretStr | None) -> str | None:
        return value.get_secret_value() if value is not None else None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Late import — `lly.paths` resolves the path *now*, so test fixtures
        # that swap the config dir take effect on each fresh `Settings()`.
        from lly.paths import settings_path

        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings]
        path = settings_path()
        if path.exists():
            sources.append(TomlConfigSettingsSource(settings_cls, toml_file=path))
        return tuple(sources)
