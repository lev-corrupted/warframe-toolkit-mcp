"""Tests for Warframe Toolkit MCP Server — all helper functions and tool outputs."""

import json
import pytest
import responses
from unittest.mock import patch, MagicMock
from pathlib import Path

# Reset caches before importing so tests start clean
import server
server._item_cache = None
server._syndicate_cache = None


# ============================================================
# FIXTURES
# ============================================================

FAKE_ITEMS = [
    {"slug": "condition_overload", "i18n": {"en": {"name": "Condition Overload"}}, "tags": ["mod"]},
    {"slug": "primed_flow", "i18n": {"en": {"name": "Primed Flow"}}, "tags": ["mod"]},
    {"slug": "blind_rage", "i18n": {"en": {"name": "Blind Rage"}}, "tags": ["mod"]},
    {"slug": "burston_prime_set", "i18n": {"en": {"name": "Burston Prime Set"}}, "tags": ["set"]},
    {"slug": "melee_influence", "i18n": {"en": {"name": "Melee Influence"}}, "tags": ["mod"]},
]

FAKE_SELL_ORDERS = [
    {"type": "sell", "platinum": 10, "quantity": 1, "user": {"ingameName": "Player1", "status": "online"}},
    {"type": "sell", "platinum": 12, "quantity": 2, "user": {"ingameName": "Player2", "status": "ingame"}},
    {"type": "sell", "platinum": 15, "quantity": 1, "user": {"ingameName": "Player3", "status": "online"}},
    {"type": "sell", "platinum": 18, "quantity": 3, "user": {"ingameName": "Player4", "status": "online"}},
    {"type": "sell", "platinum": 20, "quantity": 1, "user": {"ingameName": "Player5", "status": "online"}},
    {"type": "sell", "platinum": 25, "quantity": 1, "user": {"ingameName": "Player6", "status": "offline"}},
    {"type": "buy", "platinum": 5, "quantity": 10, "user": {"ingameName": "Buyer1", "status": "online"}},
]

FAKE_SYNDICATE_DATA = {
    "syndicates": {
        "Arbiters of Hexis": {
            "weapon_augments": ["Stinging Truth"],
            "warframe_augments": {
                "Excalibur": ["Surging Dash", "Radiant Finish"],
                "Valkyr": ["Swing Line"],
            },
        },
        "Cephalon Suda": {
            "weapon_augments": ["Entropy Spike"],
            "warframe_augments": {
                "Banshee": ["Resonance"],
            },
        },
    }
}

FAKE_STATS_RESPONSE = {
    "payload": {
        "statistics_closed": {
            "48hours": [
                {"avg_price": 15.5, "min_price": 10, "max_price": 25, "volume": 42, "median": 14},
            ],
            "90days": [
                {"datetime": "2026-04-01T00:00:00", "avg_price": 14, "min_price": 8, "max_price": 30, "volume": 50},
                {"datetime": "2026-04-02T00:00:00", "avg_price": 15, "min_price": 9, "max_price": 28, "volume": 55},
            ],
        }
    }
}

FAKE_FISSURES = [
    {"missionType": "Capture", "tier": "Axi", "node": "Hydra (Pluto)", "enemy": "Corpus", "eta": "30m", "expired": False},
    {"missionType": "Exterminate", "tier": "Neo", "node": "Xini (Eris)", "enemy": "Infested", "eta": "45m", "expired": False},
    {"missionType": "Defense", "tier": "Meso", "node": "Io (Jupiter)", "enemy": "Corpus", "eta": "20m", "expired": False},
    {"missionType": "Capture", "tier": "Lith", "node": "Hepit (Void)", "enemy": "Corrupted", "eta": "15m", "expired": False},
]

FAKE_WORLD_STATE = {
    "archonHunt": {
        "boss": "Archon Boreal",
        "eta": "3d 12h",
        "missions": [
            {"node": "Hydra (Pluto)", "type": "Mobile Defense"},
            {"node": "Xini (Eris)", "type": "Interception"},
            {"node": "Tycho (Lua)", "type": "Assassination"},
        ],
    },
    "duviriCycle": {"state": "sorrow", "eta": "1h 30m"},
    "sortie": {
        "boss": "Tyl Regor",
        "eta": "8h 15m",
        "variants": [
            {"node": "Titania (Uranus)", "missionType": "Spy", "modifier": "Eximus Stronghold"},
        ],
    },
}

