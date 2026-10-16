import os
import pytest
from agents.collector.adapters.krisha import KrishaAdapter
from agents.collector.adapters.telegram import TelegramAdapter
from agents.collector.adapters.demo import DemoAdapter
from agents.collector.filter import check_relevance
from agents.collector.models import RawAd

def test_krisha_parser_sample():
    adapter = KrishaAdapter()
    with open("fixtures/krisha_sample.html", "r", encoding="utf-8") as f:
        html_content = f.read()

    ad = adapter.parse_html(html_content, url="https://krisha.kz/a/show/990001")
    assert ad is not None
    assert ad.platform == "krisha"
    assert "2-комнатная квартира" in ad.text
    assert "закрепим за вами квартиру" in ad.text
    assert "500 000" in ad.text

def test_telegram_parser_sample():
    adapter = TelegramAdapter()
    with open("fixtures/telegram_sample.html", "r", encoding="utf-8") as f:
        html_content = f.read()

    ads = adapter.parse_html(html_content, channel_name="astana_stroy_demo")
    assert len(ads) == 1
    ad = ads[0]
    assert ad.platform == "telegram"
    assert "@astana_stroy_demo" in ad.account
    assert "ЖК 'Есиль Ривер'" in ad.text
    assert "1 000 000 тг" in ad.text

def test_malformed_html_handling():
    krisha_adapter = KrishaAdapter()
    with open("fixtures/malformed.html", "r", encoding="utf-8") as f:
        html_content = f.read()

    # Must not throw an unhandled crash exception
    ad = krisha_adapter.parse_html(html_content, url="https://krisha.kz/a/show/malformed")
    assert ad is not None
    assert ad.platform == "krisha"

def test_demo_adapter_count():
    adapter = DemoAdapter(seed_filepath="seed/demo_ads.json")
    ads = adapter.fetch()
    assert len(ads) >= 12
    for ad in ads:
        assert ad.is_demo is True

def test_deduplication():
    ad1 = RawAd(
        id="ad1",
        platform="krisha",
        url="https://krisha.kz/a/show/100",
        text="  Продается КВАРТИРА в ЖК  ",
        is_demo=False
    )
    ad2 = RawAd(
        id="ad2",
        platform="krisha",
        url="https://krisha.kz/a/show/100 ",
        text="продается квартира в жк",
        is_demo=False
    )
    assert ad1.dedup_hash == ad2.dedup_hash

def test_relevance_filter():
    rel_text = "Продается квартира в строящемся ЖК, котлован"
    is_rel, reason = check_relevance(rel_text)
    assert is_rel is True

    irrel_text = "Продам авто Toyota Camry 2022 года"
    is_rel_2, reason_2 = check_relevance(irrel_text)
    assert is_rel_2 is False
    assert "No relevant keywords" in reason_2
