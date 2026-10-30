"""
Agent: NTPC Wiki (NTPCPedia)
Source: https://ccitapps.ntpc.co.in/ntpcwiki

Strategy B (PAGE CONTENT + CRAWL): the wiki has NO downloadable files - content
lives in articles reached via /ntpcwiki/Articles/Details?slug=<slug>. Crawl
same-domain wiki links (default depth 2, max 50 pages), extract each page's main
article text, and save it as ntpcwiki_<date>_<slug>.txt so the indexer reads it.
Tracks visited URLs to avoid loops.

Config: NTPC_WIKI_URL, WIKI_MAX_DEPTH, WIKI_MAX_PAGES.
"""

import re
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.async_api import async_playwright

from .base_agent import DEFAULT_UA, BaseAgent

_WIKI_PATH = "/ntpcwiki"
_MIN_CHARS = 120  # skip near-empty / nav-only pages


def _slug(url: str) -> str:
    q = parse_qs(urlparse(url).query)
    raw = q["slug"][0] if "slug" in q and q["slug"] else (
        urlparse(url).path.rstrip("/").split("/")[-1] or "home")
    slug = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-")
    return slug or "home"


class NTPCWikiAgent(BaseAgent):
    name = "ntpcwiki"
    _host = "ccitapps.ntpc.co.in"
    _port = 443

    async def _fetch(self):
        base_url = self.config["NTPC_WIKI_URL"]
        max_depth = int(self.config.get("WIKI_MAX_DEPTH", 2))
        max_pages = int(self.config.get("WIKI_MAX_PAGES", 50))
        host = urlparse(base_url).netloc
        self.logger.info(
            f"strategy=PAGE(crawl) mode=playwright headless={self.headless} "
            f"depth={max_depth} max_pages={max_pages} url={base_url}")

        visited: set[str] = set()
        queued: set[str] = {base_url}
        queue: list[tuple[str, int]] = [(base_url, 0)]
        saved_slugs: set[str] = set()

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

                    # Extract + save this page's article text.
                    html = await page.content()
                    text = self.extract_main_text(html)
                    slug = _slug(cur)
                    if len(text) >= _MIN_CHARS and slug not in saved_slugs:
                        title = await page.title()
                        header = f"NTPC Wiki article: {title}\nSource: {cur}\n\n"
                        self.note_discovered(1)
                        if self.save_file((header + text).encode("utf-8"), f"{slug}.txt", cur):
                            saved_slugs.add(slug)
                    self.logger.info(f"  [depth {depth}] {slug} ({len(text)} chars) <- {cur}")

                    # Enqueue same-domain wiki links.
                    if depth < max_depth:
                        hrefs = await page.eval_on_selector_all(
                            "a[href]", "els => els.map(e => e.href).filter(Boolean)")
                        for href in hrefs:
                            full = urljoin(cur, href).split("#")[0]
                            p = urlparse(full)
                            if (p.netloc == host and p.path.startswith(_WIKI_PATH)
                                    and full not in queued and full not in visited):
                                queued.add(full)
                                queue.append((full, depth + 1))

                self.logger.info(f"Crawled {len(visited)} page(s), saved {len(saved_slugs)} article(s).")
                if not saved_slugs:
                    self.logger.warning("No wiki article text extracted - structure may have changed.")
            finally:
                await browser.close()
