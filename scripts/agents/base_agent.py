"""
Base agent: retry/backoff, hash-based dedup, file saving, network health check,
per-run file logging. All fetch agents inherit from BaseAgent.

Cross-platform note (Windows port): log messages use ASCII tags ([ok]/[skip]/
[fail]) instead of Unicode glyphs, because the default Windows console code page
(cp1252) raises UnicodeEncodeError on characters like the check-mark glyphs.
"""

import asyncio
import hashlib
import json
import logging
import re
import socket
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

# Browser-like UA shared by the Playwright context and httpx downloads.
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class DownloadManifest:
    """
    Tracks every downloaded file by SHA-256 hash to prevent re-downloading
    unchanged content.  Stored as a flat JSON dict at MANIFEST_PATH.
    """

    def __init__(self, manifest_path: Path):
        self.path = manifest_path
        self.data: dict = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def is_known(self, file_hash: str) -> bool:
        return file_hash in self.data

    def record(self, file_hash: str, filename: str, source: str, url: str):
        self.data[file_hash] = {
            "filename": filename,
            "source": source,
            "url": url,
            "downloaded_at": datetime.now().isoformat(),
        }
        self.save()

    def seed_from_dir(self, directory: Path, source: str = "preexisting") -> int:
        """
        Register the content-hash of every file already present in `directory`
        so that downloading an identical file is skipped. Makes re-runs
        idempotent and stops the agents from duplicating files that a human
        already placed in the reports folder. Returns the count newly seeded.
        """
        if not directory.exists():
            return 0
        seeded = 0
        for f in sorted(directory.iterdir()):
            if not f.is_file():
                continue
            try:
                h = hashlib.sha256(f.read_bytes()).hexdigest()[:20]
            except OSError:
                continue
            if h not in self.data:
                self.data[h] = {
                    "filename": f.name,
                    "source": source,
                    "url": "preexisting-local-file",
                    "downloaded_at": datetime.now().isoformat(),
                }
                seeded += 1
        if seeded:
            self.save()
        return seeded