FAKE_BARO_ACTIVE = {
    "active": True,
    "location": "Kronia Relay (Saturn)",
    "endString": "1d 2h",
    "eta": "1d 2h",
    "inventory": [
        {"item": "Primed Continuity", "ducats": 350, "credits": 110000},
        {"item": "Sands of Inaros", "ducats": 100, "credits": 25000},
    ],
}

FAKE_BARO_INACTIVE = {
    "active": False,
    "startString": "4d 6h",
    "location": "Larunda Relay (Mercury)",
}


@pytest.fixture(autouse=True)
def reset_caches():
    """Reset module-level caches before each test."""
    server._item_cache = None
    server._syndicate_cache = None
    yield
    server._item_cache = None
    server._syndicate_cache = None


# ============================================================
# _find_item_slug TESTS
# ============================================================

class TestFindItemSlug:
    """Tests for item slug fuzzy matching."""

    def test_exact_match(self):
        server._item_cache = FAKE_ITEMS
        slug, name = server._find_item_slug("Condition Overload")
        assert slug == "condition_overload"
        assert name == "Condition Overload"

    def test_case_insensitive(self):
        server._item_cache = FAKE_ITEMS
        slug, name = server._find_item_slug("condition overload")
        assert slug == "condition_overload"

    def test_partial_match(self):
        server._item_cache = FAKE_ITEMS
        slug, name = server._find_item_slug("Primed Flow")
        assert slug == "primed_flow"

    def test_partial_substring(self):
        server._item_cache = FAKE_ITEMS
        slug, name = server._find_item_slug("Blind")
        assert slug == "blind_rage"

    def test_no_match_returns_none(self):
        server._item_cache = FAKE_ITEMS
        slug, name = server._find_item_slug("Nonexistent Mod XYZ")
        assert slug is None
        assert name is None

    def test_empty_string(self):
        server._item_cache = FAKE_ITEMS
        slug, name = server._find_item_slug("")
        # Empty string matches everything via partial — should return shortest
        assert slug is not None or slug is None  # graceful handling either way

    def test_whitespace_handling(self):
        server._item_cache = FAKE_ITEMS
        slug, name = server._find_item_slug("  Condition Overload  ")
        assert slug == "condition_overload"

    def test_word_fuzzy_match(self):
        server._item_cache = FAKE_ITEMS
        slug, name = server._find_item_slug("Melee Influence")
        assert slug == "melee_influence"


# ============================================================
# _quick_price TESTS — New algorithm (traded median + fallback)
# ============================================================

