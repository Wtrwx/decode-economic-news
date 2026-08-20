#!/usr/bin/env python3
"""Offline tests for deterministic evidence and signal logic."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from build_evidence_pack import build_pack
from build_browser_news_source import canonicalize_url, normalize_capture
from build_news_coverage import build_collection_coverage, build_coverage
from build_prediction_brief import build_brief
from build_recommendation import build_recommendation
from auto_review_research import build_outcome, load_history_series
from backtest_selector import run_backtest
from backtest_sector_signal import run_signal_backtest
from backtest_trade_timing import run_timing_backtest
from build_a_share_outlook_plan import build_plan as build_a_share_outlook_plan
from compute_cross_market_signal import _aligned_prior_pairs, compute_signal as compute_cross_market_signal
from compute_market_mood import compute_market_mood
from compute_news_reaction import compute_news_reaction
from compute_text_signals import compute_text_signals
from compute_topic_heat import compute_topic_heat
from compute_trade_timing import compute_timing
from evidence_core import atomic_write_json, load_json, safe_proxy_url, safe_url
from fetch_price_history import market_prefix, parse_tencent_payload
from fetch_clinical_trials import normalize_studies
from fetch_cross_market_history import normalize_proxy_url as normalize_cross_market_proxy, parse_chart, planned_assets
from fetch_gdelt_news import normalize_articles, normalize_proxy_url
from fetch_newsnook_news import parse_payload as parse_newsnook_payload, validate_api_base as validate_newsnook_api_base
from fetch_official_feed import parse_feed
from fetch_sec_filings import normalize_filings, resolve_ticker
from fetch_sector_universe import DEFAULT_PRESETS, build_universe
from forecast_sector import forecast
from finalize_prediction_brief import finalize_brief
from install import ignored_names, install as install_skill_bundle, validate_skill as validate_installed_skill
from list_browser_news_sites import build_plan, load_registry, select_sites
from research_journal import (
    add_review,
    compare_runs,
    journal_stats,
    list_runs,
    load_reviews,
    load_run,
    review_queue,
    save_run,
    verify_archive,
)
from select_stocks import rank_candidates
from validate_evidence import validate_document
from validate_prediction import validate_prediction_documents


class EvidenceCoreTests(unittest.TestCase):
    def test_safe_url_redacts_credentials(self) -> None:
        result = safe_url("https://example.test/data?series=x&api_key=secret&token=hidden")
        self.assertNotIn("secret", result)
        self.assertNotIn("hidden", result)
        self.assertIn("REDACTED", result)

    def test_safe_proxy_url_redacts_user_information(self) -> None:
        result = safe_proxy_url("socks5://user:password@127.0.0.1:1080/")
        self.assertEqual(result, "socks5://REDACTED@127.0.0.1:1080/")
        self.assertNotIn("user", result)
        self.assertNotIn("password", result)


class InstallationTests(unittest.TestCase):
    @staticmethod
    def _dependency(root: Path, version: str = "3.3.0") -> Path:
        target = root / "a-stock-data"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text(
            "---\n"
            "name: a-stock-data\n"
            "description: Test A-share dependency\n"
            f"version: {version}\n"
            "---\n\n# Test dependency\n",
            encoding="utf-8",
        )
        return target

    def test_installer_requires_and_copies_a_stock_data_first(self) -> None:
        skill_root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dependency = self._dependency(root / "source")
            codex_home = root / "codex-home"
            result = install_skill_bundle(
                codex_home=codex_home,
                dependency_source=dependency,
                skip_python_package_check=True,
                source_root=skill_root,
                manifest_path=skill_root / "skill-dependencies.json",
            )
            self.assertEqual(result["status"], "installed")
            self.assertTrue((codex_home / "skills" / "a-stock-data" / "SKILL.md").is_file())
            installed = codex_home / "skills" / "decode-economic-news"
            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertTrue((installed / "README.md").is_file())
            self.assertTrue((installed / "skill-dependencies.json").is_file())
            self.assertFalse((installed / "scripts" / "__pycache__").exists())

            second = install_skill_bundle(
                codex_home=codex_home,
                dependency_source=dependency,
                skip_python_package_check=True,
                source_root=skill_root,
                manifest_path=skill_root / "skill-dependencies.json",
            )
            self.assertTrue(second["skill"]["installation"]["backup"])
            self.assertTrue(Path(second["skill"]["installation"]["backup"]).is_dir())

    def test_missing_dependency_blocks_installation(self) -> None:
        skill_root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temp:
            isolated = Path(temp) / "isolated" / "decode-economic-news"
            isolated.mkdir(parents=True)
            (isolated / "SKILL.md").write_text(
                "---\nname: decode-economic-news\ndescription: Isolated installer test\n---\n",
                encoding="utf-8",
            )
            isolated_manifest = isolated / "skill-dependencies.json"
            isolated_manifest.write_text(
                (skill_root / "skill-dependencies.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "required skill a-stock-data"):
                install_skill_bundle(
                    codex_home=Path(temp) / "codex-home",
                    skip_python_package_check=True,
                    source_root=isolated,
                    manifest_path=isolated_manifest,
                )

    def test_old_dependency_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            dependency = self._dependency(Path(temp), version="3.2.9")
            with self.assertRaisesRegex(ValueError, "older than required"):
                validate_installed_skill(dependency, "a-stock-data", "3.3.0")

    def test_installer_excludes_secrets_and_runtime_data(self) -> None:
        ignored = ignored_names("/tmp/source", [".env", ".env.local", "work", ".cache", "x.pyc", "safe.json"])
        self.assertEqual(ignored, {".env", ".env.local", "work", ".cache", "x.pyc"})


class MarketMoodTests(unittest.TestCase):
    def test_complete_hot_snapshot(self) -> None:
        snapshot = {
            "schema": "market.snapshot/1",
            "market": "CN-A",
            "date": "20260808",
            "as_of": "2026-08-08T08:00:00+00:00",
            "breadth": {"advance_count": 4000, "decline_count": 1000},
            "limit_ecology": {
                "limit_up_count": 100,
                "broken_limit_count": 20,
                "limit_down_count": 5,
                "break_rate_pct": 16.667,
                "max_limit_height": 5,
                "continuation_rate_pct": 60,
            },
            "indices": [{"change_pct": 2.0}, {"change_pct": 1.0}],
            "warnings": [],
        }
        result = compute_market_mood(snapshot)
        self.assertEqual(result["schema"], "evidence.signal/1")
        self.assertGreater(result["values"]["score"], 60)
        self.assertEqual(result["coverage"], 1.0)

    def test_partial_snapshot_reweights_available_components(self) -> None:
        snapshot = {
            "schema": "market.snapshot/1",
            "market": "CN-A",
            "date": "20260808",
            "breadth": {"advance_count": 100, "decline_count": 100},
            "limit_ecology": {},
            "indices": [],
            "warnings": [],
        }
        result = compute_market_mood(snapshot)
        self.assertEqual(result["values"]["score"], 50.0)
        self.assertLess(result["coverage"], 0.75)


class TextSignalTests(unittest.TestCase):
    def test_interpretable_counts(self) -> None:
        result = compute_text_signals("根据官方公告，公司盈利增长20%，但仍存在风险，未来可能下调预期。")
        self.assertGreater(result["counts"]["positive"], 0)
        self.assertGreater(result["counts"]["negative"], 0)
        self.assertGreater(result["counts"]["uncertainty"], 0)
        self.assertGreater(result["values"]["evidence_density_per_1000"], 0)
        self.assertGreater(result["values"]["number_count"], 0)


class TopicHeatTests(unittest.TestCase):
    def test_attention_and_deduplication(self) -> None:
        now = datetime(2026, 8, 8, 8, tzinfo=timezone.utc)
        articles = [
            {"title": "新能源出口增长", "content": "", "source": "A", "published_at": (now - timedelta(minutes=20)).isoformat()},
            {"title": "新能源出口增长", "content": "转载", "source": "B", "published_at": (now - timedelta(minutes=10)).isoformat()},
            {"title": "新能源出口新数据", "content": "", "source": "B", "published_at": (now - timedelta(hours=3)).isoformat()},
            {"title": "新能源出口历史", "content": "", "source": "C", "published_at": (now - timedelta(days=3)).isoformat()},
        ]
        result = compute_topic_heat(articles, ["新能源", "出口"], now=now)
        self.assertEqual(result["values"]["last_24h_count"], 2)
        self.assertGreater(result["values"]["duplicate_ratio"], 0)
        self.assertGreater(result["values"]["score"], 50)


class NewSourceAdapterTests(unittest.TestCase):
    def test_newsnook_eastmoney_api_normalizes_attributed_content(self) -> None:
        source = {
            "publisher": "Eastmoney",
            "parser": "eastmoney-kx",
            "timezone": "Asia/Shanghai",
        }
        payload = (
            'var ajaxResult={"rc":1,"LivesList":[{'
            '"newsid":"202608203847620971",'
            '"title":"创新药ETF上涨",'
            '"digest":"截至13:35，创新药ETF上涨4.15%。",'
            '"showtime":"2026-08-20 13:38:24",'
            '"url_w":"http://finance.eastmoney.com/a/202608203847620971.html"'
            '}]};'
        ).encode("utf-8")
        articles = parse_newsnook_payload(payload, source)
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "创新药ETF上涨")
        self.assertTrue(articles[0]["url"].startswith("https://finance.eastmoney.com/"))
        self.assertIn("4.15%", articles[0]["summary"])

    def test_newsnook_rejects_html_error_page_for_json_source(self) -> None:
        source = {"publisher": "Cailian Press", "parser": "cls", "timezone": "UTC"}
        with self.assertRaises((RuntimeError, json.JSONDecodeError)):
            parse_newsnook_payload(b"<html>open the app</html>", source)

    def test_newsnook_api_base_rejects_credentials(self) -> None:
        with self.assertRaises(ValueError):
            validate_newsnook_api_base("https://user:secret@news.example.test")

    @staticmethod
    def _newsnook_document(*, sufficient: bool) -> dict:
        return {
            "schema": "evidence.source/1",
            "provider": {"id": "newsnook-api"},
            "retrieval": {"status": "fresh" if sufficient else "failed"},
            "collection": {
                "schema": "newsnook.api.collection/1",
                "query": "AI 芯片",
                "attempts": [
                    {
                        "source_id": "eastmoney-kx",
                        "outcome": "success" if sufficient else "failed",
                    }
                ],
                "gate": {
                    "all_source_outcomes_explicit": True,
                    "primary_sufficient": sufficient,
                    "passed": sufficient,
                    "fallback_reasons": [] if sufficient else ["no relevant API item"],
                },
            },
            "facts": [],
            "warnings": [],
        }

    def test_newsnook_primary_coverage_skips_browser_when_sufficient(self) -> None:
        coverage = build_collection_coverage(self._newsnook_document(sufficient=True))
        self.assertEqual(coverage["schema"], "news.collection.coverage/2")
        self.assertTrue(coverage["gate"]["passed"])
        self.assertFalse(coverage["gate"]["browser_fallback_required"])
        self.assertFalse(coverage["browser_fallback"]["provided"])

    def test_newsnook_failure_requires_and_accepts_targeted_browser_fallback(self) -> None:
        registry = load_registry()
        plan = build_plan(select_sites(registry, publisher="路透"), "AI 芯片")
        capture = {
            "schema": "browser.news.capture/1",
            "query": "AI 芯片",
            "captured_at": "2026-08-20T12:00:00+00:00",
            "attempts": [{"site_id": "reuters", "outcome": "opened_original"}],
            "pages": [
                {
                    "url": "https://www.reuters.com/world/test-story-2026-08-20/",
                    "title": "Test story",
                    "publisher": "Reuters",
                    "published_at": "2026-08-20T10:00:00+00:00",
                    "observed_at": "2026-08-20T12:00:00+00:00",
                    "capture_method": "visible_original_page",
                    "access_state": "open",
                    "visible_text": "Relevant visible text",
                }
            ],
        }
        missing = build_collection_coverage(self._newsnook_document(sufficient=False))
        self.assertFalse(missing["gate"]["passed"])
        self.assertTrue(missing["gate"]["browser_fallback_required"])
        recovered = build_collection_coverage(
            self._newsnook_document(sufficient=False),
            browser_plan=plan,
            browser_capture=capture,
        )
        self.assertTrue(recovered["gate"]["passed"])
        self.assertTrue(recovered["gate"]["browser_fallback_passed"])
        self.assertEqual(recovered["status"], "degraded")

    def test_browser_capture_normalizes_and_does_not_store_full_text(self) -> None:
        long_text = "Visible article text " * 200
        capture = {
            "schema": "browser.news.capture/1",
            "query": "semiconductor policy",
            "captured_at": "2026-08-08T12:00:00+00:00",
            "browser_surface": "in-app-browser",
            "pages": [
                {
                    "url": "https://Publisher.Test/news/item?utm_source=search&id=7#top",
                    "title": "Policy announcement",
                    "publisher": "Publisher Test",
                    "published_at": "2026-08-08T10:00:00+00:00",
                    "observed_at": "2026-08-08T12:00:00+00:00",
                    "capture_method": "visible_original_page",
                    "access_state": "signed_in",
                    "visible_text": long_text,
                    "cookies": "must be ignored",
                },
                {
                    "canonical_url": "https://publisher.test/news/item?id=7",
                    "title": "Duplicate canonical page",
                    "observed_at": "2026-08-08T12:01:00+00:00",
                    "capture_method": "search_result",
                },
            ],
        }
        result = normalize_capture(capture, max_excerpt_chars=120)
        self.assertEqual(len(result["facts"]), 1)
        fact = result["facts"][0]
        self.assertEqual(fact["source_url"], "https://publisher.test/news/item?id=7")
        self.assertEqual(fact["evidence_role"], "browser_observed_original")
        self.assertTrue(fact["content_observed"])
        self.assertEqual(fact["observation_scope"], "content_and_metadata")
        self.assertLessEqual(len(fact["excerpt"]), 120)
        self.assertNotIn("visible_text", fact)
        self.assertNotIn("cookies", json.dumps(result))
        self.assertTrue(fact["visible_text_sha256"])
        self.assertTrue(validate_document(result)["valid"])

    def test_browser_url_rejects_embedded_credentials(self) -> None:
        with self.assertRaises(ValueError):
            canonicalize_url("https://user:password@example.test/article")

    def test_corpus_backed_browser_site_plan(self) -> None:
        registry = load_registry()
        core = select_sites(registry, tiers={"core"})
        self.assertEqual({site["id"] for site in core}, {"reuters", "bloomberg", "financial-times"})
        self.assertTrue(all(site["corpus_files"] >= 15 for site in core))
        plan = build_plan(select_sites(registry, publisher="路透"), "AI 芯片")
        self.assertEqual(plan["schema"], "browser.news.search-plan/1")
        self.assertEqual(len(plan["queries"]), 1)
        self.assertEqual(plan["queries"][0]["query"], "site:reuters.com AI 芯片")
        self.assertTrue(plan["queries"][0]["must_attempt"])
        self.assertTrue(plan["coverage_requirements"]["silent_skip_is_failure"])
        self.assertNotIn("cookies", json.dumps(plan).lower())

    def test_core_media_coverage_requires_explicit_outcomes(self) -> None:
        registry = load_registry()
        plan = build_plan(select_sites(registry, tiers={"core"}), "AI 芯片")
        capture = {
            "schema": "browser.news.capture/1",
            "query": "AI 芯片",
            "captured_at": "2026-08-08T12:00:00+00:00",
            "attempts": [
                {"site_id": "reuters", "outcome": "opened_original"},
                {"site_id": "bloomberg", "outcome": "paywalled"},
                {"site_id": "financial-times", "outcome": "no_relevant_result"},
            ],
            "pages": [
                {
                    "url": "https://www.reuters.com/world/test-story-2026-08-08/",
                    "title": "Test story",
                    "publisher": "Reuters",
                    "published_at": "2026-08-08T10:00:00+00:00",
                    "observed_at": "2026-08-08T12:00:00+00:00",
                    "capture_method": "visible_original_page",
                    "access_state": "open",
                    "visible_text": "Relevant visible text",
                }
            ],
        }
        coverage = build_coverage(plan, capture)
        self.assertTrue(coverage["gate"]["passed"])
        self.assertTrue(coverage["gate"]["reuters_attempted"])
        self.assertEqual(coverage["gate"]["opened_original_pages"], 1)

        capture["attempts"] = capture["attempts"][:2]
        incomplete = build_coverage(plan, capture)
        self.assertFalse(incomplete["gate"]["passed"])
        self.assertIn("financial-times", incomplete["gate"]["missing_publishers"])

        capture["pages"] = []
        capture["attempts"] = [
            {"site_id": "reuters", "outcome": "search_results_only"},
            {"site_id": "bloomberg", "outcome": "paywalled"},
            {"site_id": "financial-times", "outcome": "no_relevant_result"},
        ]
        unresolved = build_coverage(plan, capture)
        self.assertFalse(unresolved["gate"]["passed"])
        self.assertIn("reuters", unresolved["gate"]["unresolved_publishers"])

    def test_gdelt_normalizes_discovery_not_article_truth(self) -> None:
        facts = normalize_articles(
            {
                "articles": [
                    {
                        "url": "https://publisher.test/story",
                        "title": "Policy changed",
                        "seendate": "20260808T120000Z",
                        "domain": "publisher.test",
                        "language": "English",
                    }
                ]
            },
            {"retrieved_at": "2026-08-08T13:00:00+00:00", "source_url": "https://api.gdelt.test"},
        )
        self.assertEqual(facts[0]["evidence_role"], "discovery_lead")
        self.assertIn("indexed an article", facts[0]["claim"])
        self.assertEqual(facts[0]["period"], "2026-08-08")

    def test_gdelt_upgrades_socks_dns_to_proxy_side(self) -> None:
        result = normalize_proxy_url("socks5://user:password@127.0.0.1:1080/")
        self.assertEqual(result, "socks5h://user:password@127.0.0.1:1080/")

    def test_cross_market_proxy_and_chart_normalization(self) -> None:
        proxy = normalize_cross_market_proxy("socks5://user:password@127.0.0.1:1080/")
        self.assertEqual(proxy, "socks5h://user:password@127.0.0.1:1080/")
        meta, bars = parse_chart(
            {
                "chart": {
                    "result": [
                        {
                            "meta": {"symbol": "SOXX", "currency": "USD", "exchangeTimezoneName": "UTC"},
                            "timestamp": [1767225600, 1767312000],
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [100, 101], "close": [101, 102], "high": [102, 103],
                                        "low": [99, 100], "volume": [1000, 1100]
                                    }
                                ],
                                "adjclose": [{"adjclose": [100.5, 101.5]}],
                            },
                        }
                    ],
                    "error": None,
                }
            },
            "SOXX",
        )
        self.assertEqual(meta["currency"], "USD")
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[-1]["close"], 101.5)
        self.assertEqual(bars[-1]["raw_close"], 102.0)

    def test_cross_market_presets_cover_every_a_share_preset(self) -> None:
        root = Path(__file__).resolve().parent.parent / "references"
        cross = load_json(root / "cross-market-presets.json")
        sector = load_json(root / "sector-presets.json")
        self.assertEqual(set(cross["presets"]), set(sector["presets"]))
        assets = planned_assets(cross, "semiconductor", ["us", "kr"])
        self.assertEqual({item[1]["symbol"] for item in assets}, {"SPY", "069500.KS", "SOXX", "091160.KS"})

    def test_sec_ticker_and_recent_filing_normalization(self) -> None:
        mapping = {"fields": ["cik", "name", "ticker", "exchange"], "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]]}
        self.assertEqual(resolve_ticker(mapping, "aapl"), "0000320193")
        payload = {
            "cik": "320193",
            "name": "Apple Inc.",
            "tickers": ["AAPL"],
            "exchanges": ["Nasdaq"],
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-26-000001"],
                    "form": ["8-K"],
                    "filingDate": ["2026-08-07"],
                    "reportDate": ["2026-08-07"],
                    "acceptanceDateTime": ["2026-08-07T16:00:00.000Z"],
                    "primaryDocument": ["event.htm"],
                    "primaryDocDescription": ["Current report"],
                }
            },
        }
        facts = normalize_filings(payload, forms={"8-K"}, limit=5, retrieved_at="2026-08-08T00:00:00+00:00")
        self.assertEqual(facts[0]["form"], "8-K")
        self.assertIn("Archives/edgar/data/320193", facts[0]["source_url"])

    def test_clinical_trial_normalization(self) -> None:
        studies = [
            {
                "protocolSection": {
                    "identificationModule": {"nctId": "NCT00000001", "briefTitle": "Test therapy"},
                    "statusModule": {"overallStatus": "RECRUITING", "lastUpdatePostDateStruct": {"date": "2026-08-01"}},
                    "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Test Sponsor"}},
                    "conditionsModule": {"conditions": ["Cancer"]},
                    "designModule": {"phases": ["PHASE2"], "studyType": "INTERVENTIONAL", "enrollmentInfo": {"count": 50}},
                    "armsInterventionsModule": {"interventions": [{"name": "Drug X"}]},
                },
                "hasResults": False,
            }
        ]
        facts = normalize_studies(studies, "2026-08-08T00:00:00+00:00")
        self.assertEqual(facts[0]["overall_status"], "RECRUITING")
        self.assertEqual(facts[0]["phases"], ["PHASE2"])

    def test_rss_and_atom_parser(self) -> None:
        rss = b"""<rss><channel><item><title>Official release</title><link>https://official.test/release</link><pubDate>Fri, 08 Aug 2026 12:00:00 GMT</pubDate><description>Details</description></item></channel></rss>"""
        facts = parse_feed(rss, publisher="Official Agency", retrieved_at="2026-08-08T13:00:00+00:00", limit=10)
        self.assertEqual(facts[0]["source_url"], "https://official.test/release")
        self.assertEqual(facts[0]["period"], "2026-08-08")


