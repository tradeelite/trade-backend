"""SEC EDGAR API service — completely free, no API key required.

Rate limit: 10 requests/second max (we stay well under this).
User-Agent header is required by SEC fair-use policy.

Covers: CIK lookup, recent 10-K/10-Q/8-K filings with direct document URLs,
        structured XBRL financial data from company facts API.
"""

import httpx

EDGAR_BASE = "https://data.sec.gov"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
USER_AGENT = "TradeElite contact@tradeelite.ai"

# In-memory CIK lookup cache (ticker → zero-padded 10-digit CIK string)
_cik_cache: dict[str, str] = {}


async def _get_cik_map() -> dict[str, str]:
    """Download SEC's full ticker→CIK mapping (~3MB JSON, cached after first call)."""
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(TICKERS_URL)
        r.raise_for_status()
        data = r.json()
    return {
        entry.get("ticker", "").upper(): str(entry["cik_str"]).zfill(10)
        for entry in data.values()
        if "ticker" in entry and "cik_str" in entry
    }


async def get_cik(ticker: str) -> str | None:
    """Resolve a ticker symbol to its SEC CIK number (10-digit zero-padded)."""
    ticker_upper = ticker.upper()
    if ticker_upper in _cik_cache:
        return _cik_cache[ticker_upper]
    mapping = await _get_cik_map()
    _cik_cache.update(mapping)
    return _cik_cache.get(ticker_upper)


async def get_recent_filings(
    ticker: str,
    form_types: list[str] | None = None,
    limit: int = 15,
) -> list[dict]:
    """
    Get recent SEC filings with direct document URLs.

    Args:
        ticker: Stock ticker symbol.
        form_types: List of form types to include. Defaults to ["10-K", "10-Q", "8-K"].
        limit: Max number of filings to return (across all form types).

    Returns list of filings with: form, date, accessionNumber, description, url, indexUrl.
    """
    cik = await get_cik(ticker)
    if not cik:
        return []

    if form_types is None:
        form_types = ["10-K", "10-Q", "8-K"]

    url = f"{EDGAR_BASE}/submissions/CIK{cik}.json"
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    primary_docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])

    filings = []
    cik_int = int(cik)
    for i, form in enumerate(forms):
        if form not in form_types:
            continue
        acc_no = accessions[i] if i < len(accessions) else ""
        acc_clean = acc_no.replace("-", "")
        doc = primary_docs[i] if i < len(primary_docs) else ""
        filings.append({
            "form": form,
            "date": dates[i] if i < len(dates) else "",
            "accessionNumber": acc_no,
            "description": descriptions[i] if i < len(descriptions) else "",
            "url": f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_clean}/{doc}" if doc else "",
            "indexUrl": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=10",
        })
        if len(filings) >= limit:
            break

    return filings


async def get_company_facts(ticker: str) -> dict:
    """
    Get all XBRL-structured financial data from SEC filings.

    This is the raw data source that powers AI analyst reports.
    Contains every reported figure from all 10-K and 10-Q filings:
    revenue, EPS, assets, liabilities, equity, dividends, shares outstanding, and more.

    Note: Response can be large (1-5MB). Cache results on the caller side.
    """
    cik = await get_cik(ticker)
    if not cik:
        return {}

    url = f"{EDGAR_BASE}/api/xbrl/companyfacts/CIK{cik}.json"
    async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r.json()
