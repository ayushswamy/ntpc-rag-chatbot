"""
Agent: Annual Reports
Source: https://www.ntpc.co.in/investors/financial-performance/annual-reports

Strategy:
  1. Playwright loads the JS-rendered page.
  2. Collect every PDF href on the page.
  3. Download each PDF via plain HTTP (faster than browser download).
  4. PDFs land in PDF_DIR (frontend/public/reports) with a stable name prefix,
     which is exactly the folder scripts/indexer.py reads.

Selectors and URL come from config/.env.agents - nothing is hard-coded.
"""

from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from .base_agent import DEFAULT_UA, BaseAgent


class AnnualReportsAgent(BaseAgent):
    name = "annual_reports"
    _host = "www.ntpc.co.in"
    _port = 443

    async def _fetch(self):
        url = self.config["ANNUAL_REPORTS_URL"]
        pdf_selector = self.config.get(
            "ANNUAL_REPORTS_PDF_SELECTOR", "a[href$='.pdf'], a[href*='.pdf']"
        )
        self.logger.info(f"mode=playwright headless={self.headless} url={url}")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                ctx = await browser.new_context(
                    user_agent=DEFAULT_UA, ignore_https_errors=True
                )
                page = await ctx.new_page()
                await page.goto(url, wait_until="networkidle", timeout=60_000)
                await page.wait_for_timeout(2_000)

                # Collect all PDF hrefs (resolved to absolute by the browser).
                links = await page.eval_on_selector_all(
                    pdf_selector,
                    "els => els.map(e => e.href).filter(Boolean)",
                )

                # De-duplicate and keep only real .pdf URLs.
                seen: set[str] = set()
                pdf_links: list[tuple[str, str]] = []
                for link in links:
                    norm = link.split("?")[0].split("#")[0]
                    if norm.lower().endswith(".pdf") and norm not in seen:
                        seen.add(norm)
                        original_name = Path(urlparse(norm).path).name or "report.pdf"
                        pdf_links.append((link, original_name))

                self.note_discovered(len(pdf_links))
                self.logger.info(f"Discovered {len(pdf_links)} PDF links")
                if not pdf_links:
                    self.logger.warning(
                        f"No PDFs found - selector may need updating: {pdf_selector!r}"
                    )
                    return

                # Download through the browser context (shares Chromium's proxy +
                # session), which works where plain httpx is blocked by the WAF.
                await self.download_via_context(ctx, pdf_links, referer=url)
            finally:
                await browser.close()