class CrossMarketSignalTests(unittest.TestCase):
    @staticmethod
    def _bars(multiplier: float, count: int = 100) -> list[dict]:
        rows = []
        price = 100.0
        for index in range(count):
            price *= multiplier
            rows.append(
                {
                    "date": (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)).date().isoformat(),
                    "open": price,
                    "close": price,
                    "high": price,
                    "low": price,
                    "volume": 1000 + index,
                }
            )
        return rows

    def test_prior_alignment_never_uses_same_date(self) -> None:
        pairs = _aligned_prior_pairs(
            {"2026-01-02": -1.0, "2026-01-03": -2.0},
            {"2026-01-01": 1.0, "2026-01-02": 99.0, "2026-01-03": 99.0},
        )
        self.assertEqual(pairs, [(-1.0, 1.0), (-2.0, 99.0)])

    def test_positive_foreign_impulse_rejected_by_a_share(self) -> None:
        a_history = {
            "schema": "market.history/1",
            "as_of": "2026-04-10",
            "series": [
                {"code": "512480", "name": "A semiconductor", "bars": self._bars(0.99)},
                {"code": "000300", "name": "CSI 300", "bars": self._bars(1.0)},
            ],
            "warnings": [],
        }
        cross_history = {
            "schema": "market.history/1",
            "requested_count": 4,
            "series": [
                {"code": "SPY", "market": "us", "role": "market_benchmark", "bars": self._bars(1.0)},
                {"code": "SOXX", "name": "SOXX", "market": "us", "role": "sector_proxy", "mapping_strength": 0.95, "bars": self._bars(1.01)},
                {"code": "069500.KS", "market": "kr", "role": "market_benchmark", "bars": self._bars(1.0)},
                {"code": "091160.KS", "name": "KODEX Semiconductor", "market": "kr", "role": "sector_proxy", "mapping_strength": 0.95, "bars": self._bars(1.01)},
            ],
            "universe_context": {
                "preset": "semiconductor",
                "market_benchmarks": {"us": {"symbol": "SPY"}, "kr": {"symbol": "069500.KS"}},
                "transmission_variables": ["HBM与存储价格"],
            },
            "warnings": [],
        }
        result = compute_cross_market_signal(a_history, cross_history, "512480", "000300")
        self.assertEqual(result["signal_type"], "cross_market_readthrough")
        self.assertEqual(result["values"]["a_share_acceptance"], "foreign_positive_a_rejected")
        self.assertGreater(result["values"]["foreign_impulse_5d_pct"], 1)
        self.assertEqual(result["inputs"]["timing_rule"], "foreign_close_date_strictly_before_a_share_date")
        self.assertEqual(result["coverage"], 1.0)


class AShareOutlookPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parent.parent / "references"
        cls.config = load_json(root / "a-share-instrument-presets.json")

    def test_588080_normal_branch_reads_local_expectations_before_deep_news(self) -> None:
        result = build_a_share_outlook_plan(
            self.config, "588080", "20d", "after_close", "unknown"
        )
        keys = [item["key"] for item in result["execution_order"]]
        self.assertEqual(keys[0], "identity_and_live_exposure")
        self.assertLess(keys.index("local_expectation_state"), keys.index("original_news_and_mechanism"))
        self.assertTrue(result["branch_warning"])
        instrument = result["instrument"]
        self.assertEqual(instrument["tracking_index"]["code"], "000688")
        self.assertEqual(instrument["exposure_model"]["mode"], "live_holdings_required")
        self.assertIn("semiconductor", instrument["cross_market"]["candidate_presets"])

    def test_confirmed_material_event_promotes_original_source(self) -> None:
        result = build_a_share_outlook_plan(
            self.config, "588080", "20d", "after_close", "confirmed_material"
        )
        keys = [item["key"] for item in result["execution_order"]]
        self.assertLess(keys.index("original_news_and_mechanism"), keys.index("local_expectation_state"))
        local = next(item for item in result["execution_order"] if item["key"] == "local_expectation_state")
        self.assertTrue(any("事件前" in task for task in local["tasks"]))

    def test_premarket_uses_foreign_prior_close_before_local_open_acceptance(self) -> None:
        result = build_a_share_outlook_plan(
            self.config, "588080", "5d", "premarket", "none"
        )
        keys = [item["key"] for item in result["execution_order"]]
        self.assertLess(keys.index("cross_market_readthrough"), keys.index("local_expectation_state"))
        cross = next(item for item in result["execution_order"] if item["key"] == "cross_market_readthrough")
        self.assertTrue(any("前一美股收盘" in task for task in cross["tasks"]))


