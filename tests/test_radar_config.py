import textwrap

from medium_notion.radar.config import load_radar_config, RadarConfig, FeedSpec


def test_load_radar_config_parses_feeds_and_interests(tmp_path):
    feeds = tmp_path / "feeds.yml"
    feeds.write_text(textwrap.dedent("""\
        - {name: "Anthropic News", url: "https://a.example/rss", layer: "一次情報"}
        - {name: "a16z", url: "https://b.example/feed", layer: "VC"}
    """))
    interests = tmp_path / "interests.yml"
    interests.write_text(textwrap.dedent("""\
        threshold: 7
        max_highlights: 8
        profile:
          - "AI 時代の EM"
          - "組織の構造変化"
    """))

    cfg = load_radar_config(str(feeds), str(interests))

    assert isinstance(cfg, RadarConfig)
    assert cfg.threshold == 7
    assert cfg.max_highlights == 8
    assert cfg.profile == ["AI 時代の EM", "組織の構造変化"]
    assert cfg.feeds == [
        FeedSpec(name="Anthropic News", url="https://a.example/rss", layer="一次情報"),
        FeedSpec(name="a16z", url="https://b.example/feed", layer="VC"),
    ]


def test_load_radar_config_defaults_when_optional_missing(tmp_path):
    feeds = tmp_path / "feeds.yml"
    feeds.write_text('- {name: "X", url: "https://x.example/rss", layer: "Substack"}\n')
    interests = tmp_path / "interests.yml"
    interests.write_text("profile:\n  - \"何か\"\n")

    cfg = load_radar_config(str(feeds), str(interests))

    assert cfg.threshold == 7
    assert cfg.max_highlights == 8
    assert len(cfg.feeds) == 1
