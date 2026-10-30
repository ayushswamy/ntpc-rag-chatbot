"""
Agent: EDOP
Source: https://ccitapps.ntpc.co.in/edop

EDOP is a JavaScript single-page app (DoPDigitizationNew), NOT a document
repository - it exposes no downloadable files. Its data comes from JSON APIs,
of which GetAllDops / GetDashboardStats are reachable without login.

Strategy:
  1. Try the document-scan path (in case sub-paths host real files).
  2. Fetch the configured JSON API endpoints, render them to readable text,
     and emit a PDF into the reports folder so the existing indexer picks it up.
     Raw JSON is also saved under data/raw/downloads/edop for the record.

URL, selectors, sub-paths and API endpoints all come from config/.env.agents.
"""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote, urlencode, urljoin, urlparse

from playwright.async_api import async_playwright

from .base_agent import DEFAULT_UA, BaseAgent

_FILE_EXTS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".ppt", ".pptx"}
_JS_POSTBACK_RE = re.compile(r"javascript:__doPostBack\(", re.IGNORECASE)


def _is_file_link(href: str) -> bool:
    return Path(urlparse(href).path).suffix.lower() in _FILE_EXTS


# EDOP JSON API (discovered from the app's inline JS; all public/no-login).
_EP_DOPS = "home/GetAllDops"
_EP_CLAUSES = "home/GetClausesByDop"               # ?dop=
_EP_DETAIL = "home/GetClauseDetails"               # ?dop=&clauseNo=  (non-admin DoPs)
_EP_DETAIL_ADMIN = "home/GetClauseDetailsForAdminFuntion"  # ?dop=&clauseNo=  (admin DoPs)
_EP_ACRONYMS = "home/GetAcronyms"                  # ?dop=


def _clean(v) -> str:
    """Coerce an API value (str / list / dict / None) to readable text."""
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return " ".join(_clean(x) for x in v).strip()
    if isinstance(v, dict):
        return " ".join(f"{k}: {_clean(val)}" for k, val in v.items()).strip()
    return str(v).strip()


def _render_nonadmin_detail(rows: list) -> list[str]:
    """Render GetClauseDetails rows (natureOfPower + authorities)."""
    lines: list[str] = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        np = _clean(r.get("natureOfPower"))
        if np:
            lines.append(f"    Nature of power: {np}")
        auth = r.get("authorities")
        if auth:
            lines.append("    Authorities / extent:")
            lines += json_to_text(auth, "      ")
        rem = _clean(r.get("remarksText"))
        if rem:
            lines.append(f"    Remarks: {rem}")
    return lines


def _render_admin_detail(payload) -> list[str]:
    """Render GetClauseDetailsForAdminFuntion (data[].snoData[])."""
    lines: list[str] = []
    data = payload.get("data") if isinstance(payload, dict) else payload
    for grp in (data or []):
        for sd in grp.get("snoData", []) if isinstance(grp, dict) else []:
            if not isinstance(sd, dict):
                continue
            sm = _clean(sd.get("subjectMatter"))
            oa = _clean(sd.get("officerAuthorized"))
            ex = _clean(sd.get("extentOfPower"))
            rm = _clean(sd.get("remarks"))
            if sm:
                lines.append(f"    Subject matter: {sm}")
            if oa:
                lines.append(f"    Officer authorized: {oa}")
            if ex:
                lines.append(f"    Extent of power: {ex}")
            if rm:
                lines.append(f"    Remarks: {rm}")
    return lines


def json_to_text(obj, prefix: str = "") -> list[str]:
    """Render arbitrary JSON into readable, indented lines for indexing."""
    lines: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{prefix}{k}:")
                lines += json_to_text(v, prefix + "  ")
            else:
                lines.append(f"{prefix}{k}: {v}")
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                flat = ", ".join(
                    f"{k}={v}" for k, v in item.items()
                    if not isinstance(v, (dict, list))
                )
                lines.append(f"{prefix}- {flat}")
                for k, v in item.items():
                    if isinstance(v, (dict, list)):
                        lines.append(f"{prefix}  {k}:")
                        lines += json_to_text(v, prefix + "    ")
            else:
                lines.append(f"{prefix}- {item}")
    else:
        lines.append(f"{prefix}{obj}")
    return lines