class NewsReactionTests(unittest.TestCase):
    @staticmethod
    def _bars(event_multiplier: float) -> list[dict]:
        bars = []
        for index in range(12):
            price = 100.0 if index < 6 else 100.0 * event_multiplier
            bars.append(
                {
                    "date": (datetime(2026, 7, 27, tzinfo=timezone.utc) + timedelta(days=index)).date().isoformat(),
                    "open": price,
                    "close": price,
                    "high": price,
                    "low": price,
                    "volume": 2_000_000 if index == 6 else 1_000_000,
                }
            )
        return bars

    def test_positive_news_rejected_by_relative_price(self) -> None:
        event = {"schema": "news.event/1", "event_date": "2026-08-02", "headline_direction": "positive", "event_stage": "announced"}
        history = {
            "schema": "market.history/1",
            "series": [
                {"code": "AAA", "name": "Asset", "bars": self._bars(0.98)},
                {"code": "BBB", "name": "Benchmark", "bars": self._bars(1.0)},
            ],
        }
        result = compute_news_reaction(event, history, asset_code="AAA", benchmark_code="BBB")
        self.assertEqual(result["values"]["market_read"]["regime"], "positive_rejected")
        self.assertIn("high_event_volume", result["values"]["market_read"]["flags"])
        self.assertEqual(result["coverage"], 1.0)


