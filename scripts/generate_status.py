#!/usr/bin/env python3
"""
Generates website/status.html without sending any alerts or emails.
Used by GitHub Actions to publish a live status page on GitHub Pages.
No credentials required — only yfinance + requests.
"""

import sys
from pathlib import Path

# Allow importing from the same scripts/ directory
sys.path.insert(0, str(Path(__file__).parent))

from market_monitor import fetch_price_data, evaluate, generate_status_html

closes = fetch_price_data()
_alerts, all_statuses, raw = evaluate(closes)
generate_status_html(all_statuses, raw)
print("status.html updated.")
