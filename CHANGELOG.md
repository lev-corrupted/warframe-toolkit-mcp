# Warframe Toolkit — Changelog

## 2026-04-07

### Testing & QA
- Added pytest test suite (`test_server.py`) — **52 tests, 100% passing**
- Tests cover: fuzzy matching, price aggregation (bottom-5 avg), syndicate data loading,
  Archon shard color verification, timestamp conversion, fissure filtering,
  world state dashboard, Baro tracker, price history, market spread, dual-source fallback
- Set up venv with pytest, pytest-mock, responses (HTTP mocking)
- Updated `.gitignore` for `.venv/` and `.pytest_cache/`

### Bug Fixes
- **Fixed Archon shard color mappings** — were completely wrong in both DE and warframestat code paths
  - Amar = Crimson (was Amber), Nira = Amber (was Azure), Boreal = Azure (was Crimson)
  - Verified from wiki.warframe.com/w/Archon_Shard
- Cleaned up section comments in server.py

### Improvements
- Added **Acrithis** (Dormizone) to `warframe_weekly_gaz_prep` weekly checklist
  - Weekly rotating shop: Rivens, Catalysts, Reactors, Exilus Adapters, Forma, Kuva
- Added **Yonta** (Zariman) to weekly checklist — 35,000 Kuva for 5 Voidplume Pinions
- Removed deleted `youtube_transcript.py` from git tracking
- Deleted `__pycache__/` directory
- Initial commit pushed to GitHub: github.com/lev-corrupted/warframe-toolkit-mcp

## 2026-03-30

### Phase 4 — Usage Analytics & Market Intelligence (2 new tools, 16 total)
- **`frame_popularity`** — Official DE usage stats from warframe.com. Shows ranking, 2025 vs 2024, YoY change, per-MR breakdown. Detects if frame is "endgame favorite" vs "new player favorite".
- **`market_intelligence`** — Full market report combining DE popularity + live prices + syndicate data. Sections:
  - Rising Frames (Valkyr +230%, Nyx +180%, Nova +94%)
  - Crashing Frames (Styanax -42%, Dagath -41%)
  - Undervalued Mods (popular frame, cheap augments = fast sales)
  - Niche Profit (rare frame, expensive augments = premium)
  - Cheapest Prime Sets for MR grinding
- Fixed `_quick_price` to use bottom 5 avg instead of top 10 — matches actual trade SMA
- Data source: `https://www-static.warframe.com/repos/WarframeUsageData{year}.json`

### Phase 2 — World State & Arbitrage (5 new tools, 13 total)
- **`fissure_sniper`** — Filters active Void Fissures for Capture/Exterminate on Meso/Neo/Axi. Uses WarframeStat.us API.
- **`world_state_dashboard`** — Archon Hunt + Duviri Cycle + Sortie in one view. Uses WarframeStat.us API.
- **`baro_tracker`** — Baro Ki'Teer arrival countdown or full inventory with Ducat/Credit prices. Uses WarframeStat.us API.
- **`market_spread_finder`** — Buy/Sell spread analysis for any item. Shows highest buy, lowest sell, and flip margin.
- **`riven_price_estimator`** — Unrolled Riven baseline pricing via warframe.market auctions. Filters to 0-roll with buyout.
- Added `API_V1` and `WFSTAT` base URL constants
- Server now at 13 MCP tools total
- Project renamed to warframe-toolkit-mcp
- Made GitHub-ready: README, LICENSE, pyproject.toml, .gitignore

### Phase 1 — Syndicate Tools + Verified Data
- **`syndicate_lookup` tool** — Type a syndicate name, get all verified mods with live prices sorted by profit tier (Rare/Consistent/Quick). Auto-saves to price history.
- **`best_buys` tool** — Input your standing amount + syndicate, get optimal shopping list ranked by plat-per-standing efficiency.
- **`price_history` tool** — Tracks price changes across scans. Shows biggest movers and overall trend direction.
- **`youtube_transcript.py`** — Downloads YouTube auto-captions as clean text. Can "read" any Warframe guide/video for meta info.
- **`syndicate_mods_verified.json`** — Rebuilt from `wiki.warframe.com/w/Syndicate#Warframe_Augment_Mods` table. Each mod mapped to exact syndicate(s) + warframe. Replaces the old inaccurate scrape.
- Server upgraded from 5 to 8 MCP tools
- Price history auto-saves to `price_history.json` (keeps last 30 scans per syndicate)

