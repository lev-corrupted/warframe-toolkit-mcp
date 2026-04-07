# Warframe Toolkit

## READ THIS FIRST — EVERY TIME
Before making ANY changes, running ANY analysis, or giving ANY recommendations, read this entire file.

## What This Project Does
Unified Warframe tooling for Linux — market analysis, syndicate profitability, and relic reward scanning.

### Components
- **MCP Server** (`server.py`): Gives Claude direct access to warframe.market for price checks, item search, trending items, and statistics.
- **Syndicate Analyzer** (`syndicate_analyzer.py`): Scans all 6 syndicates, filters mods by daily sales volume, and ranks them by profitability.
- **Wiki Scraper** (`wiki_scraper.py`): Scrapes wiki.warframe.com for accurate syndicate offerings.
- **Wiki JSON** (`syndicate_mods_wiki.json`): Mod lists scraped from wiki — the SOURCE OF TRUTH for what syndicates sell.
- **wfinfo-ng** (`wfinfo-ng/`): Rust-based relic reward screen scanner for Linux. Detects relic rewards via OCR and shows platinum values. Binary installed at `~/.cargo/bin/wfinfo`.

## CRITICAL RULES

### Rule 1: NEVER GUESS MOD/ITEM SOURCES
- DO NOT assume which mods belong to which syndicate from AI training data
- ALWAYS verify from wiki.warframe.com or by searching with DuckDuckGo/Brave before claiming anything
- If you can't verify, SAY SO — don't make up data
- Past mistakes that must never repeat:
  - Listed "Acid Shells" as Steel Meridian offering — actually drops from Kela de Thaym boss
  - Listed "Primary Blight" as Cavia offering — actually from Nightcap (Holdfasts) or Duviri bounties
  - Listed "Reinforced Bond" as Cavia offering — actually from The Business (Solaris United/Fortuna)
  - Entire Cavia analysis was wrong because items were not verified from wiki
  - Listed Banshee/Garuda/Hildryn/Mesa/Ivara augments as Arbiters of Hexis — they belong to other syndicates

### Rule 2: Two-Source Verification System

**For FACTS** (drop locations, syndicate offerings, standing costs, patch notes):
1. **wiki.warframe.com** (official wiki) — PRIMARY source, use Fetch MCP or Playwright
   - Syndicate augment table: `https://wiki.warframe.com/w/Syndicate#Warframe_Augment_Mods`
   - Individual syndicate pages: `https://wiki.warframe.com/w/Arbiters_of_Hexis` (has full offerings list)
   - ALWAYS use this table to verify which syndicate sells which augment — each warframe's augments are split between TWO syndicates
2. **DuckDuckGo MCP** — quick search to find the right wiki page or verify a fact
3. **warframe.market API v2** — for LIVE pricing data only (not for source/drop information)
4. **NEVER use AI memory/training data** for specific game data

