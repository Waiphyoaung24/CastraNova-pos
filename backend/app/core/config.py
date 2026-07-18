import secrets
import warnings
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = secrets.token_urlsafe(32)
    # Access tokens are short-lived (15 min); the frontend transparently
    # refreshes them via /login/refresh-token while the user is active.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    # 12 hours. Rotated + re-set (max_age) on every /login/refresh-token call,
    # so this is a SLIDING inactivity window, not a fixed session length:
    # the clock resets on activity and only expires after 12h of silence.
    # This is the concrete mechanism behind PRD §8.3 (12h idle auto-logout).
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 12
    # Rate limiting is enabled by default; the test session disables it globally
    # and re-enables it only inside the dedicated rate-limit test.
    RATE_LIMIT_ENABLED: bool = True
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cookie_secure(self) -> bool:
        # Secure cookies require HTTPS; disable only for local dev over http.
        return self.ENVIRONMENT != "local"

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    POSTGRES_SERVER: str
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""
    # Least-privilege runtime role (hardening spec §4.2.3). When unset, the app
    # falls back to the admin (POSTGRES_USER) connection — pre-hardening behavior.
    POSTGRES_APP_USER: str = ""
    POSTGRES_APP_PASSWORD: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_APP_USER or self.POSTGRES_USER,
            password=self.POSTGRES_APP_PASSWORD or self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_ADMIN_DATABASE_URI(self) -> PostgresDsn:
        """Superuser connection — migrations, role management, test teardown."""
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    # Outbound push notification tokens (FR-018). None in dev/test; the LINE,
    # Viber + Telegram clients are mocked in tests. Never log these.
    # TELEGRAM_BOT_TOKEN goes in the request URL, not a header — see notify.py.
    LINE_CHANNEL_ACCESS_TOKEN: str | None = None
    VIBER_AUTH_TOKEN: str | None = None
    TELEGRAM_BOT_TOKEN: str | None = None
    # Public (not secret) -- used to build the t.me/<username>?start=<code>
    # connect deep link. The bot token above is what's actually sensitive.
    TELEGRAM_BOT_USERNAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        # NOTE: FIRST_SUPERUSER_PASSWORD is intentionally exempted from the
        # production "changethis" guard at the owner's explicit request, so a
        # default admin (admin@example.com / changethis) can be seeded in
        # production. This is a known security trade-off, not an oversight.
        if self.POSTGRES_APP_PASSWORD:
            self._check_default_secret(
                "POSTGRES_APP_PASSWORD", self.POSTGRES_APP_PASSWORD
            )

        return self


settings = Settings()  # type: ignore
