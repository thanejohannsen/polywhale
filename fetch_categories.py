"""
Reads qualified_whales.json, fetches open positions for each whale,
then resolves categories for all $50k+ markets via the Gamma API.
Saves results to categories.json  (slug -> category label).
"""
import requests
import json
import time

BROAD_CATEGORIES = {
    "sports", "politics", "crypto", "finance", "science", "tech",
    "entertainment", "pop culture", "world", "business", "geopolitics",
    "economy", "climate", "health", "ai", "gaming", "music", "culture",
}

with open("qualified_whales.json") as f:
    whales = json.load(f)

# Collect slugs for markets with $50k+ whale investment
slug_totals = {}
for whale in whales:
    try:
        resp = requests.get(
            f"https://data-api.polymarket.com/positions?user={whale['address']}&sizeThreshold=0&limit=500",
            timeout=15,
        )
        if resp.status_code != 200:
            continue
        for pos in resp.json():
            cur_price = float(pos.get("curPrice", 0))
            cur_val   = float(pos.get("currentValue", 0))
            if cur_price <= 0.01 or cur_price >= 0.99 or cur_val <= 0:
                continue
            slug = pos.get("slug", "")
            invested = float(pos.get("totalBought", 0))
            if slug:
                slug_totals[slug] = slug_totals.get(slug, 0) + invested
    except Exception as e:
        print(f"  Warning: {whale['username']} positions failed: {e}")
    time.sleep(0.15)

qualifying_slugs = {slug for slug, total in slug_totals.items() if total >= 50000}
print(f"Fetching categories for {len(qualifying_slugs)} slugs...")

categories = {}
for slug in qualifying_slugs:
    try:
        # Fast path: try events?slug= directly first
        r = requests.get(f"https://gamma-api.polymarket.com/events?slug={slug}", timeout=10)
        tags = []
        if r.status_code == 200:
            data = r.json()
            if data:
                tags = data[0].get("tags") or []

        # Fallback: market -> embedded event slug -> event tags
        if not tags:
            r2 = requests.get(f"https://gamma-api.polymarket.com/markets?slug={slug}", timeout=10)
            if r2.status_code == 200:
                markets = r2.json()
                if markets:
                    events = markets[0].get("events") or []
                    if events:
                        event_slug = events[0].get("slug")
                        if event_slug and event_slug != slug:
                            r3 = requests.get(
                                f"https://gamma-api.polymarket.com/events?slug={event_slug}",
                                timeout=10,
                            )
                            if r3.status_code == 200:
                                data3 = r3.json()
                                if data3:
                                    tags = data3[0].get("tags") or []

        labels = [t.get("label", "") for t in tags
                  if t.get("label", "").lower() not in ("all", "featured")]
        broad = next((l for l in labels if l.lower() in BROAD_CATEGORIES), "")
        cat = broad or (labels[0] if labels else "")
        categories[slug] = cat.strip().title() if cat else "Other"
        print(f"  {slug[:50]:50s} -> {categories[slug]}")
    except Exception as e:
        print(f"  Warning: category lookup failed for {slug}: {e}")
        categories[slug] = "Other"
    time.sleep(0.15)

with open("categories.json", "w") as f:
    json.dump(categories, f, indent=2)

print(f"\nSaved {len(categories)} categories to categories.json")
