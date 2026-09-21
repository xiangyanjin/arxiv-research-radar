"""Portable configuration, with private local overrides and readable errors."""
from __future__ import annotations

from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .ranking import _text


class ConfigError(ValueError):
    """A configuration problem suitable for display without a traceback."""


def resolve_path(value, root):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else Path(root) / path).resolve()


def profile_path(root, explicit=None):
    chosen = explicit or os.environ.get("ARXIV_RADAR_PROFILE")
    if chosen:
        return resolve_path(chosen, root)
    local = Path(root) / "config/profile.local.json"
    return local if local.exists() else Path(root) / "config/profile.json"


def data_path(root, explicit=None):
    return resolve_path(explicit or os.environ.get("ARXIV_RADAR_DATA_DIR") or "data", root)


def validate_profile(value):
    if not isinstance(value, dict):
        raise ConfigError("配置根节点必须是 JSON 对象 / profile must be a JSON object")
    result = deepcopy(value)

    def fail(field, message):
        raise ConfigError(f"配置字段 {field}: {message}")

    def string(field, item):
        if not isinstance(item, str) or not item.strip():
            fail(field, "需要非空字符串 / expected a non-empty string")

    def strings(field, items, allow_empty=False, categories=False):
        if not isinstance(items, list) or (not items and not allow_empty):
            fail(field, "需要字符串数组 / expected an array of strings")
        for item in items:
            string(field, item)
            if categories and not re.fullmatch(r"[a-z][a-z\-]*(?:\.[A-Za-z][A-Za-z\-]*)?", item):
                fail(field, f"无效的 arXiv 分类 / invalid arXiv category: {item}")

    def integer(field, item, low, high):
        if isinstance(item, bool) or not isinstance(item, int) or not low <= item <= high:
            fail(field, f"需要 {low}–{high} 之间的整数 / expected an integer")

    def terms(field, items, allow_empty=False):
        strings(field, items, allow_empty=allow_empty)
        for item in items:
            if not _text(item):
                fail(field, "规范化后必须含有字母或数字 / term must contain letters or numbers after normalization")

    result.setdefault("name", "arXiv Research Radar")
    string("name", result["name"])
    display = result.setdefault("display", {})
    if not isinstance(display, dict):
        fail("display", "需要 JSON 对象 / expected an object")
    display.setdefault("name", result["name"])
    display.setdefault("timezone", "UTC")
    string("display.name", display["name"])
    string("display.timezone", display["timezone"])
    try:
        ZoneInfo(display["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        fail("display.timezone", "需要有效的 IANA 时区，例如 UTC 或 Asia/Shanghai")

    strings("categories", result.get("categories"), categories=True)
    if "exclude_keywords" in result:
        terms("exclude_keywords", result["exclude_keywords"], allow_empty=True)
    topics = result.get("topics")
    if not isinstance(topics, list) or not topics:
        fail("topics", "至少配置一个研究方向 / configure at least one topic")
    seen = set()
    for index, topic in enumerate(topics):
        field = f"topics[{index}]"
        if not isinstance(topic, dict):
            fail(field, "需要 JSON 对象 / expected an object")
        string(field + ".id", topic.get("id"))
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", topic["id"]) or topic["id"] in seen:
            fail(field + ".id", "需要唯一的小写英文标识 / expected a unique lowercase identifier")
        seen.add(topic["id"])
        string(field + ".label", topic.get("label"))
        terms(field + ".keywords", topic.get("keywords"))
        strings(field + ".categories", topic.setdefault("categories", []), allow_empty=True, categories=True)
        if "anchors" in topic:
            terms(field + ".anchors", topic["anchors"])
        if "exclude_keywords" in topic:
            terms(field + ".exclude_keywords", topic["exclude_keywords"], allow_empty=True)
        weight = topic.setdefault("weight", 1.0)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or not 0 < weight <= 5:
            fail(field + ".weight", "需要大于 0 且不超过 5 的数 / expected a number in (0, 5]")
    for key in ("own_arxiv_ids", "self_author_names"):
        strings(key, result.setdefault(key, []), allow_empty=True)
    scan = result.setdefault("scan", {})
    if not isinstance(scan, dict):
        fail("scan", "需要 JSON 对象 / expected an object")
    limits = {"lookback_days": (14, 1, 90), "overlap_days": (3, 0, 90),
              "page_size": (1000, 1, 1000), "max_pages": (30, 1, 50),
              "timeout_seconds": (20, 1, 20), "retries": (1, 0, 1)}
    for key, (default, low, high) in limits.items():
        integer("scan." + key, scan.setdefault(key, default), low, high)
    integer("digest_limit", result.setdefault("digest_limit", 8), 1, 100)
    integer("minimum_score", result.setdefault("minimum_score", 20), 0, 100)
    return result


def load_profile(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as error:
        raise ConfigError(f"无法读取配置 / Cannot read profile {path}: {error}") from None
    except json.JSONDecodeError as error:
        raise ConfigError(f"配置 JSON 无效 / Invalid JSON in {path}, line {error.lineno}, column {error.colno}: {error.msg}") from None
    try:
        return validate_profile(value)
    except ConfigError as error:
        raise ConfigError(f"{path}: {error}") from None
