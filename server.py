#!/usr/bin/env python3
"""Warframe Toolkit MCP Server - market prices, syndicate lookup, world state, arbitrage"""

import json
import os
import re
import requests
from datetime import datetime
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("warframe-market")

API_BASE = "https://api.warframe.market/v2"
API_V1 = "https://api.warframe.market/v1"
WFSTAT = "https://api.warframestat.us/pc"
HEADERS = {"Accept": "application/json", "Language": "en"}
TOOLKIT_DIR = Path(__file__).parent
VERIFIED_JSON = TOOLKIT_DIR / "syndicate_mods_verified.json"
PRICE_HISTORY = TOOLKIT_DIR / "price_history.json"
DE_USAGE_URL = "https://www-static.warframe.com/repos/WarframeUsageData{year}.json"

# Cache item list so we don't spam the API
_item_cache = None
_syndicate_cache = None


def _get_items():
    """Fetch and cache all tradeable items."""
    global _item_cache
    if _item_cache is None:
        res = requests.get(f"{API_BASE}/items", headers=HEADERS, timeout=10)
        res.raise_for_status()
        _item_cache = res.json()["data"]
    return _item_cache


def _find_item_slug(query: str) -> tuple[str, str]:
    """Fuzzy match an item name to its slug. Returns (slug, matched_name)."""
    items = _get_items()
    query_lower = query.lower().strip()

    # Exact match first
    for item in items:
        name = item["i18n"]["en"]["name"].lower()
        if name == query_lower:
            return item["slug"], item["i18n"]["en"]["name"]

    # Partial match
    matches = []
    for item in items:
        name = item["i18n"]["en"]["name"].lower()
        if query_lower in name:
            matches.append((item["slug"], item["i18n"]["en"]["name"]))

    if matches:
        matches.sort(key=lambda x: len(x[1]))
        return matches[0]

    # Word-based fuzzy match
    query_words = set(query_lower.split())
    best = None
    best_score = 0
    for item in items:
        name = item["i18n"]["en"]["name"].lower()
        name_words = set(name.split())
        score = len(query_words & name_words)
        if score > best_score:
            best_score = score
            best = (item["slug"], item["i18n"]["en"]["name"])

    if best and best_score >= 1:
        return best

    return None, None


def _load_syndicate_data():
    """Load verified syndicate mod data."""
    global _syndicate_cache
    if _syndicate_cache is None:
        if VERIFIED_JSON.exists():
            with open(VERIFIED_JSON) as f:
                _syndicate_cache = json.load(f)
        else:
            _syndicate_cache = {}
    return _syndicate_cache


def _get_syndicate_mods(syndicate_name: str) -> list[str]:
    """Get all mods for a syndicate from verified data."""
    data = _load_syndicate_data()
    syndicates = data.get("syndicates", {})

    # Fuzzy match syndicate name
    name_lower = syndicate_name.lower().strip()
    matched_key = None
    for key in syndicates:
        if name_lower in key.lower() or key.lower() in name_lower:
            matched_key = key
            break

    if not matched_key:
        return []

    syn = syndicates[matched_key]
    mods = list(syn.get("weapon_augments", []))
    for wf_mods in syn.get("warframe_augments", {}).values():
        mods.extend(wf_mods)
    return mods


def _fetch_statistics(slug: str) -> dict:
    """Fetch v1 /statistics endpoint for a slug. Returns {} on failure."""
    try:
        res = requests.get(f"{API_V1}/items/{slug}/statistics",
                           headers=HEADERS, timeout=10)
        if res.status_code != 200:
            return {}
        return res.json().get("payload", {}).get("statistics_closed", {})
    except Exception:
        return {}


def _traded_median_from_stats(stats: dict, days: int = 7):
    """Compute volume-weighted median of traded prices over last N days.
    Returns (median_price, avg_daily_volume) or (None, 0) if insufficient data.
    """
    entries = stats.get("90days", []) or []
    if not entries:
        return (None, 0)
    # Last N daily entries (api returns chronologically sorted)
    recent = entries[-days:]
    total_vol = sum(e.get("volume", 0) for e in recent)
    if total_vol < 5:  # need at least 5 trades in window
        return (None, total_vol / max(len(recent), 1))

    # Volume-weighted median of daily medians
    # Expand: treat each daily median as weighted by its volume
    weighted = []
    for e in recent:
        median = e.get("median", e.get("avg_price", 0))
        vol = e.get("volume", 0)
        weighted.extend([median] * int(vol))
    if not weighted:
        return (None, 0)
    weighted.sort()
    mid = len(weighted) // 2
    if len(weighted) % 2 == 0:
        median_price = (weighted[mid - 1] + weighted[mid]) / 2
    else:
        median_price = weighted[mid]
    avg_daily_volume = total_vol / len(recent)
    return (median_price, avg_daily_volume)


def _liquidity_tier(avg_daily_volume: float) -> str:
    """Map daily volume to a liquidity label."""
    if avg_daily_volume >= 10:
        return "HIGH"
    if avg_daily_volume >= 3:
        return "MED"
    if avg_daily_volume > 0:
        return "LOW"
    return "DEAD"


