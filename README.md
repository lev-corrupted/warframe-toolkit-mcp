# warframe-toolkit-mcp

MCP server for Warframe market analysis -- syndicate profitability, price tracking, and trading insights, powered by warframe.market API.

Built as a [Model Context Protocol](https://modelcontextprotocol.io/) server that gives AI assistants (Claude, etc.) direct access to live Warframe market data. Ask your AI to price check items, find the best syndicate mods to sell, track price trends, and more.

## Features

### Market Tools

- **price_check** -- Look up the current price of any tradeable item. Returns the cheapest sell orders from online/in-game players with average price stats. Works for mods, prime parts, arcanes, sets, blueprints, and more.

- **search_items** -- Search for Warframe items by name when you are not sure of the exact spelling. Returns matching items with their market slugs and tags.

- **price_check_multiple** -- Check prices for multiple items at once with comma-separated names. Great for comparing values from a screenshot or batch lookups.

- **trending_items** -- See the most actively traded items on warframe.market right now based on recent order volume.

- **item_statistics** -- Get detailed 48-hour and 90-day price history for any item, including volume, min/max, and median prices.

### Syndicate Tools

- **syndicate_lookup** -- Look up all verified mods for a syndicate with live prices, sorted into profit tiers (20p+, 15-19p, 10-14p, <10p). Uses wiki-verified data so nothing is guessed.

- **best_buys** -- Given your available standing, get an optimal shopping list ranked by platinum-per-standing efficiency. Tells you exactly which mods to buy and expected total profit.

- **price_history** -- Track how syndicate mod prices change over time across multiple scans. Shows biggest movers and overall market trend direction.

### World State Tools

- **fissure_sniper** -- Find the fastest active Void Fissures for relic cracking. Filters for Capture/Exterminate missions on Meso/Neo/Axi tiers only.

- **world_state_dashboard** -- Quick weekly endgame tracker. Shows Archon Hunt boss and missions, Duviri Cycle mood, and Sortie details in one view.

- **baro_tracker** -- Check Baro Ki'Teer's status. Shows arrival countdown (if gone) or full inventory with Ducat/Credit costs (if active).

### Arbitrage Tools

- **market_spread_finder** -- Find the flip margin between Buy and Sell orders for any item. Shows highest buy offer, lowest sell listing, and platinum profit spread.

- **riven_price_estimator** -- Find baseline prices for unrolled Rivens for any weapon. Searches warframe.market auctions filtered to 0-roll Rivens with buyout prices.

### Analytics Tools

- **frame_popularity** -- Check any warframe's official usage stats from warframe.com. Shows 2025 vs 2024 usage, year-over-year trend, ranking out of 113 frames, and per-mastery-rank breakdown. Shows top 30 when no frame specified.

- **market_intelligence** -- Deep market analysis combining DE official popularity data with live prices and syndicate mod data. Finds rising frames (mod demand growing), crashing frames (cheap investment opportunities), undervalued mods (popular frame but cheap augments = fast sales), and niche profit mods (rare frame but expensive augments). Also shows cheapest prime sets for MR grinding.

## Installation

### Requirements

- Python 3.10+

### Install dependencies

```bash
cd warframe-toolkit-mcp
pip install -r requirements.txt
```

Or install as a package:

```bash
pip install -e .
```

### Run the server

```bash
python server.py
```

The server communicates over stdio using the MCP protocol.

## MCP Configuration

### Claude Code

Add this to your `~/.claude/settings.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "warframe-market": {
      "command": "python",
      "args": ["/path/to/warframe-toolkit-mcp/server.py"],
      "env": {}
    }
  }
}
```

Replace `/path/to/` with the actual path to where you cloned the repo.

### Claude Desktop

Add the same config block to your Claude Desktop MCP settings file.

## Usage Examples

**Price check a single item:**
> "What's the current price of Condition Overload?"

The `price_check` tool returns a table of the 10 cheapest sell orders with seller name, status, quantity, and overall average price.

**Batch price check:**
> "Price check Blind Rage, Primed Flow, and Narrow Minded"

The `price_check_multiple` tool returns a summary line for each item with low price, average, and order count.

**Search for an item:**
> "Search for Saryn Prime"

The `search_items` tool returns all matching items with their slugs and tags.

**Check trending items:**
> "What's hot on warframe.market right now?"

The `trending_items` tool returns the top 20 most actively traded items with order counts and average prices.

**Syndicate profitability:**
> "Show me all New Loka mods with prices"

The `syndicate_lookup` tool returns every verified mod grouped into profit tiers, with a summary of average prices and top earners.

**Optimal spending:**
> "I have 90,000 standing with Cephalon Suda, what should I buy?"

The `best_buys` tool returns a ranked shopping list sorted by plat-per-standing efficiency, with expected total platinum earned.

**Track price trends:**
> "How have Arbiters of Hexis mod prices changed?"

The `price_history` tool compares your latest scan to previous ones and highlights the biggest price movers.

**Find fast fissures:**
> "Any good fissures for cracking relics right now?"

The `fissure_sniper` tool filters active fissures to only Capture/Exterminate on Meso/Neo/Axi tiers.

**Weekly endgame check:**
> "What's the world state looking like?"

The `world_state_dashboard` tool shows Archon Hunt, Duviri Cycle, and Sortie in one view.

**Check Baro:**
> "Is Baro here? What's he selling?"

The `baro_tracker` tool shows his full inventory with Ducat/Credit prices, or countdown to arrival.

**Find flip opportunities:**
> "What's the spread on Condition Overload?"

The `market_spread_finder` tool shows the gap between buy offers and sell listings for arbitrage.

**Price an unrolled Riven:**
> "How much is an unrolled Rubico Riven worth?"

The `riven_price_estimator` tool finds the 5 cheapest 0-roll Rivens on the auction house.

## Screenshots

_Coming soon._

## Data Sources

- **Syndicate mods** -- Sourced from [wiki.warframe.com](https://wiki.warframe.com/) and stored in `syndicate_mods_verified.json`
- **Market prices and orders** -- [warframe.market API](https://warframe.market/) (v1 + v2)
- **World state, fissures, Baro** -- [WarframeStat.us API](https://docs.warframestat.us/)
- **Riven auctions** -- [warframe.market auctions API](https://warframe.market/)

## Credits

- [warframe.market](https://warframe.market/) -- market data and Riven auctions API
- [WarframeStat.us](https://warframestat.us/) -- live world state, fissures, Baro tracker
- [wiki.warframe.com](https://wiki.warframe.com/) -- verified syndicate mod lists

## License

MIT License. See [LICENSE](LICENSE) for details.
