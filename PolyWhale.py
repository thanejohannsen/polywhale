import requests
import json
import time as time_mod
import threading
import tkinter as tk
from tkinter import ttk
from datetime import datetime, timezone

# Load qualified whales from WhaleStrategy output
with open("qualified_whales.json", "r") as f:
    qualified_whales = json.load(f)


def fetch_open_positions():
    """Fetch open positions directly via the positions API (1 call per whale)."""
    market_agg = {}

    for whale in qualified_whales:
        username = whale["username"]
        address = whale["address"]
        roi = whale["roi"]

        try:
            resp = requests.get(
                f"https://data-api.polymarket.com/positions?user={address}&sizeThreshold=0&limit=500",
                timeout=15,
            )
        except requests.RequestException:
            continue
        if resp.status_code != 200:
            continue

        positions = resp.json()
        for pos in positions:
            cur_price = float(pos.get("curPrice", 0))
            current_value = float(pos.get("currentValue", 0))
            if cur_price <= 0.01 or cur_price >= 0.99 or current_value <= 0:
                continue

            title = pos.get("title") or "Unknown market"
            outcome = pos.get("outcome") or "N/A"
            slug = pos.get("slug", "")
            invested = float(pos.get("totalBought", 0))
            avg_price = float(pos.get("avgPrice", 0))

            mkey = (title, outcome, slug)
            if mkey not in market_agg:
                market_agg[mkey] = {
                    "whales": [],
                    "total_invested": 0,
                    "cur_price": cur_price,
                    "slug": slug,
                }
            market_agg[mkey]["whales"].append({
                "name": username,
                "roi": roi,
                "invested": invested,
                "avg_price": avg_price,
            })
            market_agg[mkey]["total_invested"] += invested
            # Keep the most recent current price
            market_agg[mkey]["cur_price"] = cur_price

        time_mod.sleep(0.15)

    # Broad category labels to prefer when a market has multiple tags
    BROAD_CATEGORIES = {
        "sports", "politics", "crypto", "finance", "science", "tech",
        "entertainment", "pop culture", "world", "business", "geopolitics",
        "economy", "climate", "health", "ai", "gaming", "music", "culture",
    }

    # Collect unique slugs that pass the $50k filter, then batch-lookup categories
    # Two-step: market slug -> event slug -> event tags
    slug_to_category = {}
    qualifying = [(key, info) for key, info in market_agg.items() if info["total_invested"] >= 50000]

    for (title, outcome, slug), info in qualifying:
        if slug and slug not in slug_to_category:
            try:
                # Step 1: get the event slug from the market
                resp = requests.get(
                    f"https://gamma-api.polymarket.com/markets?slug={slug}",
                    timeout=10,
                )
                event_slug = None
                if resp.status_code == 200:
                    markets = resp.json()
                    if markets:
                        events = markets[0].get("events") or []
                        if events:
                            event_slug = events[0].get("slug")

                # Step 2: fetch the event by its own slug to get tags
                if event_slug:
                    resp2 = requests.get(
                        f"https://gamma-api.polymarket.com/events?slug={event_slug}",
                        timeout=10,
                    )
                    if resp2.status_code == 200:
                        event_data = resp2.json()
                        if event_data:
                            tags = event_data[0].get("tags") or []
                            labels = [t.get("label", "") for t in tags
                                      if t.get("label", "").lower() not in ("all", "featured")]
                            cat = next((l for l in labels if l.lower() in BROAD_CATEGORIES), "")
                            if not cat and labels:
                                cat = labels[0]
                            slug_to_category[slug] = cat.strip().title() if cat else "Other"
                        else:
                            slug_to_category[slug] = "Other"
                    else:
                        slug_to_category[slug] = "Other"
                else:
                    slug_to_category[slug] = "Other"
            except requests.RequestException:
                slug_to_category[slug] = "Other"
            time_mod.sleep(0.1)

    # Build results
    results = []
    for (title, outcome, slug), info in qualifying:

        info["whales"].sort(key=lambda w: -w["invested"])

        results.append({
            "title": title,
            "outcome": outcome,
            "whales": info["whales"],
            "total_invested": info["total_invested"],
            "cur_price": info["cur_price"],
            "category": slug_to_category.get(slug, "Other"),
        })

    results.sort(key=lambda r: -r["total_invested"])
    return results


class WhaleWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Polymarket Whale Positions")
        self.root.geometry("960x720")
        self.root.configure(bg="#1a1a2e")
        self.root.minsize(800, 500)

        self.all_results = []
        self.selected_category = tk.StringVar(value="All")

        # Header
        header = tk.Frame(self.root, bg="#16213e", pady=10)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text="POLYMARKET WHALE POSITIONS",
            font=("Consolas", 16, "bold"),
            fg="#00d4ff",
            bg="#16213e",
        ).pack()
        self.status_label = tk.Label(
            header,
            text="Loading...",
            font=("Consolas", 10),
            fg="#888888",
            bg="#16213e",
        )
        self.status_label.pack()

        tk.Label(
            header,
            text=f"Tracking {len(qualified_whales)} whales  |  Min $50,000 per market  |  Refreshes every 60s",
            font=("Consolas", 9),
            fg="#666666",
            bg="#16213e",
        ).pack()

        # Category filter bar
        filter_bar = tk.Frame(self.root, bg="#16213e", pady=6)
        filter_bar.pack(fill=tk.X)

        tk.Label(
            filter_bar,
            text="  Category:",
            font=("Consolas", 10, "bold"),
            fg="#cccccc",
            bg="#16213e",
        ).pack(side=tk.LEFT, padx=(10, 4))

        self.category_combo = ttk.Combobox(
            filter_bar,
            textvariable=self.selected_category,
            state="readonly",
            values=["All"],
            width=20,
            font=("Consolas", 10),
        )
        self.category_combo.pack(side=tk.LEFT, padx=4)
        self.category_combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filter())

        self.filter_count_label = tk.Label(
            filter_bar,
            text="",
            font=("Consolas", 9),
            fg="#888888",
            bg="#16213e",
        )
        self.filter_count_label.pack(side=tk.LEFT, padx=10)

        # Scrollable content area
        container = tk.Frame(self.root, bg="#1a1a2e")
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        self.canvas = tk.Canvas(container, bg="#1a1a2e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=self.canvas.yview)
        self.scrollable = tk.Frame(self.canvas, bg="#1a1a2e")

        self.scrollable.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.bind("<Configure>", self._on_canvas_resize)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        self.refresh()
        self.root.mainloop()

    def _on_canvas_resize(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    def refresh(self):
        self.status_label.config(text="Refreshing...", fg="#ffaa00")
        threading.Thread(target=self._fetch_and_update, daemon=True).start()

    def _fetch_and_update(self):
        try:
            results = fetch_open_positions()
            self.root.after(0, self._on_data_ready, results)
        except Exception as e:
            self.root.after(0, self._show_error, str(e))

    def _show_error(self, msg):
        now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self.status_label.config(text=f"Error at {now}: {msg}", fg="#ff4444")
        self.root.after(60000, self.refresh)

    def _on_data_ready(self, results):
        self.all_results = results

        # Update category dropdown
        categories = sorted(set(r["category"] for r in results))
        self.category_combo["values"] = ["All"] + categories
        # Keep current selection if still valid
        if self.selected_category.get() not in (["All"] + categories):
            self.selected_category.set("All")

        self._apply_filter()

        now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        self.status_label.config(
            text=f"Last updated: {now}  |  {len(results)} markets",
            fg="#44ff44",
        )
        self.root.after(60000, self.refresh)

    def _apply_filter(self):
        selected = self.selected_category.get()
        if selected == "All":
            filtered = self.all_results
        else:
            filtered = [r for r in self.all_results if r["category"] == selected]

        self.filter_count_label.config(
            text=f"Showing {len(filtered)} of {len(self.all_results)} markets"
        )
        self._render(filtered)

    def _render(self, results):
        for widget in self.scrollable.winfo_children():
            widget.destroy()

        if not results:
            tk.Label(
                self.scrollable,
                text="No markets match the current filter.",
                font=("Consolas", 12),
                fg="#888888",
                bg="#1a1a2e",
                pady=30,
            ).pack()
        else:
            for r in results:
                self._render_market(r)

    def _render_market(self, market):
        card = tk.Frame(self.scrollable, bg="#0f3460", bd=1, relief=tk.RIDGE)
        card.pack(fill=tk.X, pady=4, padx=2)

        # Top row: title + total invested
        title_frame = tk.Frame(card, bg="#0f3460", pady=6, padx=10)
        title_frame.pack(fill=tk.X)

        tk.Label(
            title_frame,
            text=market["title"],
            font=("Consolas", 11, "bold"),
            fg="#ffffff",
            bg="#0f3460",
            anchor="w",
            wraplength=650,
            justify=tk.LEFT,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(
            title_frame,
            text=f"${market['total_invested']:,.0f}",
            font=("Consolas", 12, "bold"),
            fg="#00d4ff",
            bg="#0f3460",
        ).pack(side=tk.RIGHT)

        # Outcome + current odds + category row
        info_frame = tk.Frame(card, bg="#0f3460", padx=10)
        info_frame.pack(fill=tk.X)

        cur_odds = market["cur_price"]
        cur_pct = f"{cur_odds * 100:.0f}%" if cur_odds else "N/A"

        tk.Label(
            info_frame,
            text=f"  {market['outcome']}",
            font=("Consolas", 9, "bold"),
            fg="#cccccc",
            bg="#0f3460",
            anchor="w",
        ).pack(side=tk.LEFT)

        tk.Label(
            info_frame,
            text=f"  Current Odds: {cur_pct}",
            font=("Consolas", 9, "bold"),
            fg="#ffdd57",
            bg="#0f3460",
        ).pack(side=tk.LEFT, padx=(10, 0))

        tk.Label(
            info_frame,
            text=market["category"],
            font=("Consolas", 8),
            fg="#888888",
            bg="#0f3460",
            anchor="e",
        ).pack(side=tk.RIGHT)

        # Whale list
        whale_frame = tk.Frame(card, bg="#0a2647", padx=10, pady=4)
        whale_frame.pack(fill=tk.X, padx=6, pady=(2, 6))

        for w in market["whales"]:
            row = tk.Frame(whale_frame, bg="#0a2647")
            row.pack(fill=tk.X, pady=1)

            tk.Label(
                row,
                text=f"  {w['name']}",
                font=("Consolas", 9, "bold"),
                fg="#e0e0e0",
                bg="#0a2647",
                anchor="w",
                width=24,
            ).pack(side=tk.LEFT)

            entry_pct = f"{w['avg_price'] * 100:.0f}%" if w["avg_price"] else "N/A"
            tk.Label(
                row,
                text=f"Bought @ {entry_pct}",
                font=("Consolas", 9),
                fg="#ff9f43",
                bg="#0a2647",
                width=14,
            ).pack(side=tk.LEFT)

            tk.Label(
                row,
                text=f"ROI: {w['roi']:.0f}%",
                font=("Consolas", 9),
                fg="#44ff44" if w["roi"] > 50 else "#ffaa00",
                bg="#0a2647",
                width=10,
            ).pack(side=tk.LEFT)

            tk.Label(
                row,
                text=f"${w['invested']:,.0f}",
                font=("Consolas", 9),
                fg="#00d4ff",
                bg="#0a2647",
                anchor="e",
            ).pack(side=tk.RIGHT)


if __name__ == "__main__":
    WhaleWindow()
