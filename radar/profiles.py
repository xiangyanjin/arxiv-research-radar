"""Editable starter profiles; selecting a preset never creates research state."""
from __future__ import annotations

import json
from pathlib import Path

from .config import ConfigError, load_profile, validate_profile


PRESET_IDS = ("math-statistics", "ai-agents", "quant-finance", "astrophysics")
PRESET_DIR = Path(__file__).resolve().parent.parent / "config" / "presets"


def load_preset(identifier):
    if identifier not in PRESET_IDS:
        raise ConfigError(f"Unknown preset / 未知预设: {identifier}")
    return load_profile(PRESET_DIR / (identifier + ".json"))


def list_presets():
    result = []
    for identifier in PRESET_IDS:
        profile = load_preset(identifier)
        result.append({"id": identifier, "name": profile["name"],
                       "description": profile.get("description", ""),
                       "categories": profile["categories"],
                       "topics": [{"id": topic["id"], "label": topic["label"]} for topic in profile["topics"]]})
    return result


def init_profile(preset, output="config/profile.local.json", *, name=None, timezone=None):
    profile = load_preset(preset)
    if name is not None:
        profile["name"] = name
        profile["display"]["name"] = name
    if timezone is not None:
        profile["display"]["timezone"] = timezone
    profile = validate_profile(profile)
    content = json.dumps(profile, ensure_ascii=False, indent=2) + "\n"
    # Do not resolve the final component: a dangling output symlink must count
    # as an existing file too. Exclusive creation closes the check/write race.
    path = Path(output).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError:
        raise ConfigError(f"Profile already exists / 配置已存在，不会覆盖: {path}") from None
    return {"created": True, "path": str(path), "preset": preset,
            "name": profile["name"], "timezone": profile["display"]["timezone"]}
