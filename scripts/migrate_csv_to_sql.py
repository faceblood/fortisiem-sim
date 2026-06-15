#!/usr/bin/env python3
"""One-shot CSV → SQLite import. Delegates to fortisiem_sim.db.import_csv."""
from __future__ import annotations

from fortisiem_sim.db.import_csv import main

if __name__ == "__main__":
    raise SystemExit(main())
