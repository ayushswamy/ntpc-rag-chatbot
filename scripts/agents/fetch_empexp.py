"""
Agent: Employee Experience (EmpExp)
Source: http://ccitapps.ntpc.co.in/empexp

The page is a JavaScript DataTable of employee experiences
(Title / Project-Site-Function / Area / Description / Year / Author / Attachment)
— it is NOT a file repository. The previous implementation inherited EDOP's
file-link scan (a[href$='.pdf'] …) and therefore found nothing: the real content
lives in the table rows + a "Show more" modal for the full description, and each
attachment opens via an "Open" button, not a .pdf href.

Strategy (TABLE + MODAL + ATTACHMENT):
  1. Walk every page of the table.
  2. For each row capture the structured fields; open its "Show more" modal to get
     the FULL description, falling back to the truncated cell text if the modal
     can't be opened.
  3. Best-effort download of each row's attachment (the "Open" button) as a PDF
     into the reports folder via the browser context.
  4. Save the whole list as empexp_<date>.json so the indexer embeds it.

Config: EMPEXP_URL, EMPEXP_MAX_PAGES (default 30).

NOTE: The NTPC intranet is not reachable from a dev machine, so the selectors
below are best-effort and defensive. Run once with --headed on the NTPC LAN to
confirm/tune them:
    python -m scripts.agents.orchestrator --only empexp --headed
"""

import json
from datetime import datetime
from urllib.parse import urljoin, urlparse
from pathlib import Path

from playwright.async_api import async_playwright

from .base_agent import DEFAULT_UA, BaseAgent

_HEADER_FALLBACK = ["Title", "Project/Site/Function", "Area", "Description", "Year", "Author"]

# "Next page" controls (DataTables-style), same family the CSR agent uses.
_NEXT_SELECTORS = [
    "a[rel='next']", "li.next:not(.disabled) a", "a.next:not(.disabled)",
    "a.paginate_next:not(.disabled)", ".pagination a[aria-label='Next']",
    "[aria-label='Next']:not([disabled])", "a[title='Next']",
    ".paginate_button.next:not(.disabled)",
]
_SHOW_MORE = ("a:has-text('Show more'), span:has-text('Show more'), "
              "button:has-text('Show more'), a:has-text('Read more'), "
              "span:has-text('Read more'), a:has-text('...')")
# Candidate modal containers across common UI frameworks. We pick the first that
# is actually VISIBLE (a hidden template must never win — that was the old bug).
_MODAL_SELECTORS = [
    ".modal.show", ".modal.in", ".modal[style*='display: block']",
    "[role='dialog']", ".modal-dialog", ".modal-content", ".modal",
    ".swal2-popup", ".ui-dialog", ".MuiDialog-paper", ".ant-modal",
]
_MODAL_CLOSE = ("[data-dismiss='modal'], [data-bs-dismiss='modal'], "
                ".modal .close, .modal .btn-close, [aria-label='Close'], .swal2-close")
_ATTACH = "a[href*='upload'], a[href$='.pdf'], a:has-text('Open'), button:has-text('Open')"


def _looks_header(row: list[str]) -> bool:
    j = " ".join(row).lower()
    return "title" in j and ("description" in j or "author" in j)


