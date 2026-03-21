"""
Configuration management for Trade Journal.
Stores user settings in a JSON file alongside the database.
"""

import json
import os
from pathlib import Path

CONFIG_PATH = os.environ.get("TJ_CONFIG_PATH", str(Path(__file__).parent / "data" / "config.json"))

DEFAULTS = {
    "ibkr_token": "",
    "ibkr_query_id": "",
    "import_schedule": "manual",
    "tq_tickq_enabled": False,
    "tq_tickq_symbol": "",
}


def load_config() -> dict:
    """Load config from JSON file, merging with defaults."""
    config = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                saved = json.load(f)
            config.update(saved)
        except (json.JSONDecodeError, IOError):
            pass
    return config


def save_config(config: dict):
    """Save config to JSON file."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def get(key: str, default=None):
    """Get a single config value."""
    config = load_config()
    return config.get(key, default)


def set_value(key: str, value):
    """Set a single config value."""
    config = load_config()
    config[key] = value
    save_config(config)