class EvidencePackTests(unittest.TestCase):
    def test_pack_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.json"
            signal = root / "signal.json"
            atomic_write_json(
                source,
                {
                    "schema": "evidence.source/1",
                    "facts": [
                        {
                            "fact_id": "F001",
                            "claim": "GDP growth was 5 percent",
                            "value": 5,
                            "unit": "%",
                            "period": "2025",
                            "publisher": "Official publisher",
                            "source_url": "https://example.test/source",
                            "retrieved_at": "2026-08-08T08:00:00+00:00",
                        }
                    ],
                    "warnings": [],
                },
            )
            atomic_write_json(
                signal,
                {
                    "schema": "evidence.signal/1",
                    "signal_type": "test",
                    "method_version": "test/1",
                    "as_of": "2026-08-08T08:00:00+00:00",
                    "values": {"score": 50},
                    "inputs": {},
                    "coverage": 1.0,
                    "warnings": [],
                },
            )
            pack = build_pack("test topic", [source], [signal])
            self.assertTrue(pack["validation"]["valid"])
            self.assertEqual(len(pack["facts"]), 1)

    def test_numeric_fact_requires_unit(self) -> None:
        document = {
            "schema": "evidence.pack/1",
            "topic": "x",
            "facts": [
                {
                    "fact_id": "F1",
                    "claim": "x",
                    "value": 1,
                    "period": "2025",
                    "publisher": "p",
                    "source_url": "https://example.test",
                    "retrieved_at": "2026-08-08T08:00:00+00:00",
                }
            ],
        }
        report = validate_document(document)
        self.assertFalse(report["valid"])
        self.assertTrue(any("missing unit" in error for error in report["errors"]))


def synthetic_bars(rate: float, count: int = 260, volume_rate: float = 0.0) -> list[dict]:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bars = []
    price = 100.0
    for index in range(count):
        price *= 1.0 + rate
        date = (start + timedelta(days=index)).date().isoformat()
        bars.append({
            "date": date,
            "open": price * 0.998,
            "close": price,
            "high": price * 1.004,
            "low": price * 0.996,
            "volume": 1_000_000 * (1.0 + volume_rate * index),
        })
    return bars


def synthetic_history() -> dict:
    return {
        "schema": "market.history/1",
        "coverage": 1.0,
        "series_count": 4,
        "warnings": [],
        "series": [
            {"code": "515000", "name": "科技ETF", "bars": synthetic_bars(0.0010)},
            {"code": "000300", "name": "沪深300", "bars": synthetic_bars(0.0002)},
            {"code": "688001", "name": "强势样本", "bars": synthetic_bars(0.0020, volume_rate=0.002)},
            {"code": "688002", "name": "弱势样本", "bars": synthetic_bars(-0.0005)},
        ],
    }


def business_bars(rate: float, count: int = 360, volume_rate: float = 0.001) -> list[dict]:
    current = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = 100.0
    bars = []
    while len(bars) < count:
        if current.weekday() < 5:
            price *= 1.0 + rate
            index = len(bars)
            bars.append({
                "date": current.date().isoformat(),
                "open": price * 0.998,
                "close": price,
                "high": price * 1.0015,
                "low": price * 0.995,
                "volume": 1_000_000 * (1.0 + volume_rate * index),
            })
        current += timedelta(days=1)
    return bars


def timing_history() -> dict:
    return {
        "schema": "market.history/1",
        "warnings": [],
        "series": [
            {"code": "515000", "name": "科技ETF", "bars": business_bars(0.0005)},
            {"code": "688001", "name": "趋势样本", "bars": business_bars(0.0025)},
        ],
    }


class PriceHistoryTests(unittest.TestCase):
    def test_tencent_parser_and_index_prefix(self) -> None:
        payload = {
            "data": {
                "sh515000": {
                    "qfqday": [["2026-08-07", "1.0", "1.1", "1.2", "0.9", "1000"]],
                    "qt": {"sh515000": ["1", "科技ETF", "515000", "1.1"]},
                }
            }
        }
        name, _, bars = parse_tencent_payload(payload, "sh515000", "qfq")
        self.assertEqual(name, "科技ETF")
        self.assertEqual(bars[0]["close"], 1.1)
        self.assertEqual(market_prefix("000300"), "sh")
        self.assertEqual(market_prefix("SZ000001"), "sz")


class SectorPresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_json(DEFAULT_PRESETS)

    def test_all_presets_have_research_profile_benchmark_and_seed(self) -> None:
        presets = self.config["presets"]
        profiles = self.config["research_profiles"]
        self.assertGreaterEqual(len(presets), 17)
        for key, preset in presets.items():
            self.assertIn(preset["research_profile"], profiles, key)
            self.assertEqual(len(preset["benchmark"]["code"]), 6, key)
            self.assertEqual(len(preset["market_benchmark"]["code"]), 6, key)
            self.assertGreaterEqual(len(preset["seed_universe"]), 8, key)
            codes = [item["code"] for item in preset["seed_universe"]]
            self.assertEqual(len(codes), len(set(codes)), key)

    def test_every_preset_builds_a_seed_fallback_universe(self) -> None:
        for key, preset in self.config["presets"].items():
            result = build_universe(
                key, [], self.config, None, 0, 8, 80, seed_only=True
            )
            self.assertEqual(result["discovery_status"], "seed_fallback", key)
            self.assertEqual(result["benchmark"]["code"], preset["benchmark"]["code"], key)
            self.assertGreaterEqual(len(result["members"]), 8, key)

    def test_non_technology_brief_uses_sector_specific_logic(self) -> None:
        history = synthetic_history()
        sector = forecast(history, "515000", "000300")
        selection = rank_candidates(history, "515000", top_n=1)
        brief = build_brief("煤炭板块", "coal", sector, selection, presets=self.config)
        self.assertEqual(brief["sector_research_profile"]["key"], "cyclical-resource")
        self.assertIn("cost_curve", brief["sector_research_profile"]["valuation_framework"])
        self.assertTrue(any("成本曲线" in item for item in brief["research_questions"]))


class ForecastSelectionTests(unittest.TestCase):
    def test_multi_timeframe_timing_uses_prior_channel_and_next_session_backtest(self) -> None:
        history = timing_history()
        timing = compute_timing(history, ["688001"], "515000")
        asset = timing["values"]["assets"][0]
        self.assertIn(asset["state"], {"triggered", "retest"})
        self.assertTrue(asset["breakout"]["close_breakout_20d"])
        self.assertLess(asset["breakout"]["prior_20d_high"], asset["timeframes"]["daily"]["close"])
        diagnostic = run_timing_backtest(
            history, ["688001"], "515000", horizon=5, cost_bps=10, slippage_bps=5
        )
        self.assertEqual(diagnostic["assets"][0]["gate"]["status"], "abstain")
        self.assertFalse(
            diagnostic["assets"][0]["gate"]["checks"]["predeclared_evaluation_start_supplied"]
        )
        evaluation_start = history["series"][1]["bars"][120]["date"]
        report = run_timing_backtest(
            history, ["688001"], "515000", horizon=5, cost_bps=10, slippage_bps=5,
            start=evaluation_start,
        )
        result = report["assets"][0]
        self.assertGreaterEqual(result["period"]["trades"], 20)
        self.assertEqual(result["gate"]["status"], "usable")
        self.assertTrue(all(item["entry_date"] > item["signal_date"] for item in result["trades"]))
        self.assertTrue(all(item["holding_sessions"] <= 5 for item in result["trades"]))
        incomplete = run_timing_backtest(
            history, ["688001"], "515000", horizon=300, cost_bps=10, slippage_bps=5,
            start=evaluation_start,
        )["assets"][0]
        self.assertEqual(incomplete["period"]["trades"], 0)
        self.assertGreater(incomplete["period"]["skipped_incomplete_horizon"], 0)

    def test_sector_forecast_and_selection(self) -> None:
        history = synthetic_history()
        result = forecast(history, "515000", "000300")
        self.assertEqual(result["signal_type"], "sector_trend_forecast")
        self.assertGreater(result["values"]["forecasts"]["20d"]["score"], 60)
        selection = rank_candidates(history, "515000", top_n=2)
        self.assertEqual(selection["values"]["candidates"][0]["code"], "688001")
        self.assertLessEqual(selection["coverage"], 1.0)

    def test_walk_forward_and_blogger_logic_brief(self) -> None:
        history = synthetic_history()
        backtest = run_backtest(history, "515000", horizon=5, top_n=1, step=10, cost_bps=10)
        self.assertGreater(backtest["period"]["evaluation_periods"], 0)
        self.assertGreater(backtest["metrics"]["mean_excess_return_pct"], 0)
        sector = forecast(history, "515000", "000300")
        selection = rank_candidates(history, "515000", top_n=1)
        brief = build_brief("科技板块", "technology", sector, selection, None, backtest)
        self.assertFalse(brief["publication_gate"]["ready"])
        self.assertIn("research_required", str(brief["candidate_theses"][0]))
        self.assertTrue(brief["blogger_logic"]["contradiction"])
        validation = validate_prediction_documents(sector, selection, backtest, brief)
        self.assertTrue(validation["valid"])
        publication = validate_prediction_documents(sector, selection, backtest, brief, publication=True)
        self.assertFalse(publication["valid"])
        self.assertTrue(any("research_required" in error or "publication gate" in error for error in publication["errors"]))

    def test_sector_signal_backtest_abstains_when_score_is_not_calibrated(self) -> None:
        result = run_signal_backtest(
            synthetic_history(), "515000", "000300", horizon=20, step=20, cost_bps=10
        )
        self.assertEqual(result["schema"], "model.signal-backtest/1")
        self.assertEqual(result["gate"]["status"], "abstain")
        self.assertFalse(result["gate"]["positive_score_monotonicity"])

    def test_prediction_brief_carries_cross_market_overlay(self) -> None:
        history = synthetic_history()
        sector = forecast(history, "515000", "000300")
        selection = rank_candidates(history, "515000", top_n=1)
        cross = {
            "schema": "evidence.signal/1",
            "signal_type": "cross_market_readthrough",
            "as_of": "2026-08-07",
            "coverage": 1.0,
            "values": {
                "a_share_acceptance": "foreign_positive_a_rejected",
                "foreign_impulse_5d_pct": 2.5,
                "market_impulses": {"us": {"regime_5d": "positive"}, "kr": {"regime_5d": "positive"}},
                "transmission_variables": ["AI资本开支"],
            },
            "warnings": ["descriptive overlay"],
        }
        brief = build_brief("科技板块", "technology", sector, selection, cross_market=cross)
        overlay = brief["quantitative_layer"]["cross_market_overlay"]
        self.assertTrue(overlay["provided"])
        self.assertEqual(overlay["acceptance"], "foreign_positive_a_rejected")
        self.assertTrue(brief["publication_gate"]["has_cross_market_overlay"])
        self.assertIn("descriptive overlay", brief["warnings"])

    def test_completed_research_can_produce_conditional_buy(self) -> None:
        history = synthetic_history()
        sector = forecast(history, "515000", "000300")
        selection = rank_candidates(history, "515000", top_n=1)
        backtest = run_backtest(history, "515000", horizon=5, top_n=1, step=5, cost_bps=10)
        facts = [
            {
                "fact_id": f"F00{index}",
                "claim": f"verified supporting fact {index}",
                "period": "2025",
                "publisher": "Official publisher",
                "source_url": f"https://example.test/fact-{index}",
                "retrieved_at": "2026-08-08T08:00:00+00:00",
            }
            for index in range(1, 4)
        ]
        evidence_pack = {"schema": "evidence.pack/1", "topic": "technology", "facts": facts, "signals": [], "warnings": []}
        news_coverage = {
            "schema": "browser.news.coverage/1",
            "status": "complete",
            "gate": {"passed": True, "opened_original_pages": 1},
            "warnings": [],
        }
        signal_backtest = {
            "schema": "model.signal-backtest/1",
            "current_score": 70,
            "current_bucket": ">=70",
            "gate": {"status": "usable"},
            "warnings": [],
        }
        trade_timing = {
            "schema": "evidence.signal/1",
            "signal_type": "trade_timing",
            "values": {
                "assets": [{
                    "code": "688001",
                    "state": "triggered",
                    "as_of": "2026-08-07",
                    "coverage": 1.0,
                    "timeframes": {"daily": {"close": 120.0}},
                    "risk": {
                        "technical_stop_reference": 110.4,
                        "risk_distance_pct": 8.0,
                        "upside_review_reference_2r": 139.2,
                        "execution_clock": "signal_at_close_earliest_execution_next_session",
                    },
                    "entry_condition": "下一交易日核验价格与流动性后分批",
                }],
            },
        }
        timing_backtest = {
            "schema": "model.timing-backtest/1",
            "settings": {
                "start": "2022-01-01",
                "usable_gate_requires_predeclared_start": True,
                "terminal_incomplete_horizons": "excluded",
            },
            "assets": [{
                "code": "688001",
                "period": {"trades": 32},
                "gate": {"status": "usable"},
            }],
        }
        brief = build_brief(
            "科技板块", "technology", sector, selection, evidence_pack, backtest,
            news_coverage=news_coverage, signal_backtest=signal_backtest,
        )
        logic = brief["blogger_logic"]
        for actor in logic["actor_matrix"]:
            actor["goal"] = "扩大可持续收益"
            actor["constraint"] = "资本与需求约束"
            actor["observable_evidence"] = ["F001"]
        for field in (
            "surface_explanation", "structural_cause", "competing_explanation",
            "second_order_effect", "conditional_conclusion",
        ):
            logic[field] = "基于已核验事实的完整分析"
        logic["causal_chain"] = ["F001触发", "F002传导", "F003验证"]
        for thesis in brief["candidate_theses"]:
            for field in (
                "role_in_industry_chain", "expectation_gap", "catalyst", "who_benefits_and_why",
                "fundamental_confirmation", "competing_explanation", "second_order_effect", "invalidation_signal",
            ):
                thesis[field] = "基于F001-F003完成研究"
            thesis["supporting_fact_ids"] = ["F001", "F002", "F003"]
            thesis["fundamental_verdict"] = "pass"
            thesis["valuation_verdict"] = "fair"
            thesis["catalyst_status"] = "confirmed"
            thesis["risk_level"] = "medium"
        finalized = finalize_brief(
            brief, sector, selection, evidence_pack, backtest, news_coverage, signal_backtest
        )
        self.assertTrue(finalized["publication_gate"]["ready"])
        recommendation = build_recommendation(
            sector, selection, backtest, finalized, risk_profile="balanced", personalized=False,
            trade_timing=trade_timing, timing_backtest=timing_backtest,
        )
        self.assertEqual(recommendation["recommendations"][0]["action"], "条件买入")
        self.assertGreater(recommendation["recommendations"][0]["model_position_pct"], 0)
        self.assertEqual(recommendation["recommendations"][0]["timing_evidence"]["state"], "triggered")
        report = validate_prediction_documents(
            sector, selection, backtest, finalized, recommendation, publication=True
        )
        self.assertTrue(report["valid"], report)