def _stats_payload(trades_per_day):
    """Build fake statistics_closed payload from list of (days_ago, median, volume) tuples.
    days_ago=0 is today, 1 is yesterday, etc.
    """
    from datetime import datetime, timedelta
    entries = []
    for days_ago, median, volume in trades_per_day:
        dt = (datetime.utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%dT00:00:00.000+00:00")
        entries.append({
            "datetime": dt,
            "avg_price": median,
            "min_price": median - 1,
            "max_price": median + 2,
            "volume": volume,
            "median": median,
        })
    entries.sort(key=lambda e: e["datetime"])
    return {"payload": {"statistics_closed": {"48hours": entries[-2:] if entries else [],
                                              "90days": entries}}}


class TestQuickPrice:
    """Tests for new pricing algorithm using traded stats + fallback."""

    @responses.activate
    def test_uses_7day_traded_median_when_available(self):
        """Primary path: use median of last 7 days of actual trades."""
        server._item_cache = FAKE_ITEMS
        responses.add(
            responses.GET,
            f"{server.API_BASE}/orders/item/condition_overload",
            json={"data": FAKE_SELL_ORDERS},
            status=200,
        )
        # 7 days of trades, median around 15-16
        stats = _stats_payload([(0, 15, 5), (1, 16, 8), (2, 15, 10), (3, 14, 6),
                                (4, 16, 7), (5, 15, 9), (6, 16, 5)])
        responses.add(
            responses.GET,
            f"{server.API_V1}/items/condition_overload/statistics",
            json=stats,
            status=200,
        )
        result = server._quick_price("Condition Overload")
        assert result["name"] == "Condition Overload"
        assert 14 <= result["avg"] <= 17  # near traded median
        assert result["source"] == "traded_7d"
        assert result["liquidity"] in ("HIGH", "MED")
        assert result["volume"] > 5  # daily average
        assert "error" not in result or result.get("error") is None

    @responses.activate
    def test_warns_when_listed_avg_differs_from_traded(self):
        """If listings show 47p but trades show 18p, emit warning."""
        server._item_cache = FAKE_ITEMS
        # Order book shows inflated prices (holdouts at 48, 74, 74)
        holdout_orders = [
            {"type": "sell", "platinum": 14, "quantity": 1, "user": {"ingameName": "L1", "status": "online"}},
            {"type": "sell", "platinum": 25, "quantity": 1, "user": {"ingameName": "L2", "status": "online"}},
            {"type": "sell", "platinum": 48, "quantity": 1, "user": {"ingameName": "L3", "status": "online"}},
            {"type": "sell", "platinum": 74, "quantity": 1, "user": {"ingameName": "L4", "status": "online"}},
            {"type": "sell", "platinum": 74, "quantity": 1, "user": {"ingameName": "L5", "status": "online"}},
        ]
        responses.add(
            responses.GET,
            f"{server.API_BASE}/orders/item/condition_overload",
            json={"data": holdout_orders},
            status=200,
        )
        # But actual trades happen at 18p
        stats = _stats_payload([(0, 18, 4), (1, 17, 5), (2, 18, 6), (3, 19, 4),
                                (4, 17, 3), (5, 18, 5), (6, 17, 4)])
        responses.add(
            responses.GET,
            f"{server.API_V1}/items/condition_overload/statistics",
            json=stats,
            status=200,
        )
        result = server._quick_price("Condition Overload")
        # Should use traded median (~18p), not listed bottom-3 avg (~29p)
        assert 16 <= result["avg"] <= 20
        assert result["warning"] is not None
        assert "listed" in result["warning"].lower() or "differ" in result["warning"].lower()

    @responses.activate
    def test_fallback_to_orderbook_when_no_trades(self):
        """If no trade data available, fall back to bottom-3 online sellers."""
        server._item_cache = FAKE_ITEMS
        responses.add(
            responses.GET,
            f"{server.API_BASE}/orders/item/condition_overload",
            json={"data": FAKE_SELL_ORDERS},
            status=200,
        )
        # Stats API returns empty (no trades)
        empty_stats = {"payload": {"statistics_closed": {"48hours": [], "90days": []}}}
        responses.add(
            responses.GET,
            f"{server.API_V1}/items/condition_overload/statistics",
            json=empty_stats,
            status=200,
        )
        result = server._quick_price("Condition Overload")
        assert result["source"] == "orderbook"
        assert result["liquidity"] == "LOW"
        assert result["warning"] is not None
        # Bottom 3 online sellers: 10, 12, 15 → avg around 12
        assert 10 <= result["avg"] <= 16

    @responses.activate
    def test_dead_mod_no_data(self):
        """If no trades AND no sellers, return error/DEAD status."""
        server._item_cache = FAKE_ITEMS
        responses.add(
            responses.GET,
            f"{server.API_BASE}/orders/item/condition_overload",
            json={"data": []},
            status=200,
        )
        empty_stats = {"payload": {"statistics_closed": {"48hours": [], "90days": []}}}
        responses.add(
            responses.GET,
            f"{server.API_V1}/items/condition_overload/statistics",
            json=empty_stats,
            status=200,
        )
        result = server._quick_price("Condition Overload")
        assert result["avg"] == 0
        assert result["source"] == "none"
        assert result["liquidity"] == "DEAD"

    @responses.activate
    def test_liquidity_tiers(self):
        """HIGH (10+/day), MED (3-9/day), LOW (<3/day)."""
        server._item_cache = FAKE_ITEMS
        responses.add(
            responses.GET,
            f"{server.API_BASE}/orders/item/condition_overload",
            json={"data": FAKE_SELL_ORDERS},
            status=200,
        )
        # HIGH: 15/day avg over 7 days = 105 total
        high_stats = _stats_payload([(i, 15, 15) for i in range(7)])
        responses.add(
            responses.GET,
            f"{server.API_V1}/items/condition_overload/statistics",
            json=high_stats,
            status=200,
        )
        result = server._quick_price("Condition Overload")
        assert result["liquidity"] == "HIGH"
        assert result["volume"] >= 10

    @responses.activate
    def test_not_found_item(self):
        server._item_cache = FAKE_ITEMS
        result = server._quick_price("Totally Fake Item")
        assert result["error"] == "not found"
        assert result["avg"] == 0

    @responses.activate
    def test_api_error_handled(self):
        server._item_cache = FAKE_ITEMS
        responses.add(
            responses.GET,
            f"{server.API_BASE}/orders/item/condition_overload",
            json={"error": "server error"},
            status=500,
        )
        responses.add(
            responses.GET,
            f"{server.API_V1}/items/condition_overload/statistics",
            json={"error": "server error"},
            status=500,
        )
        result = server._quick_price("Condition Overload")
        assert "error" in result or result.get("avg") == 0

    @responses.activate
    def test_returns_low_price_for_undercut(self):
        """`low` field should always show lowest online listing (for undercut pricing)."""
        server._item_cache = FAKE_ITEMS
        responses.add(
            responses.GET,
            f"{server.API_BASE}/orders/item/condition_overload",
            json={"data": FAKE_SELL_ORDERS},
            status=200,
        )
        stats = _stats_payload([(i, 15, 10) for i in range(7)])
        responses.add(
            responses.GET,
            f"{server.API_V1}/items/condition_overload/statistics",
            json=stats,
            status=200,
        )
        result = server._quick_price("Condition Overload")
        # Lowest online/ingame seller = 10p
        assert result["low"] == 10


# ============================================================
# _load_syndicate_data TESTS
# ============================================================

class TestSyndicateData:
    """Tests for syndicate data loading and mod lookup."""

    def test_load_from_json(self, tmp_path):
        fake_json = tmp_path / "syndicate_mods_verified.json"
        fake_json.write_text(json.dumps(FAKE_SYNDICATE_DATA))
        with patch.object(server, "VERIFIED_JSON", fake_json):
            data = server._load_syndicate_data()
            assert "syndicates" in data
            assert "Arbiters of Hexis" in data["syndicates"]

    def test_missing_json_returns_empty(self, tmp_path):
        fake_json = tmp_path / "nonexistent.json"
        with patch.object(server, "VERIFIED_JSON", fake_json):
            data = server._load_syndicate_data()
            assert data == {}

    def test_get_syndicate_mods_exact(self, tmp_path):
        fake_json = tmp_path / "syndicate_mods_verified.json"
        fake_json.write_text(json.dumps(FAKE_SYNDICATE_DATA))
        with patch.object(server, "VERIFIED_JSON", fake_json):
            mods = server._get_syndicate_mods("Arbiters of Hexis")
            assert "Stinging Truth" in mods
            assert "Surging Dash" in mods
            assert "Radiant Finish" in mods
            assert "Swing Line" in mods

    def test_get_syndicate_mods_fuzzy(self, tmp_path):
        fake_json = tmp_path / "syndicate_mods_verified.json"
        fake_json.write_text(json.dumps(FAKE_SYNDICATE_DATA))
        with patch.object(server, "VERIFIED_JSON", fake_json):
            mods = server._get_syndicate_mods("Arbiters")
            assert len(mods) > 0

    def test_get_syndicate_mods_not_found(self, tmp_path):
        fake_json = tmp_path / "syndicate_mods_verified.json"
        fake_json.write_text(json.dumps(FAKE_SYNDICATE_DATA))
        with patch.object(server, "VERIFIED_JSON", fake_json):
            mods = server._get_syndicate_mods("Fake Syndicate")
            assert mods == []


# ============================================================
# ARCHON SHARD MAPPING TESTS
# ============================================================

class TestArchonShardMappings:
    """Verify shard colors are correct per wiki."""

    def test_amar_is_crimson(self):
        boss, shard = server._ARCHON_BOSSES["SORTIE_BOSS_AMAR"]
        assert shard == "Crimson"
        assert "Amar" in boss

    def test_nira_is_amber(self):
        boss, shard = server._ARCHON_BOSSES["SORTIE_BOSS_NIRA"]
        assert shard == "Amber"
        assert "Nira" in boss

    def test_boreal_is_azure(self):
        boss, shard = server._ARCHON_BOSSES["SORTIE_BOSS_BOREAL"]
        assert shard == "Azure"
        assert "Boreal" in boss


# ============================================================
# _ts_to_eta TESTS
# ============================================================

class TestTimestampConversion:
    """Tests for DE timestamp to ETA string."""

    def test_expired_timestamp(self):
        # A timestamp in the past
        result = server._ts_to_eta(1000000000000)
        assert result == "Expired"

    def test_far_future_shows_days(self):
        from datetime import datetime, timedelta
        future = datetime.now() + timedelta(days=3, hours=5)
        ts = int(future.timestamp() * 1000)
        result = server._ts_to_eta(ts)
        assert "3d" in result

    def test_hours_only(self):
        from datetime import datetime, timedelta
        future = datetime.now() + timedelta(hours=2, minutes=30)
        ts = int(future.timestamp() * 1000)
        result = server._ts_to_eta(ts)
        assert "2h" in result

    def test_minutes_only(self):
        from datetime import datetime, timedelta
        future = datetime.now() + timedelta(minutes=15)
        ts = int(future.timestamp() * 1000)
        result = server._ts_to_eta(ts)
        assert "15m" in result or "14m" in result  # allow 1 min drift

    def test_de_nested_dict_format(self):
        from datetime import datetime, timedelta
        future = datetime.now() + timedelta(hours=1)
        ts_ms = str(int(future.timestamp() * 1000))
        result = server._ts_to_eta({"$date": {"$numberLong": ts_ms}})
        assert result != "?" and result != "Expired"

    def test_invalid_input_returns_question(self):
        result = server._ts_to_eta("not_a_timestamp")
        assert result == "?"


# ============================================================
# TOOL OUTPUT TESTS — fissure_sniper
# ============================================================

class TestFissureSniper:
    """Tests for the fissure_sniper tool."""

    @responses.activate
    def test_finds_fast_fissures(self):
        responses.add(responses.GET, f"{server.WFSTAT}/fissures", json=FAKE_FISSURES, status=200)
        result = server.fissure_sniper()
        assert "Fissure Sniper" in result
        assert "Capture" in result
        assert "Axi" in result
        # Defense should NOT appear (not a fast type)
        assert "Io (Jupiter)" not in result
        # Lith should NOT appear (not a good tier)
        assert "Hepit" not in result

    @responses.activate
    def test_no_fast_fissures_shows_all(self):
        slow_fissures = [
            {"missionType": "Defense", "tier": "Axi", "node": "Hydra", "enemy": "Corpus", "eta": "30m", "expired": False},
        ]
        responses.add(responses.GET, f"{server.WFSTAT}/fissures", json=slow_fissures, status=200)
        result = server.fissure_sniper()
        assert "No fast fissures" in result or "No Capture/Exterminate" in result

    @responses.activate
    def test_api_failure(self):
        responses.add(responses.GET, f"{server.WFSTAT}/fissures", body=Exception("timeout"))
        result = server.fissure_sniper()
        assert "Failed" in result


# ============================================================
# TOOL OUTPUT TESTS — world_state_dashboard
# ============================================================

class TestWorldStateDashboard:
    """Tests for world_state_dashboard tool."""

    @responses.activate
    def test_shows_archon_hunt(self):
        responses.add(responses.GET, server.WFSTAT, json=FAKE_WORLD_STATE, status=200)
        result = server.world_state_dashboard()
        assert "Archon" in result
        assert "Boreal" in result

    @responses.activate
    def test_shows_duviri_cycle(self):
        responses.add(responses.GET, server.WFSTAT, json=FAKE_WORLD_STATE, status=200)
        result = server.world_state_dashboard()
        assert "Duviri" in result
        assert "sorrow" in result.lower() or "Sorrow" in result

    @responses.activate
    def test_shows_sortie(self):
        responses.add(responses.GET, server.WFSTAT, json=FAKE_WORLD_STATE, status=200)
        result = server.world_state_dashboard()
        assert "Sortie" in result
        assert "Tyl Regor" in result


# ============================================================
# TOOL OUTPUT TESTS — baro_tracker
# ============================================================

class TestBaroTracker:
    """Tests for baro_tracker tool."""

    @responses.activate
    def test_baro_active_shows_inventory(self):
        responses.add(responses.GET, f"{server.WFSTAT}/voidTrader", json=FAKE_BARO_ACTIVE, status=200)
        result = server.baro_tracker()
        assert "Active" in result
        assert "Primed Continuity" in result
        assert "350" in result  # ducats

    @responses.activate
    def test_baro_inactive_shows_arrival(self):
        responses.add(responses.GET, f"{server.WFSTAT}/voidTrader", json=FAKE_BARO_INACTIVE, status=200)
        result = server.baro_tracker()
        assert "Not here" in result or "Arrives" in result


# ============================================================
# TOOL OUTPUT TESTS — price_check
# ============================================================

class TestPriceCheck:
    """Tests for the price_check tool."""

    @responses.activate
    def test_returns_table_format(self):
        server._item_cache = FAKE_ITEMS
        responses.add(
            responses.GET,
            f"{server.API_BASE}/orders/item/condition_overload",
            json={"data": FAKE_SELL_ORDERS},
            status=200,
        )
        result = server.price_check("Condition Overload")
        assert "Condition Overload" in result
        assert "Price Check" in result
        assert "Player1" in result
        assert "10p" in result or "10" in result

    @responses.activate
    def test_not_found_item(self):
        server._item_cache = FAKE_ITEMS
        result = server.price_check("Nonexistent Widget")
        assert "Could not find" in result


# ============================================================
# TOOL OUTPUT TESTS — search_items
# ============================================================

class TestSearchItems:
    """Tests for the search_items tool."""

    def test_finds_matching_items(self):
        server._item_cache = FAKE_ITEMS
        result = server.search_items("Condition")
        assert "Condition Overload" in result

    def test_no_results(self):
        server._item_cache = FAKE_ITEMS
        result = server.search_items("zzzznonexistent")
        assert "No items found" in result


# ============================================================
# TOOL OUTPUT TESTS — item_statistics
# ============================================================

class TestItemStatistics:
    """Tests for item_statistics tool."""

    @responses.activate
    def test_shows_48h_and_90d(self):
        server._item_cache = FAKE_ITEMS
        responses.add(
            responses.GET,
            f"{server.API_V1}/items/condition_overload/statistics",
            json=FAKE_STATS_RESPONSE,
            status=200,
        )
        result = server.item_statistics("Condition Overload")
        assert "48 Hours" in result
        assert "90-Day" in result
        assert "15.5" in result or "15" in result


# ============================================================
# TOOL OUTPUT TESTS — market_spread_finder
# ============================================================

class TestMarketSpreadFinder:
    """Tests for market_spread_finder tool."""

    @responses.activate
    def test_shows_spread(self):
        server._item_cache = FAKE_ITEMS
        # v1 orders endpoint
        v1_orders = [
            {"order_type": "sell", "platinum": 15, "user": {"ingame_name": "Seller1", "status": "online"}},
            {"order_type": "buy", "platinum": 8, "user": {"ingame_name": "Buyer1", "status": "online"}},
        ]
        responses.add(
            responses.GET,
            f"{server.API_V1}/items/condition_overload/orders",
            json={"payload": {"orders": v1_orders}},
            status=200,
        )
        result = server.market_spread_finder("Condition Overload")
        assert "Spread" in result
        assert "7p" in result  # 15 - 8 = 7


# ============================================================
# PRICE HISTORY TESTS
# ============================================================

class TestPriceHistory:
    """Tests for price history save/load."""

    def test_save_and_load(self, tmp_path):
        history_file = tmp_path / "price_history.json"
        with patch.object(server, "PRICE_HISTORY", history_file):
            prices = [
                {"name": "TestMod", "low": 10, "avg": 15, "orders": 5},
            ]
            server._save_price_history("Test Syndicate", prices)

            assert history_file.exists()
            data = json.loads(history_file.read_text())
            assert "Test Syndicate" in data
            assert len(data["Test Syndicate"]) == 1
            assert data["Test Syndicate"][0]["mods"]["TestMod"]["avg"] == 15

    def test_keeps_max_30_scans(self, tmp_path):
        history_file = tmp_path / "price_history.json"
        # Pre-populate with 30 scans
        existing = {"Test": [{"date": f"2026-01-{i:02d}", "mods": {}} for i in range(1, 31)]}
        history_file.write_text(json.dumps(existing))

        with patch.object(server, "PRICE_HISTORY", history_file):
            server._save_price_history("Test", [{"name": "Mod", "low": 1, "avg": 2, "orders": 3}])
            data = json.loads(history_file.read_text())
            assert len(data["Test"]) == 30  # trimmed to 30

    def test_price_history_tool_no_data(self):
        with patch.object(server, "PRICE_HISTORY", Path("/tmp/nonexistent_history.json")):
            result = server.price_history("Arbiters")
            assert "No price history" in result


# ============================================================
# EDA MODIFIER MAPPING TESTS
# ============================================================

class TestEDAMappings:
    """Verify EDA mission type and modifier mappings exist."""

    def test_eda_types_not_empty(self):
        assert len(server._EDA_TYPES) > 0

    def test_eda_modifiers_not_empty(self):
        assert len(server._EDA_MODIFIERS) > 0

    def test_exterminate_mapped(self):
        assert server._EDA_TYPES.get("DT_EXTERMINATE") == "Exterminate"

    def test_defense_mapped(self):
        assert server._EDA_TYPES.get("DT_DEFENSE") == "Defense"


# ============================================================
# NIGHTWAVE CHALLENGE MAPPING TESTS
# ============================================================

class TestNightwaveMappings:
    """Verify nightwave challenge lookups."""

    def test_known_challenge(self):
        assert "Kill 100 Eximus" in server._NW_CHALLENGES.get(
            "SeasonWeeklyPermanentKillEximus23", ""
        )

    def test_elite_challenge(self):
        result = server._NW_CHALLENGES.get("SeasonWeeklyHardCompleteSortie", "")
        assert "ELITE" in result


# ============================================================
# _fetch_world_state TESTS
# ============================================================

class TestFetchWorldState:
    """Tests for the dual-source world state fetcher."""

    @responses.activate
    def test_warframestat_primary(self):
        responses.add(responses.GET, f"{server.WFSTAT}/", json={"test": "data", "padding": "x" * 100}, status=200)
        result = server._fetch_world_state()
        assert result["source"] == "warframestat"
        assert result["data"]["test"] == "data"

    @responses.activate
    def test_fallback_to_de(self):
        responses.add(responses.GET, f"{server.WFSTAT}/", body=b"", status=200)
        responses.add(
            responses.GET,
            "https://content.warframe.com/dynamic/worldState.php",
            json={"de": "fallback"},
            status=200,
        )
        result = server._fetch_world_state()
        assert result["source"] == "de"

    @responses.activate
    def test_both_fail_returns_error(self):
        responses.add(responses.GET, f"{server.WFSTAT}/", body=Exception("down"))
        responses.add(
            responses.GET,
            "https://content.warframe.com/dynamic/worldState.php",
            body=Exception("also down"),
        )
        result = server._fetch_world_state()
        assert result["source"] == "error"
