import requests
from datetime import datetime, timezone

# Step 1: Get top 20 most profitable users over the past month
print("Fetching top 20 whales from leaderboard...")
url = "https://data-api.polymarket.com/v1/leaderboard?category=OVERALL&timePeriod=MONTH&orderBy=PNL&limit=20"
leaderboard_resp = requests.get(url)
top_users = leaderboard_resp.json()

print("=" * 90)
print(f"HISTORICAL WIN RATES — TOP 20 POLYMARKET WHALES")
print("=" * 90)

for i, user in enumerate(top_users, 1):
    username = user.get("userName", "Anonymous")
    pnl = user.get("pnl", 0)
    address = user.get("proxyWallet") or user.get("userAddress", "")

    # Step 2: Fetch closed positions (settled trades) for this user
    closed_resp = requests.get(
        f"https://data-api.polymarket.com/closed-positions?user={address}&limit=200"
    )
    if closed_resp.status_code != 200:
        continue

    positions = closed_resp.json()
    if not positions:
        continue

    wins = 0
    losses = 0
    total_profit = 0.0
    total_invested = 0.0

    for pos in positions:
        pnl_val = float(pos.get("realizedPnl", 0))
        bought = float(pos.get("totalBought", 0))
        total_profit += pnl_val
        total_invested += bought

        if pnl_val > 0:
            wins += 1
        else:
            losses += 1

    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    roi = (total_profit / total_invested * 100) if total_invested > 0 else 0

    print(f"\n{'─' * 90}")
    print(f"#{i} | {username} | Monthly PnL: ${float(user.get('pnl', 0)):,.2f}")
    print(f"  Closed Positions: {total_trades} | Wins: {wins} | Losses: {losses} | Win Rate: {win_rate:.1f}%")
    print(f"  Total Invested: ${total_invested:,.2f} | Total Profit: ${total_profit:,.2f} | ROI: {roi:.1f}%")

    # Show last 5 closed positions
    print(f"  Recent settled trades:")
    for pos in positions[:5]:
        title = pos.get("title", "Unknown")
        outcome = pos.get("outcome", "N/A")
        rpnl = float(pos.get("realizedPnl", 0))
        avg_price = float(pos.get("avgPrice", 0))
        bought = float(pos.get("totalBought", 0))
        end_date = pos.get("endDate", "")[:10]
        result = "WIN" if rpnl > 0 else "LOSS"

        print(f"    {result:4s} | ${rpnl:>+12,.2f} | Bought: ${bought:>12,.2f} @ {avg_price:.2f} | {title} → {outcome} | {end_date}")

print(f"\n{'=' * 90}")