class ResearchJournalTests(unittest.TestCase):
    def test_save_search_review_compare_and_verify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "journal"
            conclusion_path = root / "recommendation.json"
            evidence_path = root / "evidence.json"
            atomic_write_json(conclusion_path, {
                "schema": "stock.recommendation/1",
                "method_version": "conditional-recommendation/1.0",
                "as_of": "2026-08-10",
                "recommendations": [
                    {"code": "688001", "action": "观察等待"},
                    {"code": "688002", "action": "回避"},
                ],
                "warnings": ["test warning"],
            })
            atomic_write_json(evidence_path, {
                "schema": "evidence.pack/1",
                "topic": "半导体",
                "facts": [{"fact_id": "F001"}],
                "warnings": [],
            })
            run = save_run(
                archive,
                topic="半导体未来20日",
                as_of="2026-08-10",
                horizon="20d",
                conclusion=conclusion_path,
                artifacts=[("evidence-pack", evidence_path)],
                instruments=["688001", "688002"],
                tags=["semiconductor", "after-close"],
                stance="neutral",
                decision="观察等待",
                confidence="medium",
                thesis="产业景气尚未被本地价格确认",
                review_date="2026-09-07",
            )
            repeated = save_run(
                archive,
                topic="半导体未来20日",
                as_of="2026-08-10",
                horizon="20d",
                conclusion=conclusion_path,
                artifacts=[("evidence-pack", evidence_path)],
                instruments=["688001", "688002"],
                tags=["semiconductor", "after-close"],
                stance="neutral",
                decision="观察等待",
                confidence="medium",
                thesis="产业景气尚未被本地价格确认",
                review_date="2026-09-07",
            )
            self.assertEqual(run["run_id"], repeated["run_id"])
            self.assertEqual(run["artifact_schema_counts"]["stock.recommendation/1"], 1)
            self.assertEqual(
                run["conclusion"]["snapshot"]["action_counts"],
                {"观察等待": 1, "回避": 1},
            )

            matches = list_runs(archive, query="景气", instrument="688001", tag="semiconductor")
            self.assertEqual([item["run_id"] for item in matches], [run["run_id"]])
            review = add_review(
                archive,
                run["run_id"],
                observed_at="2026-09-07",
                thesis_status="partially_confirmed",
                realized_return_pct=3.5,
                benchmark_return_pct=1.0,
                decision_quality="good",
                note="产业数据改善但价格确认偏晚",
            )
            self.assertEqual(review["excess_return_pct"], 2.5)
            loaded, path = load_run(archive, run["run_id"])
            self.assertEqual(loaded["content_fingerprint"], run["content_fingerprint"])
            self.assertEqual(load_reviews(path)[0]["review_id"], review["review_id"])

            comparison = compare_runs(archive, [run["run_id"]])
            self.assertEqual(comparison["runs"][0]["latest_review"]["thesis_status"], "partially_confirmed")
            self.assertEqual(
                comparison["runs"][0]["artifact_snapshots"]["conclusion"]["schema"],
                "stock.recommendation/1",
            )
            stats = journal_stats(archive, group_by="tag")
            self.assertEqual(stats["groups"]["semiconductor"]["reviewed_runs"], 1)
            self.assertEqual(stats["groups"]["semiconductor"]["mean_excess_return_pct"], 2.5)
            verification = verify_archive(archive)
            self.assertTrue(verification["valid"], verification["errors"])
            self.assertEqual(verification["runs"], 1)
            self.assertEqual(verification["reviews"], 1)
            tampered = load_json(path)
            tampered["summary"]["thesis"] = "事后改写"
            atomic_write_json(path, tampered)
            self.assertFalse(verify_archive(archive)["valid"])

    def test_rejects_likely_secret_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = root / ".env"
            secret.write_text("API_KEY=hidden", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "secret"):
                save_run(
                    root / "journal", topic="test", as_of="2026-08-10",
                    horizon="event", conclusion=secret,
                )

    def test_due_queue_reads_conclusion_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "journal"
            conclusion = root / "conclusion.json"
            atomic_write_json(conclusion, {
                "schema": "prediction.brief/1",
                "as_of": "2026-08-10",
                "status": "research_scaffold_not_publication_ready",
                "publication_gate": {"ready": False},
                "warnings": [],
            })
            run = save_run(
                archive, topic="科技ETF未来3日", as_of="2026-08-10", horizon="3d",
                conclusion=conclusion, instruments=["515000"], stance="abstain",
                decision="观察等待", review_date="2026-08-14",
            )
            queue = review_queue(archive, as_of="2026-08-14")
            self.assertEqual(queue["counts"], {"due": 1})
            item = queue["items"][0]
            self.assertEqual(item["run_id"], run["run_id"])
            self.assertEqual(item["conclusion"]["snapshot"]["schema"], "prediction.brief/1")
            self.assertFalse(item["conclusion"]["snapshot"]["gate"]["ready"])

    def test_price_grounded_auto_review_builds_append_only_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "journal"
            conclusion = root / "conclusion.json"
            history = root / "history.json"
            outcome_path = root / "outcome.json"
            atomic_write_json(conclusion, {
                "schema": "stock.recommendation/1", "as_of": "2026-01-01",
                "recommendations": [{"code": "515000", "action": "条件买入"}], "warnings": [],
            })
            run = save_run(
                archive, topic="科技ETF未来3日", as_of="2026-01-01", horizon="3d",
                conclusion=conclusion, instruments=["515000"], stance="bullish",
                decision="条件买入", review_date="2026-01-05",
            )
            atomic_write_json(history, {
                "schema": "market.history/1", "as_of": "2026-01-06", "series": [
                    {"code": "515000", "name": "科技ETF", "bars": [
                        {"date": "2026-01-02", "close": 100},
                        {"date": "2026-01-03", "close": 102},
                        {"date": "2026-01-04", "close": 104},
                        {"date": "2026-01-05", "close": 106},
                    ]},
                    {"code": "000300", "name": "沪深300", "bars": [
                        {"date": "2026-01-02", "close": 100},
                        {"date": "2026-01-03", "close": 101},
                        {"date": "2026-01-04", "close": 101},
                        {"date": "2026-01-05", "close": 102},
                    ]},
                ], "warnings": [],
            })
            queue_item = review_queue(archive, as_of="2026-01-05")["items"][0]
            outcome = build_outcome(
                archive, run, queue_item, load_history_series([history]), benchmark_override="000300"
            )
            self.assertEqual(outcome["status"], "ready")
            self.assertEqual(outcome["evaluation"]["thesis_status"], "confirmed")
            self.assertEqual(outcome["evaluation"]["decision_quality"], "good")
            self.assertAlmostEqual(outcome["evaluation"]["realized_return_pct"], 6.0)
            atomic_write_json(outcome_path, outcome)
            review = add_review(
                archive, run["run_id"], observed_at=outcome["asset"]["exit_date"],
                thesis_status=outcome["evaluation"]["thesis_status"],
                realized_return_pct=outcome["evaluation"]["realized_return_pct"],
                benchmark_return_pct=outcome["evaluation"]["benchmark_return_pct"],
                decision_quality=outcome["evaluation"]["decision_quality"],
                note=outcome["evaluation"]["note"],
                artifacts=[("auto-review-outcome", outcome_path), ("outcome-history", history)],
                tags=["automatic-review"],
            )
            self.assertTrue(review["review_id"])
            self.assertEqual(verify_archive(archive)["reviews"], 1)

    def test_auto_review_blocks_when_horizon_bars_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "journal"
            conclusion = root / "conclusion.json"
            history = root / "history.json"
            atomic_write_json(conclusion, {"schema": "evidence.signal/1", "as_of": "2026-01-01"})
            run = save_run(
                archive, topic="测试", as_of="2026-01-01", horizon="3d",
                conclusion=conclusion, instruments=["515000"], stance="neutral",
                review_date="2026-01-05",
            )
            atomic_write_json(history, {
                "schema": "market.history/1", "series": [
                    {"code": "515000", "bars": [{"date": "2026-01-02", "close": 100}]}
                ],
            })
            item = review_queue(archive, as_of="2026-01-05")["items"][0]
            outcome = build_outcome(archive, run, item, load_history_series([history]))
            self.assertEqual(outcome["status"], "blocked")
            self.assertIn("1/4", outcome["reason"])


if __name__ == "__main__":
    unittest.main()
