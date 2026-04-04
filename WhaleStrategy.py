import requests
import json
from collections import defaultdict
import time as time_mod

# Get top 10 most profitable users
url = "https://data-api.polymarket.com/v1/leaderboard?category=OVERALL&timePeriod=MONTH&orderBy=PNL&limit=30"
leaderboard_resp = requests.get(url)
top_users = leaderboard_resp.json()

all_whale_data = []

for i, user in enumerate(top_users, 1):
    username = user.get("userName", "Anonymous")
    pnl = float(user.get("pnl", 0))
    address = user.get("proxyWallet") or user.get("userAddress", "")

    # Get closed positions (redeemed — mostly wins)
    closed_resp = requests.get(f"https://data-api.polymarket.com/closed-positions?user={address}&limit=500")
    closed = closed_resp.json() if closed_resp.status_code == 200 else []

    # Get ALL activity with pagination to find every market they traded
    all_activity = []
    offset = 0
    while True:
        activity_resp = requests.get(
            f"https://data-api.polymarket.com/activity?user={address}&limit=200&offset={offset}"
        )
        if activity_resp.status_code != 200:
            break
        batch = activity_resp.json()
        if not batch:
            break
        all_activity.extend(batch)
        if len(batch) < 200:
            break
        offset += 200
        time_mod.sleep(0.2)

    # Get open positions
    positions_resp = requests.get(f"https://data-api.polymarket.com/positions?user={address}&limit=500")
    positions = positions_resp.json() if positions_resp.status_code == 200 else []

    # --- Cross-reference to find hidden losses ---
    # Group BUY trades by conditionId to find all unique markets entered
    buys_by_condition = defaultdict(lambda: {"total_spent": 0, "size": 0, "title": "", "outcome": "", "slug": "", "avg_price": 0, "count": 0})
    sells_by_condition = defaultdict(lambda: {"total_received": 0, "size": 0})
    for trade in all_activity:
        cid = trade.get("conditionId", "")
        if not cid:
            continue
        side = str(trade.get("side", "")).upper()
        if side == "BUY":
            spent = float(trade.get("usdcSize", 0))
            size = float(trade.get("size", 0))
            price = float(trade.get("price", 0))
            buys_by_condition[cid]["total_spent"] += spent
            buys_by_condition[cid]["size"] += size
            buys_by_condition[cid]["count"] += 1
            buys_by_condition[cid]["avg_price"] = (buys_by_condition[cid]["avg_price"] * (buys_by_condition[cid]["count"] - 1) + price) / buys_by_condition[cid]["count"]
            if not buys_by_condition[cid]["title"]:
                buys_by_condition[cid]["title"] = trade.get("title", "")
                buys_by_condition[cid]["outcome"] = trade.get("outcome", "")
                buys_by_condition[cid]["slug"] = trade.get("slug", "")
        elif side == "SELL":
            sells_by_condition[cid]["total_received"] += float(trade.get("usdcSize", 0))
            sells_by_condition[cid]["size"] += float(trade.get("size", 0))

    # Closed position conditionIds (already accounted for)
    closed_cids = set(p.get("conditionId", "") for p in closed)

    # Open position conditionIds — split into truly active vs. dead ($0 value = lost)
    dead_positions = [p for p in positions if float(p.get("curPrice", 1)) == 0 or float(p.get("currentValue", 1)) == 0]
    alive_positions = [p for p in positions if float(p.get("curPrice", 1)) > 0 and float(p.get("currentValue", 1)) > 0]
    open_cids = set(p.get("conditionId", "") for p in alive_positions)

    # Dead position conditionIds (already counted as losses directly)
    dead_cids = set(p.get("conditionId", "") for p in dead_positions)

    # Markets they bought into but are NOT in closed, NOT open, NOT already dead = potential hidden losses
    hidden_loss_cids = set(buys_by_condition.keys()) - closed_cids - open_cids - dead_cids

    # Check market status for each hidden position
    hidden_losses = []

    # First, add dead "open" positions ($0 value) directly as losses
    for dp in dead_positions:
        cid = dp.get("conditionId", "")
        total_bought = float(dp.get("totalBought", 0))
        cash_pnl = float(dp.get("cashPnl", 0))
        # Use cashPnl if available (negative = loss), otherwise use totalBought
        net_loss = abs(cash_pnl) if cash_pnl < 0 else total_bought
        if net_loss > 0:
            hidden_losses.append({
                "conditionId": cid,
                "title": dp.get("title", ""),
                "outcome": dp.get("outcome", ""),
                "total_spent": net_loss,
                "avg_price": float(dp.get("avgPrice", 0)),
                "slug": dp.get("slug", ""),
                "source": "dead_open",
            })

    # Then check unaccounted markets from activity
    for cid in hidden_loss_cids:
        info = buys_by_condition[cid]
        slug = info["slug"]
        if not slug:
            continue

        # Check if market is closed/resolved
        try:
            market_resp = requests.get(f"https://gamma-api.polymarket.com/markets?slug={slug}")
            if market_resp.status_code == 200:
                markets = market_resp.json()
                if markets:
                    m = markets[0]
                    if m.get("closed"):
                        # Market resolved — this is a hidden loss (they bought but didn't redeem)
                        # Subtract any sells they made before expiry
                        sell_recovered = sells_by_condition.get(cid, {}).get("total_received", 0)
                        net_loss = info["total_spent"] - sell_recovered
                        if net_loss > 0:  # Only count if they actually lost money
                            hidden_losses.append({
                                "conditionId": cid,
                                "title": info["title"],
                                "outcome": info["outcome"],
                                "total_spent": net_loss,
                                "avg_price": info["avg_price"],
                                "slug": slug,
                                "source": "activity_cross_ref",
                            })
        except:
            pass
        time_mod.sleep(0.1)

    all_whale_data.append({
        "rank": i,
        "username": username,
        "pnl": pnl,
        "address": address,
        "closed": closed,
        "activity": all_activity,
        "positions": positions,
        "hidden_losses": hidden_losses,
        "buys_by_condition": buys_by_condition,
    })

    print(f"  Fetched #{i} {username}...")

