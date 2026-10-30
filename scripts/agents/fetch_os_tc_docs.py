"""
Agent: OS/TC Documents
Source: http://10.0.8.241/OS-TCDocs/OS_TC_Main.aspx  (ASP.NET)

Strategy:
  1. Playwright navigates the ASPX page (handles ViewState / EventValidation).
  2. Collect document links from the page grid/table.
  3. Two download modes per link:
       a. Direct href (.pdf/.doc/.xls/...) -> queued for HTTP download.
       b. JavaScript postback (__doPostBack) -> page.expect_download() + click().
  4. Paginate through a multi-page grid via OS_TC_NEXT_PAGE_SELECTOR (optional).

All selectors come from config/.env.agents.
"""

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright

from .base_agent import DEFAULT_UA, BaseAgent

_FILE_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip"}
_JS_POSTBACK_RE = re.compile(r"javascript:__doPostBack\(", re.IGNORECASE)


def _is_file_link(href: str) -> bool:
    return Path(urlparse(href).path).suffix.lower() in _FILE_EXTS


def _is_postback(href: str) -> bool:
    return bool(_JS_POSTBACK_RE.match(href or ""))


class OSTCDocsAgent(BaseAgent):
    name = "os_tc"
    _host = "10.0.8.241"
    _port = 80

    async def _fetch(self):
        base_url = self.config["OS_TC_URL"]
        doc_selector = self.config.get(
            "OS_TC_DOC_LINK_SELECTOR",
            "a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], "
            "a[href$='.xls'], a[href$='.xlsx'], a[href$='.csv']",
        )
        next_page_selector = self.config.get("OS_TC_NEXT_PAGE_SELECTOR", "")
        max_pages = int(self.config.get("OS_TC_MAX_PAGES", 20))

        self.logger.info(f"mode=playwright headless={self.headless} url={base_url}")

        all_direct_links: list[tuple[str, str]] = []

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                ctx = await browser.new_context(
                    user_agent=DEFAULT_UA,
                    ignore_https_errors=True,
                    accept_downloads=True,
                )
                page = await ctx.new_page()
                await page.goto(base_url, wait_until="networkidle", timeout=60_000)
                await page.wait_for_timeout(2_000)

                page_num = 0
                while page_num < max_pages:
                    page_num += 1
                    self.logger.info(f"Scanning grid page {page_num}")

                    anchors = await page.query_selector_all(doc_selector)
                    self.logger.info(f"  Found {len(anchors)} matching links")

                    for anchor in anchors:
                        href = (await anchor.get_attribute("href") or "").strip()
                        if not href:
                            continue

                        if _is_file_link(href):
                            full_url = urljoin(base_url, href)
                            original_name = Path(urlparse(full_url).path).name or "doc"
                            all_direct_links.append((full_url, original_name))
                            self.note_discovered(1)

                        elif _is_postback(href):
                            self.note_discovered(1)
                            original_name = (
                                (await anchor.inner_text()).strip().replace(" ", "_")
                                or f"doc_p{page_num}.bin"
                            )
                            try:
                                async with page.expect_download(timeout=30_000) as dl_info:
                                    await anchor.click()
                                download = await dl_info.value
                                tmp_path = await download.path()
                                if tmp_path:
                                    content = Path(tmp_path).read_bytes()
                                    suggested = download.suggested_filename or original_name
                                    self.save_file(content, suggested, base_url)
                                await download.delete()
                            except Exception as exc:
                                self.logger.warning(
                                    f"  [fail] postback download {original_name!r}: {exc}"
                                )
                                self.stats["failed"] += 1

                    # Paginate if configured and a visible next button exists.
                    if next_page_selector:
                        next_btn = await page.query_selector(next_page_selector)
                        if next_btn and await next_btn.is_visible():
                            await next_btn.click()
                            await page.wait_for_load_state("networkidle")
                            await page.wait_for_timeout(1_000)
                        else:
                            break
                    else:
                        break  # single-page scan

                # Download through the browser context (shares the proxy/session)
                # - plain httpx is blocked here with 403 URLBlocked.
                await self.download_via_context(ctx, all_direct_links, referer=base_url)
            finally:
                await browser.close()