## 2026-03-28

### Project Merge
- Merged `warframe-market-mcp/` and `wfinfo-ng/` into unified `warframe-toolkit/`
- MCP server path updated in `~/.claude/settings.json` and `.mcp.json`
- wfinfo-ng source kept in `wfinfo-ng/` subdirectory (binary stays at `~/.cargo/bin/wfinfo`)
- Removed ~800MB of Rust build artifacts (target/) — rebuild with `cargo install --path wfinfo-ng --bin wfinfo`
- Removed wiki dump `.md` files (wiki_*.md) — use live wiki.warframe.com instead

### Corrections
- Added `wiki.warframe.com/w/Syndicate#Warframe_Augment_Mods` as mandatory reference for syndicate augment verification
- Previous analysis incorrectly listed 27 mods from other syndicates (Banshee, Garuda, Hildryn, Mesa, Ivara, etc.) as Arbiters of Hexis
- Each warframe's augments are split between TWO syndicates — must always cross-check the table

### Arbiters of Hexis Verified Analysis
Top earners (all confirmed from wiki):
- Rift Haven: 41p avg (Limbo)
- Stinging Truth: 30p avg (Silva & Aegis weapon aug)
- Rift Torrent: 28p avg (Limbo)
- Desiccation's Curse: 25p avg (Inaros)
- Surging Dash: 22p avg (Excalibur)
- Irradiating Disarm: 22p avg (Loki)

## 2026-03-23

### Corrections
- **Acid Shells is NOT a Steel Meridian offering** — it drops from Kela de Thaym boss fight (Merrow, Sedna). Was incorrectly listed as SM syndicate mod.
- **Primary Blight is NOT a Cavia offering** — it comes from Nightcap (Rank 3: Seeker, costs 10 Fergolyte) or Acrithis (10 Pathos Clamps), or Deepmines Bounties. It's a Holdfasts/Duviri item.
- **Reinforced Bond is NOT a Cavia offering** — it comes from The Business (Rank 3: Doer, Solaris United/Fortuna) for 20,000 standing.
- **Entire previous Cavia analysis was wrong** — items listed as "Arcane Dissolution" drops were from various other syndicates. Arcane Dissolution costs Vosfor + Credits, not Cavia standing.

### Verified Cavia (Bird 3) Offerings
Scraped directly from wiki.warframe.com/w/Bird_3:
- Melee Arcanes: Retaliation (5k), Fortification (5k), Exposure (7.5k), Influence (7.5k), Animosity (7.5k), Vortex (7.5k)
- Melee Arcane Adapter: 50k standing
- Necramech mods: Various (10k-28k standing)
- Blueprints: Qorvex (50k), Grimoire (50k), Ekhein (15k), Helminth Coalescent Segment (30k)
- Eidolon Lenses: All 5 schools at 60k each
- Captura scenes and sigils (non-tradeable)

### Best Cavia Buys (verified prices)
1. Melee Exposure — 31p avg, 85/day volume, 4.16p/1k standing (BEST)
2. Melee Influence — 29p avg, 187/day volume, 3.92p/1k standing
3. Melee Vortex — 29p avg, 15/day volume, 3.87p/1k standing
4. Melee Animosity — 28p avg, 17/day volume, 3.76p/1k standing

### Infrastructure
- Added DuckDuckGo MCP server (free web search, no API key)
- Added Brave Search MCP server (better quality search, 2000 queries/month free)
- Added Bright Data MCP server (Cloudflare bypass, 5000 requests/month free)
- Updated INSTRUCTIONS.md with research priority order and critical rules
- Created this CHANGELOG.md

### Lesson Learned
NEVER guess which items come from which syndicate/vendor based on AI training data. ALWAYS verify from wiki.warframe.com first. The Warframe item economy has many vendors across different open worlds and updates, and items can come from unexpected sources.

## 2026-03-21

### Initial Setup
- Created warframe-market-mcp server with 5 tools
- Created syndicate_analyzer.py
- Scraped syndicate mods from wiki.warframe.com → syndicate_mods_wiki.json (410 mods)
- Initial syndicate rankings generated
