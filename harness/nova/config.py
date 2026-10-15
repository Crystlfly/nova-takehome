"""Configuration constants for Nova harness and audit engine."""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

# Automatically find and load .env from project root or workspace
def _load_env_file() -> None:
    try:
        # pyrefly: ignore [missing-import]
        from dotenv import load_dotenv
        # Look in current working directory and up to project root
        cwd = Path.cwd()
        for p in [cwd, cwd / "harness", Path(__file__).resolve().parent.parent.parent]:
            env_file = p / ".env"
            if env_file.is_file():
                load_dotenv(dotenv_path=env_file, override=False)
                break
    except ImportError:
        # Fallback manual parser if python-dotenv is not installed
        for p in [Path.cwd(), Path(__file__).resolve().parent.parent.parent]:
            env_file = p / ".env"
            if env_file.is_file():
                try:
                    with open(env_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith("#") and "=" in line:
                                k, v = line.split("=", 1)
                                k, v = k.strip(), v.strip().strip("'\"")
                                if k and k not in os.environ:
                                    os.environ[k] = v
                except Exception:
                    pass
                break

_load_env_file()

# ---- Anthropic Models ---------------------------------------------------------------------------------
ANTHROPIC_MODEL_SONNET = "claude-3-5-sonnet-20241022"
ANTHROPIC_MODEL_HAIKU = "claude-3-5-haiku-20241022"
ANTHROPIC_MODEL_DEFAULT = os.environ.get("ANTHROPIC_MODEL", ANTHROPIC_MODEL_SONNET)


# ---- Thresholds & Windows -----------------------------------------------------------------------------
# Outbound remedies of $5,000.00 or more on one invoice require human review
HUMAN_REVIEW_THRESHOLD_USD = Decimal("5000.00")

# Late-fee risk: unpaid invoices whose due date is 1-14 days after as_of (0 < due - as_of <= 14)
LATE_FEE_RISK_WINDOW_DAYS = 14

# Expiry: contracts whose operative date is 0-60 days after as_of (0 <= deadline - as_of <= 60)
EXPIRY_WINDOW_DAYS = 60

# Minimum non-whitespace characters for evidence quote
MIN_QUOTE_LENGTH = 12

# Default state directory for persistent data between batches
DEFAULT_STATE_DIR = ".state"