def _quick_price(item_name: str) -> dict:
    """Get accurate price for an item.

    Priority:
      1. Volume-weighted median of last 7 days of actual trades (source='traded_7d')
      2. Fallback: bottom-3 online sellers avg (source='orderbook') with warning
      3. DEAD: no trades + no sellers (source='none')

    Returns:
      {
        name, avg, low, orders,
        volume (daily avg), liquidity ('HIGH'|'MED'|'LOW'|'DEAD'),
        source ('traded_7d'|'orderbook'|'none'),
        warning (str or None),
        error (str or None)
      }
    """
    slug, matched_name = _find_item_slug(item_name)
    if not slug:
        return {"name": item_name, "low": 0, "avg": 0, "orders": 0,
                "volume": 0, "liquidity": "DEAD", "source": "none",
                "warning": None, "error": "not found"}

    # 1. Fetch both order book and statistics in parallel (sequential is fine here)
    order_err = None
    sell_orders = []
    try:
        res = requests.get(f"{API_BASE}/orders/item/{slug}", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            data = res.json().get("data", [])
            if isinstance(data, list):
                sell_orders = [o for o in data if o.get("type") == "sell"
                               and o.get("user", {}).get("status") in ("ingame", "online")]
                if not sell_orders:
                    sell_orders = [o for o in data if o.get("type") == "sell"]
        else:
            order_err = f"orders api {res.status_code}"
    except Exception as e:
        order_err = str(e)

    stats = _fetch_statistics(slug)

    # Low price from order book (for undercut reference)
    low_price = 0
    if sell_orders:
        sell_orders.sort(key=lambda x: x.get("platinum", 999999))
        low_price = sell_orders[0].get("platinum", 0)

    # Listed avg of bottom 3 (for warning comparison)
    listed_avg = 0
    if sell_orders:
        bottom_3 = [o.get("platinum", 0) for o in sell_orders[:3]]
        listed_avg = sum(bottom_3) / len(bottom_3)

    # 2. Primary: traded median from last 7 days
    traded_median, avg_daily_vol = _traded_median_from_stats(stats, days=7)

    if traded_median is not None:
        warning = None
        # Warning if listed avg >> traded median (stale holdouts)
        if listed_avg > 0 and traded_median > 0:
            diff_ratio = abs(listed_avg - traded_median) / traded_median
            if diff_ratio > 0.3:
                warning = (f"Listed avg {listed_avg:.0f}p differs from traded "
                           f"median {traded_median:.0f}p — list near {int(max(low_price, traded_median - 1))}p")
        return {
            "name": matched_name,
            "avg": round(traded_median),
            "low": low_price,
            "orders": len(sell_orders),
            "volume": round(avg_daily_vol, 1),
            "liquidity": _liquidity_tier(avg_daily_vol),
            "source": "traded_7d",
            "warning": warning,
            "error": None,
        }

    # 3. Fallback: bottom-3 online sellers
    if sell_orders and len(sell_orders) >= 1:
        n = min(3, len(sell_orders))
        bottom_n_prices = [o.get("platinum", 0) for o in sell_orders[:n]]
        fallback_avg = sum(bottom_n_prices) / len(bottom_n_prices)
        return {
            "name": matched_name,
            "avg": round(fallback_avg),
            "low": low_price,
            "orders": len(sell_orders),
            "volume": 0,
            "liquidity": "LOW",
            "source": "orderbook",
            "warning": "no recent trades — price estimated from listings only",
            "error": None,
        }

    # 4. Dead: no data at all
    return {
        "name": matched_name, "avg": 0, "low": 0, "orders": 0,
        "volume": 0, "liquidity": "DEAD", "source": "none",
        "warning": "no trades and no listings", "error": order_err,
    }


def _save_price_history(syndicate: str, prices: list[dict]):
    """Append price scan to history file."""
    history = {}
    if PRICE_HISTORY.exists():
        with open(PRICE_HISTORY) as f:
            history = json.load(f)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    if syndicate not in history:
        history[syndicate] = []

    entry = {
        "date": timestamp,
        "mods": {p["name"]: {"low": p["low"], "avg": p["avg"], "orders": p["orders"]}
                 for p in prices if not p.get("error")},
    }
    history[syndicate].append(entry)

    # Keep last 30 scans per syndicate
    if len(history[syndicate]) > 30:
        history[syndicate] = history[syndicate][-30:]

    with open(PRICE_HISTORY, "w") as f:
        json.dump(history, f, indent=2)


# ============================================================
# MARKET TOOLS — price_check, search_items, price_check_multiple, trending_items, item_statistics
# ============================================================

@mcp.tool()
def price_check(item_name: str) -> str:
    """Look up the current price of any Warframe tradeable item on warframe.market.
    Returns the cheapest sell orders from online/in-game players, plus average price stats.
    Works for mods, prime parts, arcanes, sets, blueprints, etc.
    """
    slug, matched_name = _find_item_slug(item_name)
    if not slug:
        return f"Could not find item matching '{item_name}'. Try a more specific name."

    try:
        res = requests.get(f"{API_BASE}/orders/item/{slug}", headers=HEADERS, timeout=10)
        res.raise_for_status()
        data = res.json()["data"]
    except Exception as e:
        try:
            res = requests.get(
                f"https://api.warframe.market/v1/items/{slug}/orders",
                headers=HEADERS, timeout=10
            )
            res.raise_for_status()
            data = res.json()["payload"]["orders"]
        except Exception:
            return f"Found '{matched_name}' but failed to fetch orders: {e}"

    if isinstance(data, list):
        sell_orders = [o for o in data if o.get("type") == "sell"
                       and o.get("user", {}).get("status") in ("ingame", "online")]
    else:
        sell_orders = []

    if not sell_orders and isinstance(data, list):
        sell_orders = [o for o in data if o.get("type") == "sell"]
        if sell_orders:
            sell_orders.sort(key=lambda x: x.get("platinum", 999999))
            sell_orders = sell_orders[:15]

    if not sell_orders:
        return f"**{matched_name}** — No active sell orders found."

    sell_orders.sort(key=lambda x: x.get("platinum", 999999))

    lines = [f"**{matched_name}** — Price Check\n"]
    lines.append("| # | Price | Seller | Status | Quantity |")
    lines.append("|---|-------|--------|--------|----------|")

    for i, order in enumerate(sell_orders[:10]):
        user = order.get("user", {})
        name = user.get("ingameName", user.get("ingame_name", "Unknown"))
        status = user.get("status", "?")
        plat = order.get("platinum", "?")
        qty = order.get("quantity", 1)
        mod_rank = order.get("rank", order.get("mod_rank"))
        rank_str = f" (R{mod_rank})" if mod_rank is not None else ""
        lines.append(f"| {i+1} | {plat}p{rank_str} | {name} | {status} | {qty} |")

    prices = [o.get("platinum", 0) for o in sell_orders[:20]]
    if prices:
        avg = sum(prices) / len(prices)
        lines.append(f"\n**Lowest:** {prices[0]}p | **Average (top 20):** {avg:.0f}p | **Orders:** {len(sell_orders)}")

    return "\n".join(lines)


@mcp.tool()
def search_items(query: str) -> str:
    """Search for Warframe items by name. Returns matching items with their slugs.
    Use this when you're not sure of the exact item name.
    """
    items = _get_items()
    query_lower = query.lower().strip()

    matches = []
    for item in items:
        name = item["i18n"]["en"]["name"]
        if query_lower in name.lower():
            tags = ", ".join(item.get("tags", []))
            matches.append(f"- **{name}** (slug: `{item['slug']}`, tags: {tags})")

    if not matches:
        return f"No items found matching '{query}'."

    if len(matches) > 25:
        matches = matches[:25]
        matches.append(f"\n... and more. Try a more specific search.")

    return f"**Items matching '{query}'** ({len(matches)} results):\n\n" + "\n".join(matches)


@mcp.tool()
def price_check_multiple(item_names: str) -> str:
    """Check prices for multiple items at once. Provide comma-separated item names.
    Great for comparing values of items from a screenshot.
    Example: 'Condition Overload, Blind Rage, Primed Flow'
    """
    names = [n.strip() for n in item_names.split(",") if n.strip()]
    results = []
    icon_map = {"HIGH": "🟢", "MED": "🟡", "LOW": "🟠", "DEAD": "⚫"}

    for name in names:
        p = _quick_price(name)
        if p.get("error") == "not found":
            results.append(f"- **{name}** — Not found")
            continue
        if p["avg"] == 0:
            results.append(f"- **{p['name']}** — No trades or sellers")
            continue
        icon = icon_map.get(p.get("liquidity", ""), "")
        src = p.get("source", "")
        src_tag = " (listings only)" if src == "orderbook" else ""
        warn = " ⚠️" if p.get("warning") else ""
        results.append(
            f"- **{p['name']}**{warn} — Median: {p['avg']}p | Low: {p['low']}p | "
            f"Vol: {p.get('volume', 0)}/d {icon} | Sellers: {p['orders']}{src_tag}"
        )

    lines = ["**Multi-Item Price Check:** (7-day traded median)"]
    lines.extend(results)
    return "\n".join(lines)


@mcp.tool()
def trending_items() -> str:
    """Get the most actively traded items on warframe.market right now.
    Checks a curated list of high-volume items using live sell orders for accurate prices.
    """
    popular_slugs = [
        "condition_overload", "blind_rage", "adaptation", "rolling_guard",
        "primed_continuity", "primed_flow", "primed_pressure_point",
        "growing_power", "steel_charge", "energy_siphon",
        "arcane_energize", "arcane_grace", "arcane_avenger", "arcane_guardian",
        "overextended", "transient_fortitude", "narrow_minded", "fleeting_expertise",
        "galvanized_chamber", "galvanized_hell", "galvanized_aptitude", "galvanized_diffusion",
        "melee_influence", "melee_exposure", "melee_vortex", "melee_animosity",
        "combat_discipline", "brief_respite", "primary_merciless", "secondary_dexterity",
    ]

    results = []
    for slug in popular_slugs:
        try:
            res = requests.get(f"{API_BASE}/orders/item/{slug}", headers=HEADERS, timeout=5)
            if res.status_code != 200:
                continue
            data = res.json()["data"]
            if not isinstance(data, list):
                continue
            sells = [o for o in data if o.get("type") == "sell"
                     and o.get("user", {}).get("status") in ("ingame", "online")]
            if not sells:
                sells = [o for o in data if o.get("type") == "sell"]
            if not sells:
                continue
            sells.sort(key=lambda x: x.get("platinum", 999999))
            prices = [o.get("platinum", 0) for o in sells[:10]]
            name = sells[0].get("item", {}).get("i18n", {}).get("en", {}).get("name", slug.replace("_", " ").title())
            results.append((name, prices[0], round(sum(prices) / len(prices)), len(sells)))
        except Exception:
            continue

    results.sort(key=lambda x: x[2], reverse=True)

    lines = ["**Trending Items — Live Prices:**\n"]
    lines.append("| Item | Low | Avg | Sellers |")
    lines.append("|------|-----|-----|---------|")
    for name, low, avg, orders in results:
        lines.append(f"| {name} | {low}p | {avg}p | {orders} |")

    return "\n".join(lines)


@mcp.tool()
def item_statistics(item_name: str) -> str:
    """Get detailed price statistics and history for an item.
    Shows 48-hour and 90-day price trends, volume, min/max prices.
    """
    slug, matched_name = _find_item_slug(item_name)
    if not slug:
        return f"Could not find item matching '{item_name}'."

    try:
        res = requests.get(
            f"https://api.warframe.market/v1/items/{slug}/statistics",
            headers=HEADERS, timeout=10
        )
        res.raise_for_status()
        data = res.json()["payload"]["statistics_closed"]

        stats_48h = data.get("48hours", [])
        stats_90d = data.get("90days", [])

        lines = [f"**{matched_name}** — Price Statistics\n"]

        if stats_48h:
            recent = stats_48h[-1]
            lines.append("**Last 48 Hours:**")
            lines.append(f"- Avg: {recent.get('avg_price', 'N/A')}p")
            lines.append(f"- Min: {recent.get('min_price', 'N/A')}p")
            lines.append(f"- Max: {recent.get('max_price', 'N/A')}p")
            lines.append(f"- Volume: {recent.get('volume', 'N/A')} trades")
            lines.append(f"- Median: {recent.get('median', 'N/A')}p")

        if stats_90d:
            lines.append("\n**90-Day Trend (last 5 data points):**")
            lines.append("| Date | Avg | Min | Max | Volume |")
            lines.append("|------|-----|-----|-----|--------|")
            for stat in stats_90d[-5:]:
                date = stat.get("datetime", "")[:10]
                lines.append(
                    f"| {date} | {stat.get('avg_price', '?')}p | "
                    f"{stat.get('min_price', '?')}p | {stat.get('max_price', '?')}p | "
                    f"{stat.get('volume', '?')} |"
                )

        return "\n".join(lines)
    except Exception as e:
        return f"Failed to get statistics for {matched_name}: {e}"


# ============================================================
# SYNDICATE TOOLS — syndicate_lookup, best_buys, price_history
# ============================================================

@mcp.tool()
def syndicate_lookup(syndicate_name: str) -> str:
    """Look up all verified mods for a syndicate with live prices, sorted by profit.
    Uses wiki-verified data (syndicate_mods_verified.json) — no guessing.
    Example: syndicate_lookup('Arbiters of Hexis')
    """
    data = _load_syndicate_data()
    if not data:
        return "Error: syndicate_mods_verified.json not found. Run wiki scraper first."

    syndicates = data.get("syndicates", {})
    name_lower = syndicate_name.lower().strip()
    matched_key = None
    for key in syndicates:
        if name_lower in key.lower() or key.lower() in name_lower:
            matched_key = key
            break

    if not matched_key:
        available = ", ".join(syndicates.keys())
        return f"Syndicate '{syndicate_name}' not found. Available: {available}"

    syn = syndicates[matched_key]
    all_mods = list(syn.get("weapon_augments", []))
    warframe_map = syn.get("warframe_augments", {})
    for wf_mods in warframe_map.values():
        all_mods.extend(wf_mods)

    # Build warframe lookup
    mod_to_warframe = {}
    for wf, mods in warframe_map.items():
        for mod in mods:
            mod_to_warframe[mod] = wf
    for mod in syn.get("weapon_augments", []):
        mod_to_warframe[mod] = "Weapon"

    # Price check all mods
    priced = []
    for mod in all_mods:
        p = _quick_price(mod)
        p["warframe"] = mod_to_warframe.get(mod, "?")
        priced.append(p)

    # Save to price history
    _save_price_history(matched_key, priced)

    # Sort by avg price descending
    priced.sort(key=lambda x: x["avg"], reverse=True)

    lines = [f"**{matched_key}** — {len(priced)} mods (traded median, last 7d)\n"]

    # Split into tiers
    rare = [p for p in priced if p["avg"] >= 20]
    good = [p for p in priced if 15 <= p["avg"] < 20]
    common = [p for p in priced if 10 <= p["avg"] < 15]
    cheap = [p for p in priced if p["avg"] < 10]

    def liq_icon(p):
        tier = p.get("liquidity", "?")
        return {"HIGH": "🟢", "MED": "🟡", "LOW": "🟠", "DEAD": "⚫"}.get(tier, "❓")

    def row(p):
        flag = " ⚠️" if p.get("warning") else ""
        src = p.get("source", "?")
        vol = p.get("volume", 0)
        return (f"| {p['name']}{flag} | {p['avg']}p | {p['low']}p | "
                f"{vol}/d {liq_icon(p)} | {p['orders']} | {p['warframe']} |")

    def table_header():
        return (["| Mod | Median | Low | Vol | Sellers | Frame |",
                 "|-----|--------|-----|-----|---------|-------|"])

    if rare:
        lines.append("**RARE SELLS (20p+):**")
        lines.extend(table_header())
        for p in rare: lines.append(row(p))

    if good:
        lines.append("\n**CONSISTENT (15-19p):**")
        lines.extend(table_header())
        for p in good: lines.append(row(p))

    if common:
        lines.append("\n**QUICK SELLS (10-14p):**")
        lines.extend(table_header())
        for p in common: lines.append(row(p))

    if cheap:
        lines.append(f"\n**LOW VALUE (<10p):** {', '.join(p['name'] + ' (' + str(p['avg']) + 'p)' for p in cheap)}")

    # Warnings summary — show stale-listing mods
    warnings = [p for p in priced if p.get("warning") and p["avg"] >= 10]
    if warnings:
        lines.append("\n**⚠️ Stale Listings Detected** (listed avg differs from actual traded median):")
        for p in warnings[:10]:
            lines.append(f"- **{p['name']}**: {p['warning']}")

    # Summary
    all_avg = [p["avg"] for p in priced if p["avg"] > 0]
    if all_avg:
        top5 = sorted(all_avg, reverse=True)[:5]
        high_liq = sum(1 for p in priced if p.get("liquidity") == "HIGH")
        med_liq = sum(1 for p in priced if p.get("liquidity") == "MED")
        lines.append(f"\n**Summary:** Avg all={sum(all_avg)/len(all_avg):.1f}p | "
                     f"Top 5 avg={sum(top5)/5:.1f}p | 20p+ mods={len(rare)} | "
                     f"🟢High liq={high_liq} 🟡Med={med_liq}")
    lines.append("\n*Prices = volume-weighted median of actual trades last 7d. "
                 "⚠️ = listings inflated above real market. List near 'Low' to sell fast.*")

    return "\n".join(lines)


@mcp.tool()
def best_buys(syndicate_name: str, standing: int = 100000) -> str:
    """Get optimal shopping list for a syndicate given your available standing.
    Ranks mods by plat-per-standing efficiency and tells you exactly what to buy.
    Each augment costs 25,000 standing. Example: best_buys('Cephalon Suda', 132000)
    """
    mods = _get_syndicate_mods(syndicate_name)
    if not mods:
        return f"Syndicate '{syndicate_name}' not found or no verified data."

    # Price all mods
    priced = []
    for mod in mods:
        p = _quick_price(mod)
        if not p.get("error") and p["avg"] > 0:
            p["efficiency"] = round(p["avg"] / 25, 2)  # plat per 1k standing
            priced.append(p)

    priced.sort(key=lambda x: x["avg"], reverse=True)

    cost_per_mod = 25000
    budget = standing
    cart = []
    total_plat = 0

    for p in priced:
        if budget >= cost_per_mod:
            cart.append(p)
            budget -= cost_per_mod
            total_plat += p["avg"]

    lines = [f"**Best Buys — {standing:,} standing budget**\n"]
    lines.append(f"Can buy **{len(cart)} mods** (25,000 standing each)\n")
    lines.append("| # | Buy This | Avg Price | Efficiency | Orders |")
    lines.append("|---|----------|-----------|------------|--------|")

    for i, p in enumerate(cart):
        lines.append(f"| {i+1} | {p['name']} | {p['avg']}p | {p['efficiency']}p/1k | {p['orders']} |")

    lines.append(f"\n**Total expected plat: ~{total_plat}p** from {len(cart)} trades")
    lines.append(f"**Standing left over: {budget:,}**")

    if priced:
        lines.append(f"\n**Best single buy:** {priced[0]['name']} at {priced[0]['avg']}p ({priced[0]['efficiency']}p per 1k standing)")

    return "\n".join(lines)


@mcp.tool()
def price_history(syndicate_name: str) -> str:
    """Show price trend history for a syndicate's mods across multiple scans.
    Tracks how prices change over time. Run syndicate_lookup first to record data.
    """
    if not PRICE_HISTORY.exists():
        return "No price history yet. Run syndicate_lookup on a syndicate first to start tracking."

    with open(PRICE_HISTORY) as f:
        history = json.load(f)

    # Fuzzy match
    name_lower = syndicate_name.lower().strip()
    matched_key = None
    for key in history:
        if name_lower in key.lower() or key.lower() in name_lower:
            matched_key = key
            break

    if not matched_key or not history[matched_key]:
        available = ", ".join(history.keys()) if history else "none"
        return f"No history for '{syndicate_name}'. Available: {available}"

    scans = history[matched_key]
    lines = [f"**{matched_key}** — Price History ({len(scans)} scans)\n"]

    if len(scans) < 2:
        lines.append("Only 1 scan recorded. Run syndicate_lookup again later to track changes.")
        scan = scans[0]
        lines.append(f"\nScan date: {scan['date']}")
        top = sorted(scan["mods"].items(), key=lambda x: x[1]["avg"], reverse=True)[:10]
        lines.append("| Mod | Avg | Low | Orders |")
        lines.append("|-----|-----|-----|--------|")
        for name, data in top:
            lines.append(f"| {name} | {data['avg']}p | {data['low']}p | {data['orders']} |")
        return "\n".join(lines)

    # Compare latest vs previous
    latest = scans[-1]
    previous = scans[-2]

    lines.append(f"Latest scan: {latest['date']} | Previous: {previous['date']}\n")

    # Find biggest movers
    movers = []
    for mod, curr in latest["mods"].items():
        if mod in previous["mods"]:
            prev = previous["mods"][mod]
            diff = curr["avg"] - prev["avg"]
            if diff != 0:
                movers.append((mod, prev["avg"], curr["avg"], diff))

    movers.sort(key=lambda x: abs(x[3]), reverse=True)

    if movers:
        lines.append("**Biggest Price Changes:**")
        lines.append("| Mod | Was | Now | Change |")
        lines.append("|-----|-----|-----|--------|")
        for mod, prev_avg, curr_avg, diff in movers[:15]:
            arrow = "+" if diff > 0 else ""
            lines.append(f"| {mod} | {prev_avg}p | {curr_avg}p | {arrow}{diff}p |")
    else:
        lines.append("No price changes detected between scans.")

    # Overall trend
    latest_avgs = [v["avg"] for v in latest["mods"].values() if v["avg"] > 0]
    prev_avgs = [v["avg"] for v in previous["mods"].values() if v["avg"] > 0]
    if latest_avgs and prev_avgs:
        curr_mean = sum(latest_avgs) / len(latest_avgs)
        prev_mean = sum(prev_avgs) / len(prev_avgs)
        trend = "UP" if curr_mean > prev_mean else "DOWN" if curr_mean < prev_mean else "FLAT"
        lines.append(f"\n**Overall trend:** {trend} (avg {prev_mean:.1f}p → {curr_mean:.1f}p)")

    return "\n".join(lines)


# ============================================================
# PHASE 2 — WORLD STATE & ARBITRAGE TOOLS
# ============================================================

@mcp.tool()
def fissure_sniper() -> str:
    """Find the fastest active Void Fissures for relic cracking.
    Filters for Capture/Exterminate missions on Meso/Neo/Axi tiers only —
    the fastest mission types for speed-cracking relics.
    """
    try:
        res = requests.get(f"{WFSTAT}/fissures", headers=HEADERS, timeout=10)
        res.raise_for_status()
        fissures = res.json()
    except Exception as e:
        return f"Failed to fetch fissures: {e}"

    fast_types = {"Capture", "Exterminate"}
    good_tiers = {"Meso", "Neo", "Axi"}

    filtered = [
        f for f in fissures
        if f.get("missionType") in fast_types
        and f.get("tier") in good_tiers
        and not f.get("expired", False)
    ]

    if not filtered:
        lines = ["**Fissure Sniper** — No fast fissures right now.\n"]
        lines.append("No Capture/Exterminate fissures active for Meso/Neo/Axi tiers.")
        lines.append("Current fissures are slower mission types. Check back in a few minutes.\n")
        all_good = [f for f in fissures if f.get("tier") in good_tiers and not f.get("expired", False)]
        if all_good:
            lines.append("**All Meso/Neo/Axi fissures (any type):**")
            lines.append("| Tier | Node | Type | Enemy | Expires |")
            lines.append("|------|------|------|-------|---------|")
            for f in sorted(all_good, key=lambda x: good_tiers.__iter__().__next__):
                lines.append(
                    f"| {f.get('tier', '?')} | {f.get('node', '?')} | "
                    f"{f.get('missionType', '?')} | {f.get('enemy', '?')} | "
                    f"{f.get('eta', '?')} |"
                )
        return "\n".join(lines)

    # Sort by tier priority: Axi > Neo > Meso
    tier_order = {"Axi": 0, "Neo": 1, "Meso": 2}
    filtered.sort(key=lambda x: tier_order.get(x.get("tier", ""), 99))

    lines = [f"**Fissure Sniper** — {len(filtered)} fast fissures found\n"]
    lines.append("| Tier | Node | Type | Enemy | Expires |")
    lines.append("|------|------|------|-------|---------|")

    for f in filtered:
        lines.append(
            f"| {f.get('tier', '?')} | {f.get('node', '?')} | "
            f"{f.get('missionType', '?')} | {f.get('enemy', '?')} | "
            f"{f.get('eta', '?')} |"
        )

    lines.append("\nThese are Capture/Exterminate only — fastest for cracking relics.")
    return "\n".join(lines)


@mcp.tool()
def world_state_dashboard() -> str:
    """Quick weekly endgame tracker. Shows Archon Hunt, Duviri Cycle, and Sortie
    status in one view — everything you need for your weekly reset.
    """
    try:
        res = requests.get(WFSTAT, headers=HEADERS, timeout=10)
        res.raise_for_status()
        state = res.json()
    except Exception as e:
        return f"Failed to fetch world state: {e}"

    lines = ["**World State Dashboard**\n"]

    # Archon Hunt
    archon = state.get("archonHunt")
    if archon:
        lines.append("**Archon Hunt:**")
        boss = archon.get("boss", "Unknown")
        eta = archon.get("eta", "?")
        lines.append(f"- Boss: {boss}")
        lines.append(f"- Resets in: {eta}")
        missions = archon.get("missions", [])
        if missions:
            lines.append("- Missions:")
            for m in missions:
                node = m.get("node", "?")
                mtype = m.get("type", "?")
                lines.append(f"  - {mtype} — {node}")
    else:
        lines.append("**Archon Hunt:** No data available")

    lines.append("")

    # Duviri Cycle
    duviri = state.get("duviriCycle")
    if duviri:
        mood = duviri.get("state", "Unknown")
        eta = duviri.get("eta", "?")
        lines.append(f"**Duviri Cycle:** {mood} (changes in {eta})")
    else:
        lines.append("**Duviri Cycle:** No data available")

    lines.append("")

    # Sortie
    sortie = state.get("sortie")
    if sortie:
        lines.append("**Sortie:**")
        boss = sortie.get("boss", "Unknown")
        eta = sortie.get("eta", "?")
        lines.append(f"- Boss: {boss}")
        lines.append(f"- Resets in: {eta}")
        variants = sortie.get("variants", [])
        if variants:
            lines.append("- Missions:")
            for v in variants:
                node = v.get("node", "?")
                mtype = v.get("missionType", "?")
                modifier = v.get("modifier", "")
                mod_desc = v.get("modifierDescription", "")
                line = f"  - {mtype} — {node}"
                if modifier:
                    line += f" [{modifier}]"
                lines.append(line)
    else:
        lines.append("**Sortie:** No data available")

    return "\n".join(lines)


@mcp.tool()
def baro_tracker() -> str:
    """Check Baro Ki'Teer's status and inventory.
    Shows when he arrives (if gone) or what he's selling (if active) with Ducat/Credit costs.
    """
    try:
        res = requests.get(f"{WFSTAT}/voidTrader", headers=HEADERS, timeout=10)
        res.raise_for_status()
        baro = res.json()
    except Exception as e:
        return f"Failed to fetch Baro Ki'Teer data: {e}"

    active = baro.get("active", False)

    if not active:
        arrival = baro.get("startString", baro.get("activation", "Unknown"))
        relay = baro.get("location", "TBD")
        lines = ["**Baro Ki'Teer** — Not here yet\n"]
        lines.append(f"- Arrives: {arrival}")
        lines.append(f"- Location: {relay}")
        lines.append("\nCheck back when he arrives for his inventory.")
        return "\n".join(lines)

    # Baro is active
    location = baro.get("location", "Unknown")
    end_string = baro.get("endString", baro.get("eta", "?"))
    inventory = baro.get("inventory", [])

    lines = [f"**Baro Ki'Teer** — Active at {location}\n"]
    lines.append(f"Leaves in: {end_string}\n")

    if inventory:
        lines.append(f"**Inventory ({len(inventory)} items):**")
        lines.append("| Item | Ducats | Credits |")
        lines.append("|------|--------|---------|")
        for item in inventory:
            name = item.get("item", "Unknown")
            ducats = item.get("ducats", 0)
            credits = item.get("credits", 0)
            lines.append(f"| {name} | {ducats:,} | {credits:,} |")
    else:
        lines.append("Inventory not yet loaded or empty.")

    return "\n".join(lines)


@mcp.tool()
def market_spread_finder(item_name: str) -> str:
    """Find the flip margin between Buy and Sell orders for a specific item.
    Shows the highest buy offer, lowest sell listing, and the platinum spread.
    Use this to find arbitrage opportunities — buy low from buy orders, sell at sell price.
    Example: market_spread_finder('Condition Overload')
    """
    slug, matched_name = _find_item_slug(item_name)
    if not slug:
        return f"Could not find item matching '{item_name}'. Try a more specific name."

    try:
        res = requests.get(
            f"{API_V1}/items/{slug}/orders",
            headers={**HEADERS, "Platform": "pc"},
            timeout=10,
        )
        res.raise_for_status()
        orders = res.json()["payload"]["orders"]
    except Exception as e:
        # Fallback to v2
        try:
            res = requests.get(f"{API_BASE}/orders/item/{slug}", headers=HEADERS, timeout=10)
            res.raise_for_status()
            orders = res.json()["data"]
        except Exception:
            return f"Failed to fetch orders for '{matched_name}': {e}"

    # Filter for online/ingame users only
    live = [o for o in orders if o.get("user", {}).get("status") in ("ingame", "online")]
    if not live:
        live = orders  # Fall back to all orders

    sells = [o for o in live if o.get("order_type", o.get("type")) == "sell"]
    buys = [o for o in live if o.get("order_type", o.get("type")) == "buy"]

    if not sells and not buys:
        return f"**{matched_name}** — No active orders found."

    lowest_sell = min((o.get("platinum", 999999) for o in sells), default=None) if sells else None
    highest_buy = max((o.get("platinum", 0) for o in buys), default=None) if buys else None

    lines = [f"**{matched_name}** — Market Spread Analysis\n"]

    if lowest_sell is not None:
        lines.append(f"- Lowest Sell: **{lowest_sell}p** ({len(sells)} sell orders)")
    else:
        lines.append("- Lowest Sell: No sell orders")

    if highest_buy is not None:
        lines.append(f"- Highest Buy: **{highest_buy}p** ({len(buys)} buy orders)")
    else:
        lines.append("- Highest Buy: No buy orders")

    if lowest_sell is not None and highest_buy is not None:
        spread = lowest_sell - highest_buy
        if spread > 0:
            lines.append(f"\n**Spread: {spread}p** profit per flip")
            lines.append(f"Buy at {highest_buy}p (buy order) -> Sell at {lowest_sell}p (sell listing)")
            if spread >= 10:
                lines.append("HIGH margin — worth flipping.")
            elif spread >= 5:
                lines.append("Decent margin — viable if volume is there.")
            else:
                lines.append("Thin margin — probably not worth the trade tax.")
        elif spread == 0:
            lines.append("\n**Spread: 0p** — No margin. Buy and sell prices are equal.")
        else:
            lines.append(f"\n**Spread: {spread}p** — Inverted! Buyers offering more than sellers asking. Market is hot.")

    # Show top 3 buy/sell for context
    if sells:
        sells_sorted = sorted(sells, key=lambda x: x.get("platinum", 999999))[:3]
        lines.append("\n**Top 3 Sell Listings:**")
        for o in sells_sorted:
            user = o.get("user", {})
            name = user.get("ingame_name", user.get("ingameName", "?"))
            lines.append(f"  - {o.get('platinum')}p — {name} ({user.get('status', '?')})")

    if buys:
        buys_sorted = sorted(buys, key=lambda x: x.get("platinum", 0), reverse=True)[:3]
        lines.append("\n**Top 3 Buy Offers:**")
        for o in buys_sorted:
            user = o.get("user", {})
            name = user.get("ingame_name", user.get("ingameName", "?"))
            lines.append(f"  - {o.get('platinum')}p — {name} ({user.get('status', '?')})")

    return "\n".join(lines)


@mcp.tool()
def riven_price_estimator(weapon_name: str) -> str:
    """Find baseline prices for unrolled Rivens for a specific weapon.
    Searches warframe.market auctions for 0-roll Rivens with buyout prices.
    Use this to estimate what an unrolled Riven is worth before rolling.
    Example: riven_price_estimator('rubico')
    """
    # Normalize weapon name to URL format
    weapon_slug = weapon_name.lower().strip().replace(" ", "_").replace("'", "").replace("-", "_")

    try:
        res = requests.get(
            f"{API_V1}/auctions/search",
            params={
                "type": "riven",
                "weapon_url_name": weapon_slug,
                "sort_by": "price_asc",
            },
            headers={**HEADERS, "Platform": "pc"},
            timeout=10,
        )
        res.raise_for_status()
        auctions = res.json()["payload"]["auctions"]
    except Exception as e:
        return f"Failed to search Riven auctions for '{weapon_name}': {e}"

    if not auctions:
        # Try alternate slug formats
        alt_slugs = [
            weapon_slug,
            weapon_slug.replace("_prime", ""),
            weapon_slug + "_prime",
        ]
        for alt in alt_slugs[1:]:
            try:
                res = requests.get(
                    f"{API_V1}/auctions/search",
                    params={"type": "riven", "weapon_url_name": alt, "sort_by": "price_asc"},
                    headers={**HEADERS, "Platform": "pc"},
                    timeout=10,
                )
                res.raise_for_status()
                auctions = res.json()["payload"]["auctions"]
                if auctions:
                    weapon_slug = alt
                    break
            except Exception:
                continue

    if not auctions:
        return f"No Riven auctions found for '{weapon_name}'. Try the base weapon name (e.g. 'rubico' not 'Rubico Prime')."

    # Filter: unrolled (re_rolls == 0) and has a buyout price
    unrolled = [
        a for a in auctions
        if a.get("item", {}).get("re_rolls", -1) == 0
        and a.get("buyout_price") is not None
        and a.get("buyout_price", 0) > 0
    ]

    # Also get all unrolled (including starting_price only)
    unrolled_any = [
        a for a in auctions
        if a.get("item", {}).get("re_rolls", -1) == 0
    ]

    if not unrolled and not unrolled_any:
        # Show rolled rivens as context
        with_buyout = [a for a in auctions if a.get("buyout_price") and a.get("buyout_price", 0) > 0]
        with_buyout.sort(key=lambda x: x.get("buyout_price", 999999))

        lines = [f"**{weapon_name.title()} Riven** — No unrolled Rivens listed\n"]
        if with_buyout:
            lines.append(f"Found {len(with_buyout)} rolled Riven listings. Top 5 cheapest:")
            lines.append("| Price | Rolls | Polarity | Stats |")
            lines.append("|-------|-------|----------|-------|")
            for a in with_buyout[:5]:
                item = a.get("item", {})
                rolls = item.get("re_rolls", "?")
                pol = item.get("polarity", "?")
                attrs = item.get("attributes", [])
                stats = ", ".join(
                    f"{at.get('positive', True) and '+' or '-'}{at.get('value', '?')}% {at.get('short_string', at.get('url_name', '?'))}"
                    for at in attrs[:3]
                )
                lines.append(f"| {a.get('buyout_price', '?')}p | {rolls} | {pol} | {stats} |")
        return "\n".join(lines)

    # Sort unrolled by buyout price
    unrolled.sort(key=lambda x: x.get("buyout_price", 999999))

    lines = [f"**{weapon_name.title()} Riven** — Unrolled (0 rolls) Baseline Prices\n"]
    lines.append(f"Found {len(unrolled)} unrolled Rivens with buyout prices (out of {len(auctions)} total listings)\n")
    lines.append("| # | Buyout | Polarity | Stats | Seller |")
    lines.append("|---|--------|----------|-------|--------|")

    for i, a in enumerate(unrolled[:5]):
        item = a.get("item", {})
        pol = item.get("polarity", "?")
        attrs = item.get("attributes", [])
        stats = ", ".join(
            f"{'+'if at.get('positive', True) else '-'}{at.get('value', '?')}% {at.get('short_string', at.get('url_name', '?'))}"
            for at in attrs[:3]
        )
        owner = a.get("owner", {})
        seller = owner.get("ingame_name", "?")
        price = a.get("buyout_price", "?")
        lines.append(f"| {i+1} | {price}p | {pol} | {stats} | {seller} |")

    # Summary
    prices = [a.get("buyout_price", 0) for a in unrolled[:10] if a.get("buyout_price")]
    if prices:
        avg = round(sum(prices) / len(prices))
        lines.append(f"\n**Baseline estimate:** {prices[0]}p (cheapest) — {avg}p (avg of top {len(prices)})")

    return "\n".join(lines)


# ============================================================
# PHASE 3 — WEEKLY RESET PREP
# ============================================================

# Warframe internal name mappings
_ARCHON_BOSSES = {
    "SORTIE_BOSS_AMAR": ("Archon Amar (Wolf)", "Crimson"),
    "SORTIE_BOSS_NIRA": ("Archon Nira (Snake)", "Amber"),
    "SORTIE_BOSS_BOREAL": ("Archon Boreal (Owl)", "Azure"),
}

_EDA_TYPES = {
    "DT_EXTERMINATE": "Exterminate", "DT_BREAK_TARGETS": "Break Targets",
    "DT_ALCHEMY": "Alchemy", "DT_MIMICS": "Mimics",
    "DT_INTERCEPTION": "Interception", "DT_CAPTURE": "Capture",
    "DT_PROTOFRAME": "Protoframe", "DT_INFESTED_SALVAGE": "Infested Salvage",
    "DT_COLLECTION": "Collection", "DT_LOOT_CREATURES": "Loot Creatures",
    "DT_SABOTAGE_DEFENSE": "Sabotage Defense", "DT_RACE": "Race",
    "DT_DEFENSE": "Defense", "DT_BOSS": "Boss Fight",
    "DT_PRESURE_GAUGE": "Pressure Gauge",
}

_EDA_MODIFIERS = {
    "VeryToxic": "Toxic Leech", "NC_Darkness": "Darkness",
    "GlassMaker": "Glass Maker", "BasicMimics": "Mimics",
    "Manics": "Manics", "HardShell": "Hard Shell",
    "NarmerPhobia": "Narmer Phobia", "NC_NarmerPhobia": "Narmer Phobia",
    "PoisonGas": "Poison Gas", "BasicLootCreatures": "Loot Creatures",
    "SpikeCeiling": "Spike Ceiling", "GiantRealm": "Giant Realm",
    "BasicRace": "Race", "FireAndIce": "Fire and Ice",
    "FreezeInShoot": "Freeze N Shoot", "UnseenFoes": "Unseen Foes",
    "HeadShotsOnly": "Headshots Only", "RocketDropOnDeath": "Rocket Drop",
}

_NW_CHALLENGES = {
    "SeasonWeeklyPermanentCompleteMissions23": "Complete 10 Missions",
    "SeasonWeeklyPermanentKillEximus23": "Kill 100 Eximus",
    "SeasonWeeklyPermanentKillEnemies23": "Kill 500 Enemies",
    "SeasonWeeklySolveCiphers": "Solve 10 Ciphers",
    "SeasonWeeklyKillEnemiesInMech": "Kill 100 in Necramech",
    "SeasonWeeklyHardKillEximus": "ELITE: Kill 250 Eximus",
    "SeasonWeeklyHardFriendsSurvival": "ELITE: 30min Survival with Friend",
    "SeasonWeeklyHardCompleteSortie": "ELITE: Complete a Sortie",
    "SeasonWeeklyHardKillSentients": "ELITE: Kill 100 Sentients",
    "SeasonWeeklyHardComplete8Bounties": "ELITE: Complete 8 Bounties",
}


def _fetch_world_state() -> dict:
    """Fetch world state from WarframeStat.us, fall back to DE endpoint."""
    # Try WarframeStat.us first (parsed/friendly)
    try:
        res = requests.get(f"{WFSTAT}/", headers=HEADERS, timeout=8)
        if res.status_code == 200 and len(res.content) > 100:
            return {"source": "warframestat", "data": res.json()}
    except Exception:
        pass

    # Fall back to official DE endpoint (raw)
    try:
        res = requests.get(
            "https://content.warframe.com/dynamic/worldState.php",
            timeout=10,
        )
        res.raise_for_status()
        return {"source": "de", "data": res.json()}
    except Exception as e:
        return {"source": "error", "error": str(e)}


def _ts_to_eta(timestamp_ms) -> str:
    """Convert a DE timestamp to a human-readable time remaining string."""
    try:
        if isinstance(timestamp_ms, dict):
            timestamp_ms = int(timestamp_ms.get("$date", {}).get("$numberLong", 0))
        exp = datetime.fromtimestamp(int(timestamp_ms) / 1000)
        now = datetime.now()
        delta = exp - now
        if delta.total_seconds() <= 0:
            return "Expired"
        days = delta.days
        hours = delta.seconds // 3600
        mins = (delta.seconds % 3600) // 60
        if days > 0:
            return f"{days}d {hours}h"
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"
    except Exception:
        return "?"


@mcp.tool()
def warframe_weekly_gaz_prep() -> str:
    """Full endgame weekly reset prep. Shows Steel Path Incarnon rotation, Archon Hunt
    with shard color, EDA missions and dangerous modifiers, Nightwave elite challenges,
    Baro status, and must-do weekly reminders. Everything a late-game player needs in one view.
    """
    ws = _fetch_world_state()
    if ws["source"] == "error":
        return f"Failed to fetch world state: {ws['error']}"

    data = ws["data"]
    is_de = ws["source"] == "de"

    lines = []

    # ================================================================
    # SECTION 1: HIGH-VALUE TIME-GATED LOOT
    # ================================================================
    lines.append("## HIGH-VALUE TIME-GATED LOOT\n")

    # Teshin's Steel Path reward
    if is_de:
        # DE endpoint doesn't expose Teshin's shop directly in worldState
        lines.append("**Teshin's Weekly Steel Path Offering:**")
        lines.append("- Check Teshin in any Relay for this week's reward (Umbra Forma, Riven Mod, etc.)")
        lines.append("- Costs 75 Steel Essence per item")
    else:
        sp = data.get("steelPath", {})
        reward = sp.get("currentReward", {})
        if reward:
            lines.append(f"**Teshin's Weekly Offering:** {reward.get('name', 'Unknown')} ({reward.get('cost', '?')} Steel Essence)")
        else:
            lines.append("**Teshin's Weekly Offering:** Check in-game (Relay)")

    lines.append("")
    lines.append("**Weekly Must-Do Checklist:**")
    lines.append("- Visit **Palladino** at Iron Wake (Earth) -- trade Riven Slivers for Kuva and 2x Veiled Rivens")
    lines.append("- Visit **Bird-3** in the Sanctum Anatomica -- buy the weekly **Archon Shard** for 30,000 Cavia standing")
    lines.append("- Check **Acrithis** in the Dormizone -- weekly Rivens, Catalysts, Reactors, Forma for Pathos Clamps")
    lines.append("- Visit **Yonta** (Zariman) -- trade 5 Voidplume Pinions for 35,000 Kuva")
    lines.append("- Check the **Clan Dojo** for weekly Clan Roster rewards")
    lines.append("- Claim **Nightwave** weekly standing before reset")

    # ================================================================
    # SECTION 2: STEEL PATH CIRCUIT (INCARNON)
    # ================================================================
    lines.append("\n## STEEL PATH CIRCUIT (Incarnon Rotation)\n")

    if is_de:
        choices = data.get("EndlessXpChoices", [])
        for choice in choices:
            cat = choice.get("Category", "")
            items = choice.get("Choices", [])
            if cat == "EXC_HARD":
                lines.append(f"**This Week's Incarnon Weapons (Steel Path Circuit):**")
                for item in items:
                    # CamelCase to spaced name (DualToxocyst -> Dual Toxocyst)
                    display = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', item)
                    lines.append(f"- {display}")
                lines.append("")
                lines.append("**Pick your 2 Incarnon Adapters carefully!** These rotate weekly.")
            elif cat == "EXC_NORMAL":
                display_wfs = [re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', w) for w in items]
                lines.append(f"\n**Normal Circuit Warframes:** {', '.join(display_wfs)}")
    else:
        duviri = data.get("duviriCycle", {})
        choices_list = duviri.get("choices", [])
        lines.append(f"**Duviri Cycle:** {duviri.get('state', '?').title()}")
        if isinstance(choices_list, list):
            for entry in choices_list:
                cat = entry.get("categoryKey", entry.get("category", ""))
                items = entry.get("choices", [])
                if cat == "EXC_HARD" and items:
                    lines.append(f"\n**This Week's Incarnon Weapons (Steel Path Circuit):**")
                    for item in items:
                        display = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', item)
                        lines.append(f"- {display}")
                    lines.append("")
                    lines.append("**Pick your 2 Incarnon Adapters carefully!** These rotate weekly.")
                elif cat == "EXC_NORMAL" and items:
                    display_wfs = [re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', w) for w in items]
                    lines.append(f"\n**Normal Circuit Warframes:** {', '.join(display_wfs)}")
        if not choices_list:
            lines.append("**Incarnon Rotation:** Check the Steel Path Circuit in-game")

    # ================================================================
    # SECTION 3: ENDGAME CONTENT (EDA & ARCHON)
    # ================================================================
    lines.append("\n## ENDGAME CONTENT\n")

    # Archon Hunt
    if is_de:
        lite = data.get("LiteSorties", [])
        if lite:
            archon = lite[0]
            boss_key = archon.get("Boss", "")
            boss_name, shard_color = _ARCHON_BOSSES.get(boss_key, (boss_key, "Unknown"))
            eta = _ts_to_eta(archon.get("Expiry", {}))
            lines.append(f"**Archon Hunt:** {boss_name}")
            lines.append(f"- Shard Drop: **{shard_color} Archon Shard**")
            lines.append(f"- Resets in: {eta}")
            missions = archon.get("Missions", [])
            if missions:
                lines.append("- Missions:")
                for m in missions:
                    mtype = m.get("missionType", "?").replace("MT_", "").replace("_", " ").title()
                    node = m.get("node", "?")
                    lines.append(f"  - {mtype} -- {node}")
    else:
        ah = data.get("archonHunt", {})
        if ah:
            boss = ah.get("boss", "Unknown")
            shard = "Amber" if "Nira" in boss else "Azure" if "Boreal" in boss else "Crimson" if "Amar" in boss else "Unknown"
            lines.append(f"**Archon Hunt:** {boss}")
            lines.append(f"- Shard Drop: **{shard} Archon Shard**")
            lines.append(f"- Resets in: {ah.get('eta', '?')}")

    lines.append("")

    # Elite Deep Archimedea
    if is_de:
        descents = data.get("Descents", [])
        if descents:
            desc = descents[0]
            eta = _ts_to_eta(desc.get("Expiry", {}))
            challenges = desc.get("Challenges", [])
            lines.append(f"**Elite Deep Archimedea (EDA):** {len(challenges)} floors | Resets in: {eta}\n")

            # Show first 5 floors (the interesting ones) + the boss
            shown = 0
            dangerous = []
            for c in challenges:
                raw_type = c.get("Type", "?")
                mission = _EDA_TYPES.get(raw_type, raw_type.replace("DT_", "").replace("_", " ").title())
                modifier = _EDA_MODIFIERS.get(c.get("Challenge", ""), c.get("Challenge", ""))

                has_aura = bool(c.get("Auras"))
                if has_aura:
                    dangerous.append(f"{mission} + {modifier}")

                if shown < 6 or "BOSS" in raw_type or "PROTOFRAME" in raw_type:
                    marker = " **DANGER**" if has_aura else ""
                    lines.append(f"- Floor {c.get('Index', '?')}: {mission} [{modifier}]{marker}")
                    shown += 1

            if len(challenges) > shown:
                lines.append(f"- ... and {len(challenges) - shown} more floors")

            if dangerous:
                lines.append(f"\n**Watch out for:** {', '.join(dangerous[:5])}")
    else:
        eda = data.get("deepArchimedea")
        if eda:
            missions = eda.get("missions", [])
            lines.append(f"**Elite Deep Archimedea (EDA):** {len(missions)} missions")
            for m in missions:
                lines.append(f"- {m.get('type', '?')} [{m.get('modifier', '?')}]")

    # ================================================================
    # SECTION 4: FOMO & EVENTS
    # ================================================================
    lines.append("\n## FOMO & EVENTS\n")

    # Nightwave
    if is_de:
        season = data.get("SeasonInfo", {})
        if season:
            season_num = season.get("Season", "?")
            eta = _ts_to_eta(season.get("Expiry", {}))
            challenges = season.get("ActiveChallenges", [])

            lines.append(f"**Nightwave Season {season_num}** -- Ends in: {eta}\n")

            weeklies = []
            for c in challenges:
                if c.get("Daily"):
                    continue
                path = c.get("Challenge", "")
                name = path.split("/")[-1] if path else "?"
                display = _NW_CHALLENGES.get(name, name.replace("SeasonWeekly", "").replace("Hard", "ELITE: "))
                is_elite = "Elite" in display or "ELITE" in display or "Hard" in name
                weeklies.append((display, is_elite))

            if weeklies:
                lines.append("**Weekly Challenges:**")
                for display, is_elite in weeklies:
                    prefix = "**[ELITE]**" if is_elite else "  "
                    lines.append(f"- {prefix} {display}")
    else:
        nw = data.get("nightwave", {})
        if nw:
            lines.append(f"**Nightwave** -- Ends in: {nw.get('eta', '?')}")
            for c in nw.get("activeChallenges", []):
                if c.get("isElite"):
                    lines.append(f"- **[ELITE]** {c.get('title', c.get('desc', '?'))}")

    lines.append("")

    # Active Events
    if is_de:
        events = data.get("Events", [])
        real_events = []
        for ev in events:
            msgs = ev.get("Messages", [])
            for msg in msgs:
                if msg.get("LanguageCode") == "en":
                    text = msg.get("Message", "")
                    # Skip Discord promo / non-gameplay events
                    if "Discord" in text or "Language" in text:
                        continue
                    eta = _ts_to_eta(ev.get("Expiry", {}))
                    if eta != "Expired" and eta != "?":
                        real_events.append((text.split("/")[-1], eta))

        if real_events:
            lines.append("**Active Events:**")
            for name, eta in real_events:
                lines.append(f"- {name} -- Ends in: {eta}")
        else:
            lines.append("**Active Events:** None this week. Grind in peace.")
    else:
        events = data.get("events", [])
        if events:
            lines.append("**Active Events:**")
            for ev in events:
                lines.append(f"- {ev.get('description', ev.get('tooltip', '?'))} -- Ends: {ev.get('eta', '?')}")
        else:
            lines.append("**Active Events:** None this week.")

    # Baro quick status
    lines.append("")
    if is_de:
        traders = data.get("VoidTraders", [])
        if traders:
            baro = traders[0]
            activation = _ts_to_eta(baro.get("Activation", {}))
            expiry = _ts_to_eta(baro.get("Expiry", {}))
            inventory = baro.get("Inventory", [])
            node = baro.get("Node", "?")
            if inventory:
                lines.append(f"**Baro Ki'Teer:** Active at {node} -- Leaves in: {expiry} ({len(inventory)} items)")
            else:
                lines.append(f"**Baro Ki'Teer:** Arrives in {activation} at {node}")
    else:
        vt = data.get("voidTrader", {})
        if vt:
            if vt.get("active"):
                lines.append(f"**Baro Ki'Teer:** Active at {vt.get('location', '?')} -- use `baro_tracker` for full inventory")
            else:
                lines.append(f"**Baro Ki'Teer:** Arrives {vt.get('startString', '?')}")

    return "\n".join(lines)


# ============================================================
# PHASE 4 — USAGE ANALYTICS & MARKET INTELLIGENCE
# ============================================================

def _fetch_usage_data(year: int = 2025) -> dict:
    """Fetch official DE usage stats for a given year."""
    try:
        res = requests.get(DE_USAGE_URL.format(year=year), timeout=10)
        res.raise_for_status()
        return res.json()
    except Exception:
        return {}


def _get_combined_usage(warframes: dict, name: str) -> float:
    """Get combined usage for a frame (base + prime + umbra)."""
    base = warframes.get(name, {}).get("ALL", 0)
    prime = warframes.get(f"{name} Prime", {}).get("ALL", 0)
    if name == "Excalibur":
        umbra = warframes.get("Excalibur Umbra", {}).get("ALL", 0)
        return base + prime + umbra
    return base + prime


@mcp.tool()
def frame_popularity(frame_name: str = "") -> str:
    """Check warframe popularity using official DE usage stats.
    Shows 2025 vs 2024 usage with year-over-year trends.
    If no frame specified, shows the full top 30 ranking.
    Can also show a specific frame's detailed MR breakdown.
    Source: warframe.com/en/stats (official Digital Extremes data)
    """
    data_2025 = _fetch_usage_data(2025)
    data_2024 = _fetch_usage_data(2024)

    if not data_2025:
        return "Failed to fetch usage data from warframe.com."

    wf_2025 = data_2025.get("ALL", {}).get("Warframe", {})
    wf_2024 = data_2024.get("ALL", {}).get("Warframe", {}) if data_2024 else {}

    if frame_name.strip():
        # Specific frame lookup
        query = frame_name.strip()
        matched = None
        for name in wf_2025:
            if query.lower() in name.lower():
                matched = name
                break

        if not matched:
            return f"Warframe '{frame_name}' not found in usage data."

        usage_2025 = wf_2025[matched]["ALL"] * 100
        usage_2024 = wf_2024.get(matched, {}).get("ALL", 0) * 100 if wf_2024 else 0

        # Rank
        ranked = sorted(wf_2025.items(), key=lambda x: x[1]["ALL"], reverse=True)
        rank = next((i + 1 for i, (n, _) in enumerate(ranked) if n == matched), "?")

        lines = [f"**{matched}** — Usage Stats (Official DE Data)\n"]
        lines.append(f"- **Rank:** #{rank} out of {len(ranked)}")
        lines.append(f"- **2025 Usage:** {usage_2025:.2f}%")
        if usage_2024 > 0:
            change = ((usage_2025 - usage_2024) / usage_2024) * 100
            arrow = "+" if change > 0 else ""
            lines.append(f"- **2024 Usage:** {usage_2024:.2f}%")
            lines.append(f"- **Year-over-Year:** {arrow}{change:.1f}%")

        # MR breakdown
        mr_data = wf_2025[matched]
        lines.append("\n**Usage by Mastery Rank:**")
        lines.append("| MR Range | Usage % |")
        lines.append("|----------|---------|")
        ranges = [("0-5", 0, 5), ("6-10", 6, 10), ("11-15", 11, 15),
                  ("16-20", 16, 20), ("21-25", 21, 25), ("26-30", 26, 30), ("LR1+", 31, 36)]
        for label, start, end in ranges:
            total = sum(mr_data.get(str(i), 0) for i in range(start, end + 1))
            if total > 0:
                lines.append(f"| MR {label} | {total * 100:.2f}% |")

        # Check if endgame or noob frame
        low_mr = sum(mr_data.get(str(i), 0) for i in range(0, 10))
        high_mr = sum(mr_data.get(str(i), 0) for i in range(20, 37))
        if high_mr > low_mr * 2:
            lines.append("\n**Profile:** Endgame favorite — mostly played by MR20+ veterans")
        elif low_mr > high_mr * 2:
            lines.append("\n**Profile:** New player favorite — mostly played by MR0-10")
        else:
            lines.append("\n**Profile:** Played across all mastery ranks")

        return "\n".join(lines)

    # Full ranking
    ranked = sorted(wf_2025.items(), key=lambda x: x[1]["ALL"], reverse=True)

    lines = ["**Warframe Popularity Rankings 2025** (Official DE Data)\n"]
    lines.append("| # | Warframe | 2025 | 2024 | Change |")
    lines.append("|---|----------|------|------|--------|")

    for i, (name, stats) in enumerate(ranked[:30]):
        pct_2025 = stats["ALL"] * 100
        pct_2024 = wf_2024.get(name, {}).get("ALL", 0) * 100 if wf_2024 else 0
        if pct_2024 > 0:
            change = ((pct_2025 - pct_2024) / pct_2024) * 100
            change_str = f"{'+' if change > 0 else ''}{change:.0f}%"
        else:
            change_str = "NEW"
        lines.append(f"| {i + 1} | {name} | {pct_2025:.2f}% | {pct_2024:.2f}% | {change_str} |")

    lines.append(f"\n*Source: warframe.com/en/stats — {len(ranked)} warframes tracked*")
    return "\n".join(lines)


@mcp.tool()
def market_intelligence() -> str:
    """Deep market analysis combining popularity data with live prices.
    Finds undervalued mods (popular frame, cheap augments) and overpriced mods
    (dead frame, expensive augments). Also spots investment opportunities
    based on frames rising/falling in popularity.
    Source: DE official usage stats + warframe.market live prices + wiki-verified syndicate data
    """
    data_2025 = _fetch_usage_data(2025)
    data_2024 = _fetch_usage_data(2024)

    if not data_2025:
        return "Failed to fetch usage data."

    wf_2025 = data_2025.get("ALL", {}).get("Warframe", {})
    wf_2024 = data_2024.get("ALL", {}).get("Warframe", {}) if data_2024 else {}

    # Load syndicate data for mod-to-frame mapping
    syn_data = _load_syndicate_data()
    if not syn_data:
        return "No syndicate_mods_verified.json found."

    # Build frame -> mods mapping (across all syndicates)
    frame_mods = {}
    for syn_name, syn in syn_data.get("syndicates", {}).items():
        for frame, mods in syn.get("warframe_augments", {}).items():
            if frame not in frame_mods:
                frame_mods[frame] = []
            for mod in mods:
                if mod not in [m[0] for m in frame_mods[frame]]:
                    frame_mods[frame].append((mod, syn_name))

    # Get usage + YoY change for each frame that has augments
    frame_stats = []
    for frame in frame_mods:
        usage = _get_combined_usage(wf_2025, frame)
        usage_prev = _get_combined_usage(wf_2024, frame) if wf_2024 else 0
        yoy = ((usage - usage_prev) / usage_prev * 100) if usage_prev > 0 else 0
        frame_stats.append({
            "frame": frame,
            "usage": usage * 100,
            "prev_usage": usage_prev * 100,
            "yoy": yoy,
            "mods": frame_mods[frame],
        })

    # Price check a sample of mods from interesting frames
    lines = ["**Market Intelligence Report**\n"]
    lines.append("*Cross-referencing DE usage stats with live market prices...*\n")

    # 1. RISING FRAMES — mods might get more expensive
    rising = [f for f in frame_stats if f["yoy"] > 5 and f["usage"] > 0.3]
    rising.sort(key=lambda x: x["yoy"], reverse=True)

    if rising:
        lines.append("## RISING FRAMES — Mod Prices May Increase")
        lines.append("*These frames gained players year-over-year. Their augment demand is growing.*\n")
        for f in rising[:5]:
            mod_name = f["mods"][0][0] if f["mods"] else "?"
            p = _quick_price(mod_name)
            lines.append(f"**{f['frame']}** — usage +{f['yoy']:.0f}% ({f['prev_usage']:.2f}% -> {f['usage']:.2f}%)")
            lines.append(f"  Top augment: {p['name']} — {p['avg']}p ({p['orders']} sellers)")
            lines.append("")
    else:
        lines.append("## RISING FRAMES\n*No frames with significant growth detected.*\n")

    # 2. CRASHING FRAMES — mods getting cheaper, buy low?
    crashing = [f for f in frame_stats if f["yoy"] < -40 and f["prev_usage"] > 0.3]
    crashing.sort(key=lambda x: x["yoy"])

    if crashing:
        lines.append("## CRASHING FRAMES — Cheap Mods, Potential Investments")
        lines.append("*These frames lost 40%+ players. Mods are cheap now — could rebound after buffs/reworks.*\n")
        for f in crashing[:5]:
            mod_name = f["mods"][0][0] if f["mods"] else "?"
            p = _quick_price(mod_name)
            lines.append(f"**{f['frame']}** — usage {f['yoy']:.0f}% ({f['prev_usage']:.2f}% -> {f['usage']:.2f}%)")
            lines.append(f"  Top augment: {p['name']} — {p['avg']}p ({p['orders']} sellers)")
            lines.append("")

    # 3. HIGH DEMAND / LOW PRICE — undervalued mods
    lines.append("## UNDERVALUED — Popular Frame, Cheap Augments")
    lines.append("*High usage but low mod prices = high demand, easy sales.*\n")

    popular_frames = sorted(frame_stats, key=lambda x: x["usage"], reverse=True)[:10]
    undervalued = []
    for f in popular_frames:
        for mod_name, syn in f["mods"][:2]:
            p = _quick_price(mod_name)
            if 0 < p["avg"] <= 12 and p["orders"] >= 15:
                undervalued.append((f["frame"], f["usage"], p["name"], p["avg"], p["orders"], syn))

    if undervalued:
        lines.append("| Frame | Usage | Mod | Price | Sellers | Syndicate |")
        lines.append("|-------|-------|-----|-------|---------|-----------|")
        for frame, usage, mod, price, orders, syn in undervalued[:10]:
            lines.append(f"| {frame} | {usage:.2f}% | {mod} | {price}p | {orders} | {syn} |")
        lines.append("\n*These sell fast because everyone plays the frame. List at market price for quick plat.*")
    else:
        lines.append("*No significant undervalued mods detected at current prices.*")

    # 4. LOW DEMAND / HIGH PRICE — niche profit
    lines.append("\n## NICHE PROFIT — Rare Frame, Expensive Augments")
    lines.append("*Low usage but high mod prices = few sellers, premium prices.*\n")

    niche_frames = [f for f in frame_stats if 0.05 < f["usage"] < 0.8]
    niche_profit = []
    for f in niche_frames:
        for mod_name, syn in f["mods"][:2]:
            p = _quick_price(mod_name)
            if p["avg"] >= 15 and p["orders"] <= 20:
                niche_profit.append((f["frame"], f["usage"], p["name"], p["avg"], p["orders"], syn))

    niche_profit.sort(key=lambda x: x[3], reverse=True)

    if niche_profit:
        lines.append("| Frame | Usage | Mod | Price | Sellers | Syndicate |")
        lines.append("|-------|-------|-----|-------|---------|-----------|")
        for frame, usage, mod, price, orders, syn in niche_profit[:10]:
            lines.append(f"| {frame} | {usage:.2f}% | {mod} | {price}p | {orders} | {syn} |")
        lines.append("\n*Low competition — fewer people sell these. Patient sellers get premium prices.*")
    else:
        lines.append("*No significant niche profit mods detected at current prices.*")

    # 5. CHEAPEST PRIME SETS — MR grinding opportunities
    lines.append("\n## CHEAPEST PRIME SETS — MR Farming Deals")
    lines.append("*Frames that crashed in popularity = cheap Prime sets for mastery XP.*\n")

    crashed_primes = [f for f in frame_stats if f["yoy"] < -30]
    crashed_primes.sort(key=lambda x: x["yoy"])
    prime_deals = []
    for f in crashed_primes[:8]:
        prime_name = f["frame"] + " Prime"
        slug = prime_name.lower().replace(" ", "_") + "_set"
        p = _quick_price(prime_name + " Set")
        if p["avg"] > 0:
            prime_deals.append((prime_name, p["avg"], p["low"], f["yoy"], p["orders"]))

    if prime_deals:
        prime_deals.sort(key=lambda x: x[1])
        lines.append("| Prime Set | Avg | Low | Popularity Drop | Sellers |")
        lines.append("|-----------|-----|-----|-----------------|---------|")
        for name, avg, low, yoy, orders in prime_deals:
            lines.append(f"| {name} | {avg}p | {low}p | {yoy:.0f}% | {orders} |")
        lines.append("\n*Cheap because nobody plays them — but they still give 6,000 MR XP each.*")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
