import asyncio
import json
import os
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright

# ============================================================
# CONFIG - Yahan apni internal site ka URL daalo office mein
# ============================================================
BASE_URL = "http://192.168.1.x"       # <- Apna internal URL daalo
MAX_DEPTH = 3                          # Kitni deep tak crawl karna hai
MAX_PAGES = 200                        # Maximum pages limit

# ============================================================
# LOGIN CONFIG - Agar site mein login chahiye toh fill karo
# ============================================================
LOGIN_REQUIRED = False                 # True karo agar login chahiye
LOGIN_URL = ""                         # Login page ka URL
LOGIN_USERNAME = ""                    # Username
LOGIN_PASSWORD = ""                    # Password
USERNAME_SELECTOR = "#username"        # Username field ka CSS selector
PASSWORD_SELECTOR = "#password"        # Password field ka CSS selector
SUBMIT_SELECTOR = "button[type=submit]"  # Submit button ka selector

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")


def clean(text):
    return " ".join(text.split()).strip()


def is_valid_url(url, base_url):
    """Sirf same domain ki links follow karo"""
    try:
        parsed_base = urlparse(base_url)
        parsed_url = urlparse(url)

        # Same domain hona chahiye
        if parsed_url.netloc and parsed_url.netloc != parsed_base.netloc:
            return False

        # Skip these file types
        skip_extensions = [
            ".pdf", ".jpg", ".jpeg", ".png", ".gif",
            ".zip", ".exe", ".doc", ".xls", ".mp4",
            ".css", ".js", ".ico", ".svg"
        ]
        path = parsed_url.path.lower()
        if any(path.endswith(ext) for ext in skip_extensions):
            return False

        # Skip anchors only links
        if url.startswith("#"):
            return False

        return True
    except:
        return False


async def login(page):
    """Login karo agar required hai"""
    if not LOGIN_REQUIRED:
        return

    print(f"🔐 Logging in at: {LOGIN_URL}")
    await page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
    await page.fill(USERNAME_SELECTOR, LOGIN_USERNAME)
    await page.fill(PASSWORD_SELECTOR, LOGIN_PASSWORD)
    await page.click(SUBMIT_SELECTOR)
    await page.wait_for_load_state("networkidle")
    print("✅ Login successful!")


async def scrape_page(page, url):
    """Ek page scrape karo aur uske links bhi nikalo"""
    print(f"  📄 Scraping: {url}")
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(1500)

        title = await page.title()

        # Extract paragraphs
        paragraphs = []
        for el in await page.query_selector_all("p"):
            t = clean(await el.inner_text())
            if len(t) > 50:
                paragraphs.append(t)

        # Extract headings
        headings = []
        for el in await page.query_selector_all("h1, h2, h3, h4"):
            t = clean(await el.inner_text())
            if t:
                headings.append(t)

        # Extract list items
        list_items = []
        for el in await page.query_selector_all("li"):
            t = clean(await el.inner_text())
            if len(t) > 20:
                list_items.append(t)

        # Extract table data
        tables = []
        for table in await page.query_selector_all("table"):
            t = clean(await table.inner_text())
            if len(t) > 30:
                tables.append(t)

        # Extract ALL links from this page
        links = []
        for el in await page.query_selector_all("a[href]"):
            href = await el.get_attribute("href")
            if href:
                full_url = urljoin(url, href)
                # Remove fragments
                full_url = full_url.split("#")[0]
                if full_url and is_valid_url(full_url, BASE_URL):
                    links.append(full_url)

        # Section name from URL
        parsed = urlparse(url)
        path_parts = parsed.path.strip("/").split("/")
        section = " > ".join(
            p.replace("-", " ").replace("_", " ").title()
            for p in path_parts if p
        ) or "Home"

        print(f"     ✓ {len(paragraphs)} paragraphs, {len(headings)} headings, {len(links)} links found")

        return {
            "url": url,
            "title": title,
            "section": section,
            "headings": headings,
            "paragraphs": paragraphs,
            "list_items": list_items,
            "tables": tables,
            "links": links  # Yeh next pages ke liye use hoga
        }

    except Exception as e:
        print(f"     ❌ Failed: {e}")
        return None


async def crawl_website():
    """Recursive crawler - automatically saari links follow karega"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    visited = set()       # Kaunse pages ho gaye
    to_visit = [(BASE_URL, 0)]  # (url, depth)
    all_pages = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            ignore_https_errors=True  # Internal sites mein SSL issues ho sakte hain
        )
        page = await context.new_page()

        # Pehle login karo agar required hai
        await login(page)

        print(f"\n🚀 Starting crawl from: {BASE_URL}")
        print(f"   Max depth: {MAX_DEPTH} | Max pages: {MAX_PAGES}\n")

        while to_visit and len(all_pages) < MAX_PAGES:
            url, depth = to_visit.pop(0)

            # Already visited? Skip karo
            if url in visited:
                continue

            # Too deep? Skip karo
            if depth > MAX_DEPTH:
                continue

            visited.add(url)
            print(f"[{len(all_pages)+1}/{MAX_PAGES}] Depth {depth}: ", end="")

            data = await scrape_page(page, url)

            if data:
                # Links save karo aur queue mein daalo
                new_links = data.pop("links", [])
                all_pages.append(data)

                # Naye links queue mein daalo
                for link in new_links:
                    if link not in visited:
                        to_visit.append((link, depth + 1))

                # Duplicate links remove karo queue se
                seen = set()
                unique_queue = []
                for item in to_visit:
                    if item[0] not in seen and item[0] not in visited:
                        seen.add(item[0])
                        unique_queue.append(item)
                to_visit = unique_queue

            await asyncio.sleep(0.5)  # Thoda wait - server pe load na pade

        await browser.close()

    # Save results
    output_file = os.path.join(OUTPUT_DIR, "pages.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_pages, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"✅ Crawling complete!")
    print(f"   Pages scraped: {len(all_pages)}")
    print(f"   Saved to: {output_file}")
    print(f"   Next step: Run indexer.py")
    print(f"{'='*50}\n")

    return all_pages


if __name__ == "__main__":
    asyncio.run(crawl_website())