class BaseAgent(ABC):
    """
    Abstract base for all four fetch agents.

    Subclasses must set:
        name: str       — short slug used in filenames and logs
        _host: str      — hostname to ping for network check (no scheme)
        _port: int      — port to check (default 80)

    And implement:
        async _fetch()  — all site-specific fetch logic
    """

    name: str = "base"
    _host: str = ""
    _port: int = 80

    def __init__(self, config: dict, manifest: DownloadManifest):
        self.config = config
        self.manifest = manifest
        self.timeout: int = int(config.get("AGENT_TIMEOUT_SECONDS", 120))
        self.max_retries: int = int(config.get("AGENT_MAX_RETRIES", 3))
        self.retry_backoff: int = int(config.get("AGENT_RETRY_BACKOFF_SECONDS", 5))
        # Safety cap on files downloaded per run (0 = unlimited).
        self.max_files: int = int(config.get("AGENT_MAX_FILES", 0))
        self.pdf_dir = Path(config["PDF_DIR"])
        self.downloads_dir = Path(config["DOWNLOADS_DIR"]) / self.name
        self.log_dir = Path(config.get("LOG_DIR", "logs/agents"))

        # Headless can be overridden per run (orchestrator --headed flag).
        self.headless: bool = str(
            config.get("PLAYWRIGHT_HEADLESS", "true")
        ).strip().lower() not in ("false", "0", "no", "off")

        self.log_path: Optional[Path] = None
        self.logger = self._make_logger()
        self.stats: dict = {
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "discovered": 0,   # candidate files seen on the page(s)
            "files": [],
            "status": "pending",
            "duration_sec": 0.0,
        }

    # ------------------------------------------------------------------ #
    # Logging                                                              #
    # ------------------------------------------------------------------ #

    def _make_logger(self) -> logging.Logger:
        """Console (stderr) + per-run UTF-8 file handler at logs/agents/<name>_<ts>.log."""
        logger = logging.getLogger(f"agent.{self.name}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        # Reset handlers so re-instantiating the agent does not duplicate output.
        for h in list(logger.handlers):
            logger.removeHandler(h)

        fmt = logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s - %(message)s",
            datefmt="%H:%M:%S",
        )

        console = logging.StreamHandler()
        console.setFormatter(fmt)
        logger.addHandler(console)

        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.log_path = self.log_dir / f"{self.name}_{ts}.log"
            file_handler = logging.FileHandler(self.log_path, encoding="utf-8")
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
        except OSError as exc:  # logging must never crash the agent
            logger.warning(f"Could not open log file: {exc}")

        return logger

    # ------------------------------------------------------------------ #
    # Network health                                                       #
    # ------------------------------------------------------------------ #

    def check_network(self) -> tuple[bool, str, str]:
        """
        Returns (reachable, status, message).

        status is one of:
            reachable    — TCP connect succeeded
            refused      — host answered but the port is closed
            timeout      — connection timed out (commonly off-LAN intranet)
            dns_failure  — hostname could not be resolved
            unreachable  — no route / other socket error
        """
        host, port = self._host, self._port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        try:
            result = sock.connect_ex((host, port))
            if result == 0:
                return True, "reachable", f"{host}:{port} reachable"
            return (
                True,
                "refused",
                f"{host}:{port} answered but port appears closed (site may be down)",
            )
        except socket.timeout:
            return False, "timeout", f"Timeout connecting to {host}:{port}"
        except socket.gaierror:
            return (
                False,
                "dns_failure",
                f"DNS resolution failed for {host!r} - off NTPC intranet / LAN / VPN",
            )
        except OSError as exc:
            return (
                False,
                "unreachable",
                f"Off NTPC intranet - host unreachable: {host}:{port} ({exc})",
            )
        finally:
            sock.close()

    # ------------------------------------------------------------------ #
    # File handling                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _hash(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()[:20]

    def _stable_name(self, original_name: str) -> str:
        # {source_tag}_{YYYYMMDD}_{original}.{ext}
        date = datetime.now().strftime("%Y%m%d")
        return f"{self.name}_{date}_{original_name}"

    def note_discovered(self, count: int = 1):
        """Record that `count` candidate downloadable files were seen on a page."""
        self.stats["discovered"] += count

    def save_file(self, content: bytes, original_name: str, url: str,
                  exact_name: Optional[str] = None,
                  dedup_key: Optional[str] = None) -> Optional[Path]:
        """
        Hash-deduplicate, then save to the right folder:
            .pdf  -> pdf_dir  (what the indexer already reads)
            other -> downloads_dir / agent_name  (Excel/Word/CSV/TXT/JSON)
        If `exact_name` is given it is used verbatim (sanitized) instead of the
        {tag}_{date}_{original} convention - lets agents control the final name.
        If `dedup_key` is given, dedup uses it instead of the content hash - use
        this for GENERATED content (e.g. PDFs rendered from text) whose bytes are
        not stable across runs, so identical logical content is still skipped.
        Returns the saved path, or None if duplicate/skipped.
        """
        if not content:
            self.logger.warning(f"  [skip] empty content: {original_name}")
            return None

        key = dedup_key or self._hash(content)
        if self.manifest.is_known(key):
            self.logger.info(f"  [skip] unchanged (already saved): {original_name}")
            self.stats["skipped"] += 1
            return None

        # URL-decode (%20 -> space) then strip characters illegal in Windows
        # filenames, so names stay clean and match the chatbot's file mapping.
        if exact_name:
            decoded = unquote(Path(exact_name).name).strip() or "document"
            safe_original = re.sub(r'[<>:"/\\|?*]', "_", decoded)
            filename = safe_original
        else:
            decoded = unquote(Path(original_name).name).strip() or "document"
            safe_original = re.sub(r'[<>:"/\\|?*]', "_", decoded)
            filename = self._stable_name(safe_original)
        ext = Path(safe_original).suffix.lower()

        if ext == ".pdf":
            dest_dir = self.pdf_dir
        else:
            dest_dir = self.downloads_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / filename

        try:
            dest.write_bytes(content)
        except OSError as exc:
            self.logger.error(f"  [fail] could not write {filename}: {exc}")
            self.stats["failed"] += 1
            return None

        self.manifest.record(key, filename, self.name, url)
        self.logger.info(f"  [ok] saved: {filename} ({len(content)//1024} KB) <- {url}")
        self.stats["downloaded"] += 1
        self.stats["files"].append(str(dest))
        return dest

    @staticmethod
    def text_to_pdf_bytes(text: str, title: str = "") -> bytes:
        """
        Render plain text into a simple multi-page PDF (via PyMuPDF) so that
        API/JSON sources can flow through the existing PDF indexing pipeline
        without changing the indexer. Returns the PDF bytes.
        """
        import textwrap

        import fitz  # PyMuPDF

        fontsize = 10
        leading = fontsize * 1.45
        margin = 50
        lines: list[str] = []
        if title:
            lines += [title, ""]
        for raw in text.split("\n"):
            lines += textwrap.wrap(raw, width=95) or [""]

        doc = fitz.open()
        page = doc.new_page()
        height = page.rect.height
        y = margin
        for line in lines:
            if y > height - margin:
                page = doc.new_page()
                y = margin
            page.insert_text((margin, y), line, fontsize=fontsize, fontname="helv")
            y += leading
        doc.set_metadata({})  # drop nondeterministic creation timestamps
        return doc.tobytes()

    @staticmethod
    def extract_main_text(html: str) -> str:
        """
        Extract readable body text from rendered HTML, stripping nav/header/
        footer/scripts. Used by page-content agents (wiki, safety pages).
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "header",
                         "footer", "aside", "form", "svg", "button"]):
            tag.decompose()
        main = (soup.find("main") or soup.find("article")
                or soup.find(id=re.compile("content|main|article", re.I))
                or soup.find(class_=re.compile("content|article|main|post", re.I))
                or soup.body or soup)
        lines = [ln.strip() for ln in main.get_text(separator="\n").splitlines()]
        return "\n".join(ln for ln in lines if ln)

    async def download_via_context(self, context, links: list[tuple[str, str]],
                                   referer: Optional[str] = None):
        """
        Download (url, original_name) pairs through the *browser's* network
        context (context.request). This reuses Chromium's proxy, cookies and TLS
        session, so it succeeds in corporate-proxy / WAF environments where a
        plain httpx request is blocked (e.g. NTPC's '403 URLBlocked'). Each
        failure is isolated. Pass the page URL as `referer` - some WAFs reject
        direct file requests that lack one.
        """
        if not links:
            return
        if self.max_files and len(links) > self.max_files:
            self.logger.info(
                f"Capping downloads to AGENT_MAX_FILES={self.max_files} of {len(links)} discovered."
            )
            links = links[: self.max_files]
        timeout_ms = float(self.config.get("HTTP_TIMEOUT_SECONDS", 60)) * 1000
        headers = {"Referer": referer} if referer else None
        for url, original_name in links:
            self.logger.info(f"Downloading (browser): {original_name}")
            try:
                resp = await context.request.get(url, headers=headers, timeout=timeout_ms)
                if resp.ok:
                    self.save_file(await resp.body(), original_name, url)
                else:
                    self.logger.error(
                        f"  [fail] {original_name}: HTTP {resp.status} {resp.status_text}"
                    )
                    self.stats["failed"] += 1
            except Exception as exc:
                self.logger.error(
                    f"  [fail] {original_name}: {type(exc).__name__}: {exc}"
                )
                self.stats["failed"] += 1

    async def download_http_links(self, links: list[tuple[str, str]]):
        """
        FALLBACK downloader: fetch (url, original_name) pairs over plain HTTP
        (httpx). Used only for sources reachable without the browser's proxy
        session. Each failure is isolated so one bad link cannot abort the rest.
        """
        if not links:
            return
        if self.max_files and len(links) > self.max_files:
            self.logger.info(
                f"Capping downloads to AGENT_MAX_FILES={self.max_files} of {len(links)} discovered."
            )
            links = links[: self.max_files]
        import httpx  # local import keeps httpx optional for non-fetch use

        http_timeout = float(self.config.get("HTTP_TIMEOUT_SECONDS", 60))
        async with httpx.AsyncClient(
            verify=False,
            follow_redirects=True,
            timeout=http_timeout,
            headers={"User-Agent": DEFAULT_UA},
        ) as client:
            for url, original_name in links:
                self.logger.info(f"Downloading: {original_name}")
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    self.save_file(resp.content, original_name, url)
                except Exception as exc:
                    self.logger.error(
                        f"  [fail] {original_name}: {type(exc).__name__}: {exc}"
                    )
                    self.stats["failed"] += 1

    # ------------------------------------------------------------------ #
    # Run with retry / backoff                                            #
    # ------------------------------------------------------------------ #

    async def run_with_retry(self) -> dict:
        """Network check -> retry loop -> classify outcome -> return stats dict."""
        start = time.monotonic()
        reachable, status, msg = self.check_network()
        if not reachable:
            self.logger.error(f"Network check failed [{status}]: {msg}")
            self.stats["success"] = False
            self.stats["status"] = status  # timeout / dns_failure / unreachable
            self.stats["error"] = msg
            self.stats["duration_sec"] = round(time.monotonic() - start, 1)
            return self.stats

        self.logger.info(f"Network check OK: {msg}")

        last_error: Optional[str] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.info(f"Attempt {attempt}/{self.max_retries} ...")
                await asyncio.wait_for(self._fetch(), timeout=self.timeout)

                # Reachable + navigated, but nothing discovered => structure/selector drift.
                if self.stats["discovered"] == 0 and self.stats["downloaded"] == 0:
                    self.stats["success"] = True
                    self.stats["status"] = "structure_changed"
                    self.logger.warning(
                        "Host reachable but NO downloadable files were discovered - "
                        "the page structure or CSS selectors likely changed and need tuning."
                    )
                else:
                    self.stats["success"] = True
                    self.stats["status"] = "ok"
                self.stats["duration_sec"] = round(time.monotonic() - start, 1)
                self.logger.info(
                    f"Done in {self.stats['duration_sec']}s - "
                    f"downloaded={self.stats['downloaded']} "
                    f"skipped={self.stats['skipped']} "
                    f"failed={self.stats['failed']} "
                    f"discovered={self.stats['discovered']}"
                )
                return self.stats
            except asyncio.TimeoutError:
                last_error = f"Fetch timed out after {self.timeout}s"
                self.logger.warning(f"  Attempt {attempt} timed out")
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self.logger.warning(f"  Attempt {attempt} failed: {last_error}")

            if attempt < self.max_retries:
                wait = self.retry_backoff * (2 ** (attempt - 1))
                self.logger.info(f"  Retrying in {wait}s ...")
                await asyncio.sleep(wait)

        self.stats["success"] = False
        self.stats["status"] = "error"
        self.stats["error"] = last_error
        self.stats["duration_sec"] = round(time.monotonic() - start, 1)
        return self.stats

    # ------------------------------------------------------------------ #
    # To implement                                                        #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def _fetch(self):
        """Site-specific fetch logic. Called by run_with_retry()."""