class EDOPAgent(BaseAgent):
    name = "edop"
    _host = "ccitapps.ntpc.co.in"
    _port = 443

    # Config keys (overridden in EmpExp).
    _url_key = "EDOP_URL"
    _selector_key = "EDOP_DOC_LINK_SELECTOR"
    _subpaths_key = "EDOP_SUB_PATHS"

    async def _fetch(self):
        base_url = self.config[self._url_key]
        doc_selector = self.config.get(
            self._selector_key,
            "a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], "
            "a[href$='.xls'], a[href$='.xlsx'], a[href$='.csv']",
        )
        sub_paths = [p.strip() for p in self.config.get(self._subpaths_key, "").split(",") if p.strip()]
        urls_to_scan = [base_url] + [urljoin(base_url + "/", p) for p in sub_paths]

        self.logger.info(
            f"mode=playwright headless={self.headless} scan={len(urls_to_scan)} url(s)"
        )

        direct_links: list[tuple[str, str]] = []

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

                for scan_url in urls_to_scan:
                    self.logger.info(f"Scanning: {scan_url}")
                    try:
                        await page.goto(scan_url, wait_until="networkidle", timeout=60_000)
                        await page.wait_for_timeout(2_000)
                    except Exception as exc:
                        self.logger.warning(f"  Could not load {scan_url}: {exc}")
                        continue

                    anchors = await page.query_selector_all(doc_selector)
                    self.logger.info(f"  Found {len(anchors)} matching links")

                    for anchor in anchors:
                        href = (await anchor.get_attribute("href") or "").strip()
                        if not href:
                            continue

                        if _is_file_link(href):
                            full_url = urljoin(scan_url, href)
                            original_name = Path(urlparse(full_url).path).name or "doc"
                            direct_links.append((full_url, original_name))
                            self.note_discovered(1)

                        elif _JS_POSTBACK_RE.match(href):
                            self.note_discovered(1)
                            label = (await anchor.inner_text()).strip().replace(" ", "_") or "doc"
                            try:
                                async with page.expect_download(timeout=30_000) as dl_info:
                                    await anchor.click()
                                download = await dl_info.value
                                tmp = await download.path()
                                if tmp:
                                    content = Path(tmp).read_bytes()
                                    fname = download.suggested_filename or label
                                    self.save_file(content, fname, scan_url)
                                await download.delete()
                            except Exception as exc:
                                self.logger.warning(
                                    f"  [fail] postback download {label!r}: {exc}"
                                )
                                self.stats["failed"] += 1

                # Direct file links via the browser context (proxy/session aware).
                await self.download_via_context(ctx, direct_links, referer=base_url)

                # EDOP-specific: pull the JSON API summary (no-op for EmpExp).
                await self.fetch_api_summary(ctx)
            finally:
                await browser.close()

    async def _api_get(self, ctx, base_url, path, timeout_ms, **params):
        """GET a JSON endpoint through the browser context; None on any failure."""
        url = f"{base_url}/{path.lstrip('/')}"
        if params:
            url += "?" + urlencode({k: v for k, v in params.items() if v is not None})
        try:
            resp = await ctx.request.get(url, timeout=timeout_ms)
        except Exception as exc:
            self.logger.warning(f"  API fetch failed {path}: {exc}")
            return None
        if not resp.ok:
            self.logger.warning(f"  API {path} -> HTTP {resp.status}")
            return None
        try:
            return await resp.json()
        except Exception:
            return None

    async def fetch_api_summary(self, ctx):
        """
        Ingest EDOP's Delegation-of-Powers data via its public JSON API and emit
        PDF(s) the indexer can read. EDOP_FETCH_MODE:
          full    - walk every DoP -> every clause -> detail rows (the ~1917 powers),
                    one PDF per DoP category (default)
          summary - just category names + counts (lightweight)
        """
        base_url = self.config[self._url_key].rstrip("/")
        timeout_ms = float(self.config.get("HTTP_TIMEOUT_SECONDS", 60)) * 1000
        mode = str(self.config.get("EDOP_FETCH_MODE", "full")).strip().lower()

        dops = await self._api_get(ctx, base_url, _EP_DOPS, timeout_ms)
        if not isinstance(dops, list) or not dops:
            self.logger.warning("EDOP: GetAllDops returned no data; skipping API ingest.")
            return
        self.logger.info(f"EDOP: {len(dops)} DoP categories (mode={mode})")
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

        if mode == "summary":
            stats = await self._api_get(ctx, base_url, "home/GetDashboardStats", timeout_ms)
            text = "## Categories\n" + "\n".join(json_to_text(dops))
            if stats:
                text += "\n\n## Dashboard\n" + "\n".join(json_to_text(stats))
            self.note_discovered(1)
            self.save_file(self.text_to_pdf_bytes(text, "EDOP - Delegation of Powers (summary)"),
                           "delegation_of_powers_summary.pdf", base_url)
            (self.downloads_dir / f"{self.name}_api_raw.json").write_text(
                json.dumps({"GetAllDops": dops, "GetDashboardStats": stats}, indent=2, ensure_ascii=False),
                encoding="utf-8")
            return

        # full mode: one PDF per DoP with all clauses + their detailed power rows.
        raw_payload: dict = {"GetAllDops": dops}
        total_detail_rows = 0
        for dop in dops:
            dop_val = dop.get("dopValue") or dop.get("dopName")
            if not dop_val:
                continue
            is_admin = bool(dop.get("isAdminFunction"))
            clauses = await self._api_get(ctx, base_url, _EP_CLAUSES, timeout_ms, dop=dop_val) or []
            acronyms = await self._api_get(ctx, base_url, _EP_ACRONYMS, timeout_ms, dop=dop_val) or []
            self.logger.info(f"EDOP: {dop_val} (admin={is_admin}) - {len(clauses)} clauses")

            lines = [
                f"NTPC Delegation of Powers (DoP) - {dop.get('dopName', dop_val)}",
                f"Source: {base_url} | category={dop_val} | admin_function={is_admin}",
                f"Total clauses: {len(clauses)}",
                "",
            ]
            detail_ep = _EP_DETAIL_ADMIN if is_admin else _EP_DETAIL
            for c in clauses:
                cno = c.get("clauseNo", "")
                lines.append(f"Clause {cno}: {_clean(c.get('description'))}")
                det = await self._api_get(ctx, base_url, detail_ep, timeout_ms, dop=dop_val, clauseNo=cno)
                if is_admin:
                    lines += _render_admin_detail(det)
                    if isinstance(det, dict):
                        total_detail_rows += sum(len(g.get("snoData", [])) for g in det.get("data", []) if isinstance(g, dict))
                else:
                    rows = det if isinstance(det, list) else []
                    lines += _render_nonadmin_detail(rows)
                    total_detail_rows += len(rows)
                lines.append("")
            if acronyms:
                lines.append("Acronyms:")
                lines += [f"  {a.get('acronym')}: {a.get('fullForm')}" for a in acronyms if isinstance(a, dict)]

            raw_payload[dop_val] = {"clauses": clauses, "acronyms": acronyms}
            self.note_discovered(1)
            safe = dop_val.replace(" ", "_")
            body = "\n".join(lines)
            pdf_bytes = self.text_to_pdf_bytes(
                body, f"EDOP - {dop.get('dopName', dop_val)} Delegation of Powers")
            # Stable filename (overwrite, no date) + text-based dedup so re-runs of
            # this GENERATED PDF don't accumulate dated duplicates each day.
            text_key = "edop::" + dop_val + "::" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]
            self.save_file(
                pdf_bytes, f"delegation_of_powers_{safe}.pdf",
                f"{base_url}?dop={quote(str(dop_val))}",
                exact_name=f"edop_delegation_of_powers_{safe}.pdf",
                dedup_key=text_key,
            )

        self.logger.info(f"EDOP: emitted {len(dops)} DoP PDFs (~{total_detail_rows} power rows).")
        (self.downloads_dir / f"{self.name}_api_raw.json").write_text(
            json.dumps(raw_payload, indent=2, ensure_ascii=False), encoding="utf-8")
