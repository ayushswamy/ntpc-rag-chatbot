"""
Agent: Safety Portal
Source: http://10.0.8.68/safety  (internal "My Safety Application")

Strategy C (MIXED, file-focused): the landing page has a few PDFs (Annual
Highlights, Safety Newsletters) plus a large nav menu (Policy Manual, Circulars
& IOMs, TC Documents, Checklists, Procedures, Standards ...) that lead to more
document pages. We do a SHALLOW same-domain crawl (default depth 1) to collect
PDF/Office links across the landing + sub-pages, then download them through the
browser context. The landing body text is just menu links, so page-text is not
extracted here - the value is the documents.

Config: SAFETY_URL, SAFETY_DOC_LINK_SELECTOR, SAFETY_MAX_DEPTH, SAFETY_MAX_PAGES.
"""

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright

from .base_agent import DEFAULT_UA, BaseAgent

_FILE_RE = re.compile(r"\.(pdf|docx?|xlsx?|csv|pptx?)(\?|#|$)", re.I)
_SKIP_RE = re.compile(r"(logoff|logout|login|account|signout)", re.I)


def _is_file(href: str) -> bool:
    return bool(_FILE_RE.search(href))


class SafetyPortalAgent(BaseAgent):
    name = "safety_portal"
    _host = "10.0.8.68"
    _port = 80

    async def _fetch(self):
        base_url = self.config["SAFETY_URL"]
        max_depth = int(self.config.get("SAFETY_MAX_DEPTH", 1))
        max_pages = int(self.config.get("SAFETY_MAX_PAGES", 25))
        host = urlparse(base_url).netloc
        self.logger.info(
            f"strategy=MIXED(files) mode=playwright headless={self.headless} "
            f"crawl_depth={max_depth} max_pages={max_pages} url={base_url}")

        doc_links: dict[str, str] = {}    # url -> original_name (dedup by url)
        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(base_url, 0)]

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                ctx = await browser.new_context(user_agent=DEFAULT_UA, ignore_https_errors=True)
                page = await ctx.new_page()

                while queue and len(visited) < max_pages:
                    cur, depth = queue.pop(0)
                    if cur in visited:
                        continue
                    visited.add(cur)
                    try:
                        try:
                            await page.goto(cur, wait_until="networkidle", timeout=45_000)
                        except Exception:
                            await page.goto(cur, wait_until="domcontentloaded", timeout=45_000)
                        await page.wait_for_timeout(1_500)
                    except Exception as exc:
                        self.logger.warning(f"  could not load {cur}: {exc}")
                        continue

                    hrefs = await page.eval_on_selector_all(
                        "a[href]", "els => els.map(e => e.href).filter(Boolean)")
                    self.logger.info(f"  [depth {depth}] {cur} -> {len(hrefs)} links")

                    for href in hrefs:
                        full = urljoin(cur, href).split("#")[0]
                        if urlparse(full).netloc != host or _SKIP_RE.search(full):
                            continue
                        if _is_file(full):
                            if full not in doc_links:
                                doc_links[full] = Path(urlparse(full).path).name or "safety_doc.pdf"
                        elif depth < max_depth and full not in visited:
                            queue.append((full, depth + 1))

                items = list(doc_links.items())
                self.note_discovered(len(items))
                self.logger.info(f"Discovered {len(items)} document links across {len(visited)} page(s)")
                if not items:
                    self.logger.warning("No document links found on the safety portal.")
                    return

                await self.download_via_context(ctx, items, referer=base_url)
            finally:
                await browser.close()
