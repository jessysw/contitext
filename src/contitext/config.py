"""Environment-only configuration for the Contitext service."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping

from contitext.auth import AuthenticationError, TokenStore


class ConfigurationError(RuntimeError):
    """Raised when required service configuration is missing or unsafe."""


@dataclass(frozen=True)
class Settings:
    database_url: str
    token_store: TokenStore | None

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        testing: bool = False,
    ) -> "Settings":
        values = os.environ if environ is None else environ
        database_key = "CONTITEXT_TEST_DATABASE_URL" if testing else "DATABASE_URL"
        database_url = values.get(database_key, "").strip()
        auth_tokens_json = values.get("CONTITEXT_AUTH_TOKENS", "").strip()

        missing = []
        if not database_url:
            missing.append(database_key)
        if not testing and not auth_tokens_json:
            missing.append("CONTITEXT_AUTH_TOKENS")
        if missing:
            raise ConfigurationError(
                "missing required environment configuration: " + ", ".join(missing)
            )
        if not database_url.startswith(("postgresql+psycopg://", "postgresql://")):
            raise ConfigurationError("Contitext requires a PostgreSQL database URL")
        if testing and "test" not in database_url.rsplit("/", 1)[-1].lower():
            raise ConfigurationError("test database URL must name a dedicated test database")

        token_store = None
        if auth_tokens_json:
            try:
                token_store = TokenStore.from_json(auth_tokens_json)
            except AuthenticationError as exc:
                raise ConfigurationError(str(exc)) from exc
        return cls(database_url=database_url, token_store=token_store)
