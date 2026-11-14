import json
from datetime import datetime, timezone

from shorts import stocks


def test_compliance_catches_advice_and_tickers():
    bad = ["研究發現散戶追高，建議買進大盤", "這檔是明牌", "$TSLA 被散戶追捧", "2330.TW 的成交量", "代號 2330",
           "現在進場剛好", "抄底的人通常…"]
    for text in bad:
        assert stocks.compliance(text), text


def test_compliance_allows_research_talk():
    ok = ("台灣投資人賣出賺錢股票的速度，大約是賠錢股票的兩倍。研究用了 1995–1999 年台灣證交所全部交易，"
          "你也有過「等它漲回來再賣」的念頭嗎？")
    assert stocks.compliance(ok) == []
    assert stocks.compliance("字" * (stocks.MAX_BODY + 1))
    assert stocks.compliance("看這裡 https://x.y")


def test_full_text_fits_threads_limit():
    text = stocks.full_text("morning", "字" * stocks.MAX_BODY)
    assert text.startswith("📈 盤前心理學｜") and text.endswith(stocks.DISCLAIMER)
    assert len(text) <= 500


def test_posted_today_uses_taiwan_date():
    # 23:30 UTC on Nov 9 is already Nov 10 in Taiwan
    h = [{"slot": "morning", "posted": "2026-11-09T23:30:00+00:00"}]
    assert stocks.posted_today(h, "morning", datetime(2026, 11, 10, 2, tzinfo=timezone.utc))
    assert not stocks.posted_today(h, "evening", datetime(2026, 11, 10, 2, tzinfo=timezone.utc))
    assert not stocks.posted_today(h, "morning", datetime(2026, 11, 10, 17, tzinfo=timezone.utc))


def test_library_loads_as_papers():
    lib = stocks.library()
    assert len(lib) >= 11
    assert all(p.abstract and p.url.startswith("https://") for p in lib)
    assert len({p.id for p in lib}) == len(lib)


def test_pool_listing_marks_used_studies(monkeypatch):
    lib = stocks.library()[:2]
    h = [{"posted": "2026-11-09T00:00:00+00:00", "kind": "taiwan_data", "paper": {"id": lib[0].id}}]
    out = stocks.pool_listing(lib, h)
    assert "used 1x, last 2026-11-09, angles so far: taiwan_data" in out
    assert "not used yet" in out


def test_journal_and_analytics_include_stock_posts(monkeypatch, tmp_path):
    from shorts import analytics, config, journal

    rec = {"posted": "2026-11-10T00:00:00+00:00", "platform": "threads", "lang": "zh", "slot": "morning",
           "kind": "finding", "text": "📈 盤前心理學｜hi", "why": "x", "news": None, "id": "123",
           "url": "https://threads.com/p/1",
           "paper": {"id": "doi:x", "title": "T", "url": "https://doi.org/x", "venue": "V", "published": "2009",
                     "abstract": "A"}}
    (tmp_path / "stock_history.json").write_text(json.dumps([rec]), encoding="utf-8")
    monkeypatch.setattr(config, "DATA", tmp_path)
    monkeypatch.setattr(stocks, "HISTORY", tmp_path / "stock_history.json")
    assert any("股市篇" in ln for _, lines in journal.entries() for ln in lines)
    assert any(r["kind"] == "stock" and r["id"] == "123" for r in analytics._posts())


def test_noon_slot_and_daily_costs():
    assert stocks.full_text("noon", "x").startswith("🏭 產業前沿｜")
    h = [{"posted": "2026-11-10T00:00:00+00:00", "cost_usd": 0.05},
         {"posted": "2026-11-10T04:00:00+00:00", "cost_usd": 0.04},
         {"posted": "2026-11-10T17:00:00+00:00", "cost_usd": 0.03},   # Nov 11 in Taiwan
         {"posted": "2026-11-10T13:00:00+00:00"}]                      # posted before costs were kept
    assert stocks.daily_costs(h) == {"2026-11-10": 0.09, "2026-11-11": 0.03}


def test_noon_rules_ban_stock_picks():
    for text in ["這項技術的受惠股", "先進封裝概念股"]:
        assert stocks.compliance(text), text


def test_rested_skips_recent_and_worn_out_studies():
    from shorts.papers import Paper

    ps = [Paper(id=f"p{i}", title="t", abstract="a", venue="v", url="u", source="journal") for i in range(5)]
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    h = [{"posted": "2026-11-13T00:00:00+00:00", "paper": {"id": "p0"}},            # used yesterday
         *({"posted": "2026-09-01T00:00:00+00:00", "paper": {"id": "p1"}} for _ in range(3)),  # used 3 times
         {"posted": "2026-10-01T00:00:00+00:00", "paper": {"id": "p2"}}]            # rested long enough
    assert [p.id for p in stocks.rested(ps, h, now)] == ["p2", "p3", "p4"]
    # too few left: the least recently used come back
    assert [p.id for p in stocks.rested(ps[:2], h, now)] == ["p1", "p0"]