**For OPINIONS** (weapon tiers, builds, meta picks, what to farm, weekly priorities):
1. **Gaz TV** — https://www.youtube.com/@GazTTV — Primary opinion source for Incarnon tier lists, weekly rotation picks, endgame meta. Download video transcripts via yt-dlp.
2. **MHBlacky** — https://www.youtube.com/@MHBlacky_ENG — Secondary opinion source for builds, tier lists, pro-level gameplay analysis. Download video transcripts via yt-dlp.
3. These are professional endgame players — their opinions override generic tier list websites
4. **Weekly:** Always check Gaz TV's latest Incarnon rotation video and share his picks
5. **NEVER assume** weapon quality or meta status from AI training data (e.g. called Soma "popular" when it's B-tier)

**For BROWSING** (any research):
- Brave Search MCP — for YouTube video searches, Reddit discussions, patch notes
- Bright Data MCP — for Cloudflare-blocked sites (Fandom wiki fallback)
- Playwright MCP — for data-heavy pages, tables, dynamic content
- yt-dlp transcript download — for "reading" YouTube video content

### Rule 3: Verify Before Recommending
- Before telling the user "buy X from Y syndicate", verify:
  1. Does Y syndicate actually sell X? (check wiki)
  2. What does X cost in standing? (check wiki)
  3. What is X selling for on warframe.market? (check API)
  4. How often does X sell? (check 7-day volume)
- If any step fails, DO NOT recommend — tell user you need to verify

### Rule 4: Price Analysis Rules
- Always filter by volume (minimum 2 sales/day) for "profitable" recommendations
- **v1 statistics endpoint avg_price is UNRELIABLE** — it includes outliers and old data that inflates averages (e.g. showed Melee Influence at 55p when real price was 3-4p). Always cross-check with live orders from v2.
- **Avg price method:** Bottom 5 online/ingame sellers averaged. Top 10 or median inflates because of overpriced listings that never sell. Bottom 5 matches the warframe.market SMA line.
- Calculate efficiency as plat per 1,000 standing spent
- Note: Some items are one-time purchases (blueprints), others are repeatable (mods/arcanes)
- Standing costs vary by syndicate and rank — verify from wiki, don't guess

## API Details
- **warframe.market v2**: `https://api.warframe.market/v2`
- **warframe.market v1 stats**: `https://api.warframe.market/v1/items/{slug}/statistics`
- v1 is dead for orders but the statistics endpoint still works for 90-day history
- v2 field names: `type` (not `order_type`), `ingameName` (not `ingame_name`), `rank` (not `mod_rank`)

## Syndicate Alliance System
```
Steel Meridian  <--->  Red Veil       (allies, level together)
Arbiters of Hexis <---> Cephalon Suda (allies, level together)
New Loka <---> Perrin Sequence        (allies, level together)

Steel Meridian OPPOSES New Loka & Perrin Sequence
Arbiters of Hexis OPPOSES Perrin Sequence & Red Veil
Cephalon Suda OPPOSES New Loka & Red Veil
```
You can maintain 2 allied syndicates at max rank simultaneously.

## Non-Main Syndicates (Different Standing Systems)
These have their own standing and vendors — DO NOT mix up with the 6 main syndicates:
- **Cavia** (Whispers in the Walls) — Vendor: Bird 3, uses Cavia standing
  - Best items: Melee Arcanes (Exposure ~31p, Influence ~29p, Vortex ~29p, Animosity ~28p)
  - These have massive volume (Melee Influence: 187 sales/day as of 2026-03-23)
  - Also sells: Necramech mods, Qorvex/Grimoire/Ekhein blueprints, Eidolon Lenses
  - Loid (Original) handles Voca trade-ins + Arcane Dissolution (costs Vosfor, NOT standing)
- **Ostron** (Plains of Eidolon) — Vendor: various Cetus NPCs
- **Solaris United** (Fortuna) — Vendor: The Business, Legs, Zuud, etc.
- **Entrati** (Deimos) — Vendor: various Necralisk NPCs
- **Holdfasts** (Zariman) — Vendor: various Zariman NPCs
- **Kahl's Garrison** — Vendor: Chipper
- **The Hex** (1999) — Vendor: various 1999 NPCs

## How to Use (via Claude Code MCP)
All tools are accessed through Claude Code. Just ask naturally:
- "syndicate lookup Arbiters of Hexis"
- "best buys Cephalon Suda 132000"
- "price check Condition Overload"
- "price history Red Veil"

## How to Update Verified Data
1. Fetch `wiki.warframe.com/w/Syndicate#Warframe_Augment_Mods`
2. Parse the augment table and rebuild `syndicate_mods_verified.json`
3. Add entry to CHANGELOG.md with date, what changed, what was learned

## Changelog Policy
After EVERY session where changes are made or new findings discovered:
1. Add entry to CHANGELOG.md with date
2. If mod assignments were wrong, note the correction with what was wrong and what is correct
3. If prices shifted significantly, note the trend
4. If new items were added to the game (new Prime, new update), note them
5. If the user corrects any information, document the correction

## MCP Server Tools (13 total)

**Market:** price_check, price_check_multiple, search_items, trending_items, item_statistics
**Syndicate:** syndicate_lookup, best_buys, price_history
**World State:** fissure_sniper, world_state_dashboard, baro_tracker
**Arbitrage:** market_spread_finder, riven_price_estimator

## YouTube Transcript Tool
```bash
# Read any YouTube video's spoken content as text
python youtube_transcript.py "https://youtube.com/watch?v=xxx"

# Save to file instead of stdout
python youtube_transcript.py "https://youtube.com/watch?v=xxx" --save
```

## Trusted Content Creators (Opinion Sources)

| Creator | Channel | Use For |
|---------|---------|---------|
| **Gaz TV** | youtube.com/@GazTTV | Incarnon tier lists, weekly rotation picks, endgame meta, general opinions |
| **MHBlacky** | youtube.com/@MHBlacky_ENG | Builds, weapon reviews, tier lists, pro-level gameplay |

**How to check their opinions:**
1. Search YouTube: `"[topic] Gaz TV"` or `"[topic] MHBlacky"`
2. Download transcript: `python youtube_transcript.py "https://youtube.com/watch?v=VIDEO_ID"`
3. Read transcript for their take
4. Combine with wiki facts for complete answer

**Weekly routine:** Every Monday, search for Gaz TV's latest Incarnon rotation video and read his picks.

## Files
```
server.py                     # MCP server (16 tools)
syndicate_mods_verified.json  # Wiki-verified syndicate->mod mapping (SOURCE OF TRUTH)
youtube_transcript.py         # YouTube subtitle downloader/parser
price_history.json            # Price tracking across scans (auto-generated)
INSTRUCTIONS.md               # THIS FILE (internal dev notes)
CHANGELOG.md                  # All changes and corrections log
README.md                     # Public-facing documentation
```

## Setup
```bash
pip install mcp requests

# wfinfo-ng
sudo pacman -S tesseract libxrandr curl jq
cd wfinfo-ng && cargo install --path . --bin wfinfo
```
MCP server configured in `~/.claude/settings.json` under `warframe-market`.

## MCP Research Tools Available
| Tool | Purpose | Cost |
|------|---------|------|
| DuckDuckGo MCP | Free web search, no API key | Free |
| Brave Search MCP | Better quality search | Free (2000/month) |
| Bright Data MCP | Cloudflare bypass, scraping | Free (5000/month) |
| Playwright MCP | Full browser automation | Free |
| Read Website MCP | Fast page content extraction | Free |
| Fetch MCP | Basic URL fetching | Free |
| Context7 MCP | Library documentation lookup | Free |

## Last Verified Data
- Syndicate mods wiki scrape: 2026-03-21
- Syndicate augment table verified: 2026-03-28 (wiki.warframe.com/w/Syndicate#Warframe_Augment_Mods)
- Arbiters of Hexis offerings verified: 2026-03-28 (61 warframe augments + 4 weapon augments)
- Cavia (Bird 3) offerings verified: 2026-03-23
- Next recommended update: After next major Warframe update or monthly