# --- Filter to whales with TRUE ROI > 30% ---
print("\n" + "=" * 80)
print("WHALES WITH TRUE ROI > 30%")
print("=" * 80)

qualified = []
for whale in all_whale_data:
    closed = whale["closed"]
    hidden_losses = whale["hidden_losses"]
    if not closed and not hidden_losses:
        continue

    wins = [p for p in closed if float(p.get("realizedPnl", 0)) > 0]
    redeemed_losses = [p for p in closed if float(p.get("realizedPnl", 0)) <= 0]
    total_hidden_loss_amount = sum(l["total_spent"] for l in hidden_losses)

    total_invested = sum(float(p.get("totalBought", 0)) for p in closed) + total_hidden_loss_amount
    total_pnl = sum(float(p.get("realizedPnl", 0)) for p in closed) - total_hidden_loss_amount
    roi = total_pnl / total_invested * 100 if total_invested > 0 else 0

    all_losses_count = len(redeemed_losses) + len(hidden_losses)
    total = len(wins) + all_losses_count
    win_rate = len(wins) / total * 100 if total > 0 else 0

    if roi > 30:
        qualified.append({
            "rank": whale["rank"],
            "username": whale["username"],
            "address": whale["address"],
            "pnl": whale["pnl"],
            "roi": roi,
            "win_rate": win_rate,
            "wins": len(wins),
            "losses": all_losses_count,
            "total_invested": total_invested,
            "total_pnl": total_pnl,
            "hidden_losses": len(hidden_losses),
        })

if not qualified:
    print("\n  No whales found with TRUE ROI > 30%.")
else:
    for q in qualified:
        print(f"\n  #{q['rank']} {q['username']}")
        print(f"    Address:        {q['address']}")
        print(f"    Monthly PnL:    ${q['pnl']:,.2f}")
        print(f"    TRUE ROI:       {q['roi']:.1f}%")
        print(f"    TRUE Win Rate:  {q['win_rate']:.1f}% ({q['wins']}W / {q['losses']}L)")
        print(f"    Invested:       ${q['total_invested']:,.2f}")
        print(f"    Profit:         ${q['total_pnl']:,.2f}")
        print(f"    Hidden Losses:  {q['hidden_losses']}")
    print(f"\n  {len(qualified)} out of {len(all_whale_data)} whales qualify.")

# --- Save qualified whales to JSON for use in other scripts ---
save_path = "qualified_whales.json"
with open(save_path, "w") as f:
    json.dump(qualified, f, indent=2)
print(f"\nSaved {len(qualified)} qualified whales to {save_path}")
