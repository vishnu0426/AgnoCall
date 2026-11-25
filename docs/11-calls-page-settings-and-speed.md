# Settings, Calls page, and why page switching was slow

## Why switching pages was slow (measured, not guessed)
1. **Next dev compiles each page on first visit**: 4-6 s (`/` 4.2 s, `/compliance` 6.2 s). Dev-only. Use `npm run build && npm run start` for real use.
2. **The database is a network hop away** (a remote host): ~75 ms per statement. A page costs (statements x 75 ms): dashboard 10-15 statements, analytics 13. Fixes: dashboard KPIs merged into one statement (10 -> 7, 15 -> 9), ingestion status 3 -> 1; and `app/core/response_cache.py` answers identical read-only GETs from memory for `RESPONSE_CACHE_SECONDS` (default 5, 0 = off). Any write empties it. Live: dashboard 807 ms -> 2 ms on the repeat view.
3. **`localhost` costs ~200 ms per new connection on Windows** (IPv6 tried first). The frontend API default is now `http://127.0.0.1:8000/api/v1`; the Redis heartbeat reuses one client instead of connecting per request.
4. Pages without a `loading.tsx` showed nothing until data arrived; analytics, calibration and settings now show a skeleton immediately.

Not changed on purpose: `pool_pre_ping` (one extra ~37 ms ping per request, but it protects against a dropped idle connection failing a real request).

## Calls page
- Sort by date, agent, status, duration, QA (lowest first by default), violations, risk. Empty values last; ties broken by id so paging is stable.
- Filters: + "reviewed by a person / not yet". Quick views (built in + "Save this view", stored in this browser).
- Violations show the worst severity; hover for the breakdown. QA hover says whether a person reviewed it and what they scored. Processed calls with no audio show "No speech".
- Failed rows show the plain-English reason and a Retry button (or "Retrying will not help").
- Bulk: tick rows -> Re-run analysis (max 100, manual reviews kept) / Retry failed.
- Export CSV of the current filters, up to 5,000 rows; cells starting with `= + - @` are neutralised against spreadsheet formula injection.

## Settings (`/settings`)
Admin-editable overrides of `.env` defaults, stored in `app_settings` (migration 0005), audit-logged, range-validated. Includes change-password.

## API speed: root cause and fixes (measured on the live database)
The database is 34 ms away (ping), so every statement costs >= ~35 ms and the app issued them one after another. Server-side execution was fast (a 6-table join: 46 ms). What was slow:
1. **Wasted round trips per request (~110 ms):** a ping on every connection checkout, an explicit BEGIN, and a ROLLBACK on return. Now: GET endpoints use AUTOCOMMIT read sessions (`get_read_db`), and the ping happens only for a connection idle > 30 s.
2. **Wide rows:** list queries joined 6 tables and fetched every column (waveform peaks, notes, evidence...). Now `load_only` fetches just what the row shows (25-row list: 480 -> 237 ms alone). Analytics loaded every call in full to count them; now one statement.
3. **Sequential independent queries:** analytics (13 statements), dashboard (4 groups), calls list (count + page) now run side by side (`app/core/parallel.py`, PostgreSQL only).
4. A settings lookup on every request is cached 5 s; the pool is warmed at startup.

Cold (no response cache) before -> after: analytics 866 -> 95 ms, dashboard 825 -> ~230 ms, calls list 403 -> ~210 ms, ingestion status 768 -> 89 ms, call detail ~67-170 ms.
**The remaining floor is the network.** Running the API on the same host/LAN segment as PostgreSQL removes it (each statement ~1 ms instead of ~35 ms).
