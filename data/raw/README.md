# Raw data provenance

Nothing in this directory is edited after download.

| Path | Source | Retrieved | Notes |
|---|---|---|---|
| `imd/rain/<year>.grd` | IMD 0.25° gridded daily rainfall, via `imdlib` (`imdpune.gov.in`) | 13 Oct 2026 | 1981–2025, one file per year, 25 MB each. Regenerate with `python scripts/download_imd.py 1981 2025`. Not committed: the directory is in `.gitignore`. |
| `power/<lat>_<lon>_<start>_<end>.json` | NASA POWER daily `PRECTOTCORR` (MERRA-2), point API | 13 Oct 2026 | Used for 2026, which IMD has not published in the archive yet, and to measure that product's own bias over 1991–2020. |

Two sources were attempted and did not work on 13 Oct 2026, which is why the
current season falls back to NASA POWER and why realised volatility is missing:

- IMD real-time gridded rainfall (`imdlib.get_real_data`) — connection to
  `imdpune.gov.in/cmpg/Realtimedata/Rainfall/rain.php` timed out.
- Bulk NIFTY 50 history — Yahoo's chart API returned HTTP 429, and the NSE and
  niftyindices endpoints returned 503 and 302.
