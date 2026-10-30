"""
Agent: CSR List
Source: https://itstaging.ntpc.co.in/om/CSRlist/CSRLIST  (Organization Memory Portal)

Strategy B (STRUCTURED TABLE + PAGINATION): no downloadable files - the data is
a paginated table (Project ID / Description / Station / Reference / Action). Walk
all pages, extract every row as structured records, and save the full list as
csr_list_<date>.json so the indexer can embed it.

Config: CSR_LIST_URL, CSR_MAX_PAGES.
"""

import json
from datetime import datetime

from playwright.async_api import async_playwright

from .base_agent import DEFAULT_UA, BaseAgent

_HEADER_FALLBACK = ["Project ID", "Description", "Station", "Reference", "Action"]
_EXTRACT_JS = ("trs => trs.map(tr => Array.from(tr.querySelectorAll('th,td'))"
               ".map(c => (c.innerText||'').replace(/\\s+/g,' ').trim()))")
_NEXT_SELECTORS = [
    "a[rel='next']", "li.next:not(.disabled) a", "a.next:not(.disabled)",
    "a.paginate_next:not(.disabled)", ".pagination a[aria-label='Next']",
    "[aria-label='Next']:not([disabled])", "a[title='Next']",
]
_NEXT_TEXTS = ["►", "»", "›", ">>"]


def _looks_header(row: list[str]) -> bool:
    j = " ".join(row).lower()
    return ("project" in j and "description" in j) or ("station" in j and "reference" in j)


class CSRListAgent(BaseAgent):
    name = "csr_list"
    _host = "itstaging.ntpc.co.in"
    _port = 443

    async def _extract_rows(self, page):
        rows = await page.eval_on_selector_all("table tr", _EXTRACT_JS)
        return [r for r in rows if any(c for c in r)]

    async def _click_next(self, page) -> bool:
        for sel in _NEXT_SELECTORS:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                try:
                    await el.click()
                    return True
                except Exception:
                    pass
        for txt in _NEXT_TEXTS:
            try:
                loc = page.get_by_text(txt, exact=True).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click()
                    return True
            except Exception:
                pass
        return False

    async def _fetch(self):
        url = self.config["CSR_LIST_URL"]
        max_pages = int(self.config.get("CSR_MAX_PAGES", 30))
        self.logger.info(
            f"strategy=TABLE(paginated) mode=playwright headless={self.headless} "
            f"max_pages={max_pages} url={url}")

        records: dict[str, dict] = {}
        header: list[str] | None = None

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                ctx = await browser.new_context(user_agent=DEFAULT_UA, ignore_https_errors=True)
                page = await ctx.new_page()
                await page.goto(url, wait_until="networkidle", timeout=60_000)
                await page.wait_for_timeout(2_000)

                for page_num in range(1, max_pages + 1):
                    rows = await self._extract_rows(page)
                    if not rows:
                        break
                    if header is None:
                        hdr = next((r for r in rows if _looks_header(r)), None)
                        header = hdr or _HEADER_FALLBACK
                    data = [r for r in rows if not _looks_header(r)]

                    new = 0
                    for r in data:
                        rec = {
                            (header[i] if i < len(header) else f"col{i+1}"): (r[i] if i < len(r) else "")
                            for i in range(max(len(header), len(r)))
                        }
                        key = (r[0].strip() if r and r[0].strip() else f"row{len(records)+1}")
                        if key not in records:
                            records[key] = rec
                            new += 1
                    self.logger.info(f"  page {page_num}: {len(data)} rows, +{new} new (total {len(records)})")

                    if page_num > 1 and new == 0:
                        break
                    if not await self._click_next(page):
                        self.logger.info("  no further pages")
                        break
                    await page.wait_for_timeout(1_800)

                self.logger.info(f"Extracted {len(records)} CSR records")
                if not records:
                    self.logger.warning("No CSR rows extracted - table structure may have changed.")
                    return

                self.note_discovered(len(records))
                # NOTE: no volatile timestamp in the body, so an unchanged list
                # produces identical bytes and is skipped by dedup on daily re-runs.
                payload = {
                    "source_url": url,
                    "columns": header,
                    "count": len(records),
                    "rows": list(records.values()),
                }
                date = datetime.now().strftime("%Y%m%d")
                self.save_file(
                    json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                    "csr_list.json", url, exact_name=f"csr_list_{date}.json",
                )
            finally:
                await browser.close()