class EmpExpAgent(BaseAgent):
    name = "empexp"
    _host = "ccitapps.ntpc.co.in"
    _port = 80  # empexp is served over http

    async def _row_cells(self, row) -> list[str]:
        """Text of every cell in a row (truncated description included)."""
        cells = row.locator("th, td")
        n = await cells.count()
        out = []
        for i in range(n):
            try:
                out.append((await cells.nth(i).inner_text()).replace("\n", " ").strip())
            except Exception:
                out.append("")
        return out

    async def _visible_modal(self, page, quick: bool = False):
        """Return the first VISIBLE modal container (or None). Polls briefly so a
        modal that animates in is still caught, and never returns a hidden template.
        quick=True does a single pass (used while waiting for a modal to CLOSE)."""
        attempts = 1 if quick else 12             # ~3s total (12 × 250ms)
        for _ in range(attempts):
            for sel in _MODAL_SELECTORS:
                loc = page.locator(sel)
                try:
                    count = await loc.count()
                except Exception:
                    continue
                for i in range(min(count, 4)):
                    el = loc.nth(i)
                    try:
                        if await el.is_visible():
                            return el
                    except Exception:
                        continue
            if not quick:
                await page.wait_for_timeout(250)
        return None

    async def _close_modal(self, page):
        """Best-effort close, then WAIT until no modal/backdrop is visible so the
        next row's 'Show more' click can't land on a fading overlay."""
        try:
            btn = page.locator(_MODAL_CLOSE)
            if await btn.count() > 0 and await btn.first.is_visible():
                await btn.first.click(timeout=2_000)
            else:
                await page.keyboard.press("Escape")
        except Exception:
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
        # Wait for the modal to actually disappear (backdrop fade-out).
        for _ in range(12):                       # up to ~3s
            if await self._visible_modal(page, quick=True) is None:
                break
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(250)
        await page.wait_for_timeout(200)

    async def _full_description(self, page, row, fallback: str) -> str:
        """Open the row's 'Show more' modal and read the full text; fall back to
        the truncated cell text if no modal appears."""
        try:
            link = row.locator(_SHOW_MORE)
            if await link.count() == 0:
                return fallback
            try:
                await link.first.scroll_into_view_if_needed(timeout=3_000)
            except Exception:
                pass

            # Click, look for a visible modal; retry the click once if none appears
            # (guards against a click that landed on a still-fading previous overlay).
            modal = None
            for attempt in range(2):
                try:
                    await link.first.click(timeout=5_000)
                except Exception:
                    await page.wait_for_timeout(400)
                    continue
                modal = await self._visible_modal(page)
                if modal is not None:
                    break
                await page.wait_for_timeout(400)

            if modal is None:
                # No modal → the link may expand the text inline; re-read the row.
                await page.wait_for_timeout(400)
                inline = (await row.inner_text()).replace("\n", " ").strip()
                await self._close_modal(page)
                return inline if len(inline) > len(fallback) else fallback

            await page.wait_for_timeout(300)      # let the body populate
            text = (await modal.inner_text()).replace("\r", " ").strip()
            await self._close_modal(page)
            return text or fallback
        except Exception as exc:
            self.logger.info(f"  [desc] modal fallback ({type(exc).__name__})")
            await self._close_modal(page)
            return fallback

    async def _download_attachment(self, ctx, page, row, base_url, title: str):
        """Best-effort: fetch the row's attachment PDF via the browser context."""
        try:
            el = row.locator(_ATTACH).first
            if await el.count() == 0:
                return
            href = (await el.get_attribute("href")) or ""
            if href and not href.lower().startswith("javascript"):
                full = urljoin(base_url, href)
                name = Path(urlparse(full).path).name or f"{title[:40]}.pdf"
                self.note_discovered(1)
                await self.download_via_context(ctx, [(full, name)], referer=base_url)
                return
            # No usable href → the button opens the file itself (download or new tab).
            self.note_discovered(1)
            try:
                async with page.expect_download(timeout=15_000) as dl:
                    await el.click()
                d = await dl.value
                tmp = await d.path()
                if tmp:
                    self.save_file(Path(tmp).read_bytes(),
                                   d.suggested_filename or f"{title[:40]}.pdf", base_url)
                await d.delete()
            except Exception:
                self.logger.info(f"  [attach] could not download for {title[:40]!r}")
        except Exception as exc:
            self.logger.info(f"  [attach] skip ({type(exc).__name__})")

    async def _fetch(self):
        url = self.config["EMPEXP_URL"]
        max_pages = int(self.config.get("EMPEXP_MAX_PAGES", 30))
        self.logger.info(
            f"strategy=TABLE(paginated)+MODAL mode=playwright headless={self.headless} "
            f"max_pages={max_pages} url={url}")

        records: dict[str, dict] = {}
        header: list[str] | None = None

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                ctx = await browser.new_context(
                    user_agent=DEFAULT_UA, ignore_https_errors=True, accept_downloads=True)
                page = await ctx.new_page()
                await page.goto(url, wait_until="networkidle", timeout=60_000)
                await page.wait_for_timeout(2_000)

                for page_num in range(1, max_pages + 1):
                    rows = page.locator("table tbody tr")
                    row_count = await rows.count()
                    if row_count == 0:
                        # some tables have no tbody — fall back to all rows
                        rows = page.locator("table tr")
                        row_count = await rows.count()
                    if row_count == 0:
                        break

                    new = 0
                    for i in range(row_count):
                        row = rows.nth(i)
                        cells = await self._row_cells(row)
                        if not any(cells) or _looks_header(cells):
                            continue
                        if header is None:
                            header = _HEADER_FALLBACK

                        title = cells[0] if cells else ""
                        trunc_desc = cells[3] if len(cells) > 3 else ""
                        full_desc = await self._full_description(page, row, trunc_desc)

                        rec = {
                            "Title":        title,
                            "Project/Site": cells[1] if len(cells) > 1 else "",
                            "Area":         cells[2] if len(cells) > 2 else "",
                            "Description":  full_desc,
                            "Year":         cells[4] if len(cells) > 4 else "",
                            "Author":       cells[5] if len(cells) > 5 else "",
                        }
                        key = title or f"row{len(records)+1}"
                        if key not in records:
                            records[key] = rec
                            new += 1
                            await self._download_attachment(ctx, page, row, url, title)

                    self.logger.info(
                        f"  page {page_num}: {row_count} rows, +{new} new (total {len(records)})")

                    if page_num > 1 and new == 0:
                        break
                    if not await self._click_next(page):
                        self.logger.info("  no further pages")
                        break
                    await page.wait_for_timeout(1_800)

                self.logger.info(f"Extracted {len(records)} employee-experience records")
                if not records:
                    self.logger.warning(
                        "No EmpExp rows extracted — table structure may have changed; "
                        "run with --headed to inspect and tune the selectors.")
                    return

                self.note_discovered(len(records))
                # No volatile timestamp in the body, so an unchanged list produces
                # identical bytes and is skipped by dedup on daily re-runs.
                payload = {
                    "source_url": url,
                    "columns": header or _HEADER_FALLBACK,
                    "count": len(records),
                    "rows": list(records.values()),
                }
                date = datetime.now().strftime("%Y%m%d")
                self.save_file(
                    json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                    "empexp.json", url, exact_name=f"empexp_{date}.json",
                )
            finally:
                await browser.close()

    async def _click_next(self, page) -> bool:
        for sel in _NEXT_SELECTORS:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                try:
                    await el.click()
                    return True
                except Exception:
                    pass
        for txt in ["►", "»", "›", ">>", "Next"]:
            try:
                loc = page.get_by_text(txt, exact=True).first
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.click()
                    return True
            except Exception:
                pass
        return False
