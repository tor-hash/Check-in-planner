#!/usr/bin/env python
import os
import sys
from pathlib import Path


def _load_local_env() -> None:
    """Load backend/.env into os.environ for local dev.

    No-ops on Render/CI where the file is absent and real env vars are
    provided by the platform. Existing env vars always win over the file.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)


def main() -> None:
    _load_local_env()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
