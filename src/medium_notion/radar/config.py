"""radar 設定ローダ — feeds.yml / interests.yml を読み込む"""

from dataclasses import dataclass, field

import yaml


@dataclass
class FeedSpec:
    """1 フィードの定義"""

    name: str
    url: str
    layer: str


@dataclass
class RadarConfig:
    """radar の動作設定（YAML 由来）"""

    feeds: list[FeedSpec] = field(default_factory=list)
    threshold: int = 7
    max_highlights: int = 8
    deepdive_max: int = 8  # 1 実行で深掘りする刺さる記事の上限（コスト防御）
    profile: list[str] = field(default_factory=list)


def load_radar_config(
    feeds_path: str = "feeds.yml",
    interests_path: str = "interests.yml",
) -> RadarConfig:
    """feeds.yml と interests.yml を読み込んで RadarConfig を返す"""
    with open(feeds_path, encoding="utf-8") as f:
        feeds_raw = yaml.safe_load(f) or []
    feeds = [
        FeedSpec(name=item["name"], url=item["url"], layer=item["layer"])
        for item in feeds_raw
    ]

    with open(interests_path, encoding="utf-8") as f:
        interests_raw = yaml.safe_load(f) or {}

    return RadarConfig(
        feeds=feeds,
        threshold=int(interests_raw.get("threshold", 7)),
        max_highlights=int(interests_raw.get("max_highlights", 8)),
        deepdive_max=int(interests_raw.get("deepdive_max", 8)),
        profile=list(interests_raw.get("profile", [])),
    )
