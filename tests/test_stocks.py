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
    assert [p.id for p in stocks.rested(ps, h, now)] == ["p3", "p4", "p2"]  # unused first
    # too few left: the least recently used come back
    assert [p.id for p in stocks.rested(ps[:2], h, now)] == ["p1", "p0"]


def test_discover_adds_new_relevant_studies(monkeypatch, tmp_path):
    monkeypatch.setattr(stocks, "HISTORY", tmp_path / "none.json")
    lib = tmp_path / "lib.json"
    lib.write_text(json.dumps([{"id": "doi:10.1/old", "title": "Old Study", "abstract": "a", "venue": "J", "url": "https://doi.org/10.1/old"}]), encoding="utf-8")
    monkeypatch.setattr(stocks, "LIBRARY", lib)
    long = "Individual investors trading stock " * 20

    def w(i, title, abstract=long, venue="J", doi=None, cites=100):
        return {"paperId": f"s{i}", "title": title, "abstract": abstract, "venue": venue, "year": 2020,
                "citationCount": cites, "externalIds": {"DOI": doi} if doi else {}, "authors": [{"name": "A"}],
                "openAccessPdf": {"url": ""}}

    class Resp:
        status_code = 200

        def json(self):
            return {"data": [w(1, "Old Study", doi="10.1/OLD"),               # already in the library
                             w(2, "Short", abstract="stock investors"),        # abstract too short
                             w(3, "Survey", abstract=long + " questionnaire"),  # weak design
                             w(4, "Cells", abstract="protein folding " * 40),  # not about markets
                             w(5, "Good A", doi="10.1/a", cites=50),
                             w(6, "Good B", cites=300),
                             w(7, "Good C", cites=10)]}

    monkeypatch.setattr(stocks, "http", lambda *a, **k: Resp())
    monkeypatch.setattr(stocks, "_crossref", lambda topic: [])
    found = stocks.discover(datetime(2026, 11, 14, tzinfo=timezone.utc), topic="t")
    assert [f["title"] for f in found] == ["Good B", "Good A"]
    assert found[1]["id"] == "doi:10.1/a" and found[1]["url"] == "https://doi.org/10.1/a"
    assert found[0]["pdf_url"] is None and found[0]["found_by"] == "Semantic Scholar: t"
    saved = json.loads(lib.read_text(encoding="utf-8"))
    assert len(saved) == 3
    assert stocks.library()[0].title == "Good A"  # newest additions first


def test_discover_falls_back_to_crossref(tmp_path, monkeypatch):
    monkeypatch.setattr(stocks, "HISTORY", tmp_path / "none.json")
    lib = tmp_path / "lib.json"
    lib.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(stocks, "LIBRARY", lib)
    monkeypatch.setattr(stocks, "_s2", lambda topic: [])

    class Resp:
        status_code = 200

        def json(self):
            item = {"DOI": "10.1/X", "title": ["Retail Investors and Stock Returns"], "is-referenced-by-count": 80,
                    "abstract": "<jats:p>" + "We study how retail investor trading predicts stock returns. " * 10 + "</jats:p>",
                    "container-title": ["Journal of Finance"], "issued": {"date-parts": [[2020]]},
                    "author": [{"given": "A", "family": "B"}]}
            return {"message": {"items": [item, item | {"DOI": "10.1/Y", "is-referenced-by-count": 3}]}}

    monkeypatch.setattr(stocks, "http", lambda *a, **k: Resp())
    found = stocks.discover(topic="retail")
    assert [f["id"] for f in found] == ["doi:10.1/x"]
    assert "<" not in found[0]["abstract"] and found[0]["found_by"] == "Crossref: retail"
    assert found[0]["authors"] == ["A B"] and found[0]["published"] == "2020"


def test_retire_drops_worn_out_and_oldest(monkeypatch):
    monkeypatch.setattr(stocks, "LIBRARY_MAX", 3)
    lib = [{"id": f"p{i}", "title": f"T{i}"} for i in range(6)]
    history = [{"paper": {"id": "p5", "title": "T5"}}] * 3 + [{"paper": {"id": "p4", "title": "T4"}}]
    assert [p["id"] for p in stocks.retire(lib, history)] == ["p2", "p3", "p4"]
