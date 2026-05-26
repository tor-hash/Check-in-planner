import os
from pathlib import Path
from urllib.parse import ParseResult, parse_qsl, urlparse

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


def database_config_from_url() -> dict:
    db_url = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
    parsed: ParseResult = urlparse(db_url)
    if parsed.scheme in {"postgres", "postgresql"}:
        # Preserve query-string params such as sslmode=require.
        opts = dict(parse_qsl(parsed.query, keep_blank_values=True))
        return dj_database_url.parse(db_url, conn_max_age=600, ssl_require=opts.get("sslmode") == "require")

    parsed = urlparse(db_url)
    if parsed.scheme in {"sqlite", "sqlite3"}:
        db_path = parsed.path.lstrip("/") or "db.sqlite3"
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": str(BASE_DIR / db_path)}
    raise ValueError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")


ENVIRONMENT = os.getenv("DJANGO_ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT == "production"
IS_STAGING = ENVIRONMENT == "staging"

DEBUG = env_bool("DJANGO_DEBUG", not (IS_STAGING or IS_PRODUCTION))
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "" if (IS_STAGING or IS_PRODUCTION) else "dev-only-change-me")
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS", "")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "social_django",
    "apps.accounts",
    "apps.planner",
    "apps.onboarding",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates", REPO_ROOT],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "social_django.context_processors.backends",
                "social_django.context_processors.login_redirect",
                "apps.planner.context_processors.app_shell",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {"default": database_config_from_url()}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/Copenhagen"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "planner:home"
LOGOUT_REDIRECT_URL = "login"

AUTHENTICATION_BACKENDS = (
    "social_core.backends.google.GoogleOAuth2",
    "django.contrib.auth.backends.ModelBackend",
)

SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = os.getenv("GOOGLE_OAUTH2_KEY", "")
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = os.getenv("GOOGLE_OAUTH2_SECRET", "")
SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.events",
]
# access_type=offline + prompt=consent are required to receive a refresh_token
# from Google. social-auth's load_extra_data step then persists it on
# UserSocialAuth.extra_data["refresh_token"], which our credentials helper
# reads to mint short-lived access tokens server-side.
SOCIAL_AUTH_GOOGLE_OAUTH2_AUTH_EXTRA_ARGUMENTS = {
    "prompt": "consent",
    "access_type": "offline",
    "include_granted_scopes": "true",
}
SOCIAL_AUTH_GOOGLE_OAUTH2_WHITELISTED_DOMAINS = [os.getenv("GOOGLE_WORKSPACE_DOMAIN", "blackcapitaltechnology.com")]
# Per-email allowlist. When set, only these exact addresses can sign in;
# when empty/unset, we fall back to the domain-only check above. Useful for
# locking the app down to "just these 8 people" without giving every employee
# in the workspace access. Comma-separated, case-insensitive.
GOOGLE_WORKSPACE_ALLOWED_EMAILS = env_list("GOOGLE_WORKSPACE_ALLOWED_EMAILS", "")
# Persist refresh_token + expires_in alongside access_token.
SOCIAL_AUTH_GOOGLE_OAUTH2_EXTRA_DATA = [
    ("refresh_token", "refresh_token"),
    ("expires_in", "expires"),
    ("token_type", "token_type"),
]
GOOGLE_CALENDAR_TIMEZONE = os.getenv("GOOGLE_CALENDAR_TIMEZONE", "Europe/Copenhagen")
USE_GOOGLE_SHEET_JOURNAL = env_bool("USE_GOOGLE_SHEET_JOURNAL", False)

# Shared API key for the onboarding REST API. Leaving this blank disables
# the API entirely (endpoints respond 503) which is the safe default for
# dev and CI: no surprise exposure on a fresh deploy.
ONBOARDING_API_TOKEN = os.getenv("ONBOARDING_API_TOKEN", "")
SOCIAL_AUTH_PIPELINE = (
    "social_core.pipeline.social_auth.social_details",
    "social_core.pipeline.social_auth.social_uid",
    "social_core.pipeline.social_auth.auth_allowed",
    # Reject unauthorised callers BEFORE social_user/create_user so they
    # never get a Django row written.
    "apps.accounts.pipeline.ensure_workspace_domain",
    "apps.accounts.pipeline.ensure_allowed_email",
    "social_core.pipeline.social_auth.social_user",
    "social_core.pipeline.user.get_username",
    "social_core.pipeline.user.create_user",
    "social_core.pipeline.social_auth.associate_user",
    "social_core.pipeline.social_auth.load_extra_data",
    "social_core.pipeline.user.user_details",
    "apps.accounts.pipeline.ensure_manager_provisioned",
)

if IS_STAGING or IS_PRODUCTION:
    if not SECRET_KEY:
        raise ValueError("DJANGO_SECRET_KEY is required for staging/production.")
    if not os.getenv("DATABASE_URL"):
        raise ValueError("DATABASE_URL is required for staging/production.")
    if not SOCIAL_AUTH_GOOGLE_OAUTH2_KEY or not SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET:
        raise ValueError("GOOGLE_OAUTH2_KEY and GOOGLE_OAUTH2_SECRET are required for staging/production.")
    if not CSRF_TRUSTED_ORIGINS:
        raise ValueError("DJANGO_CSRF_TRUSTED_ORIGINS must be configured for staging/production.")

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", True)
    SESSION_COOKIE_HTTPONLY = True
    CSRF_COOKIE_HTTPONLY = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Booking events are emitted as structured JSON so they can be ingested by
# whatever observability stack is wired to stdout (Render's log drain by
# default). Other logs use the plain Django format.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "apps.planner.logging.JsonFormatter",
        },
        "plain": {
            "format": "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "plain",
        },
        "json_console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "apps.planner.services.bookings": {
            "handlers": ["json_console"],
            "level": "INFO",
            "propagate": False,
        },
        "apps.planner.google": {
            "handlers": ["json_console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
