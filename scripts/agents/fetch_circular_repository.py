"""
Agent: Circular Repository
Source: https://ccitapps.ntpc.co.in/circularrepository

Strategy A (FILE DOWNLOAD): the landing page is a "Circular center" listing
official NTPC circulars/IOMs as direct PDF links (under /uploads/...). Collect
every document link and download it through the browser context (proxy/session
aware) into the reports folder so the indexer picks them up.

URL + selector come from config/.env.agents.
"""

from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright

from .base_agent import DEFAULT_UA, BaseAgent

_DEFAULT_SELECTOR = (
    "a[href$='.pdf'], a[href*='.pdf'], a[href$='.doc'], a[href$='.docx'], "
    "a[href$='.xls'], a[href$='.xlsx'], a[href$='.csv']"
)


class CircularRepositoryAgent(BaseAgent):
    name = "circular_repository"
    _host = "ccitapps.ntpc.co.in"
    _port = 443

    async def _fetch(self):
        url = self.config["CIRCULAR_REPOSITORY_URL"]
        selector = self.config.get("CIRCULAR_DOC_LINK_SELECTOR", _DEFAULT_SELECTOR)
        self.logger.info(f"strategy=FILE mode=playwright headless={self.headless} url={url}")

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

                hrefs = await page.eval_on_selector_all(
                    selector, "els => els.map(e => e.href).filter(Boolean)")

                seen: set[str] = set()
                doc_links: list[tuple[str, str]] = []
                for href in hrefs:
                    full = urljoin(url, href)
                    norm = full.split("#")[0]
                    if norm in seen:
                        continue
                    seen.add(norm)
                    original = Path(urlparse(norm).path).name or "circular.pdf"
                    doc_links.append((full, original))

                self.note_discovered(len(doc_links))
                self.logger.info(f"Discovered {len(doc_links)} document links")
                if not doc_links:
                    self.logger.warning(f"No document links found - selector may need tuning: {selector!r}")
                    return

                await self.download_via_context(ctx, doc_links, referer=url)
            finally:
                await browser.close()
