#!/usr/bin/env python3
"""Print a local cache summary for the stock screener project."""

from __future__ import annotations

import json

from backend.service import get_cache_summary


def main() -> None:
    summary = get_cache_summary()
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
