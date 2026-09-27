# financial_news_scraper.py
# Scrapes news headlines from FinancialJuice and stores them in a Windmill Data Table.

from datetime import datetime, timezone
from playwright.sync_api import sync_playwright
import wmill


# ---------- Database Setup ----------
def ensure_table_exists(db):
    """Ensure the table and the UNIQUE index on headline exist."""
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS financial_news (
        id SERIAL PRIMARY KEY,
        headline TEXT NOT NULL,
        url TEXT,
        published_at TIMESTAMPTZ,
        source TEXT DEFAULT 'FinancialJuice',
        scraped_at TIMESTAMPTZ DEFAULT NOW()
    );
    """
    db.query(create_table_sql).execute()

    # Create unique index specifically for headline if it doesn't exist
    create_index_sql = """
    CREATE UNIQUE INDEX IF NOT EXISTS financial_news_headline_idx 
    ON financial_news (headline);
    """
    db.query(create_index_sql).execute()


# ---------- Scraping Logic ----------
def scrape_news(page):
    """Extract news items from FinancialJuice using page.evaluate() for faster execution.

    Returns a list of dicts with keys: headline, url, published_at.
    """
    # Wait for the main feed container to appear
    page.wait_for_selector("#mainFeed", timeout=15_000, state="attached")

    # Execute JavaScript directly in the browser context to parse DOM elements
    raw_news = page.evaluate("""
        () => {
            const items = document.querySelectorAll('.infinite-item');
            const data = [];

            items.forEach(item => {
                const linkEl = item.querySelector('social-nav');
                
                // Extract headline text (prefer link text, fallback to item container text)
                const headline = linkEl ? linkEl.innerText.trim() : item.innerText.trim();
                
                // Extract URL (href attribute)
                const url = linkEl ? linkEl.getAttribute('href') : null;

                // Filter out ad banners or empty items
                if (headline && !headline.includes("GO PRO") && !headline.includes("Don't like Ads")) {
                    data.push({
                        headline: headline,
                        url: url
                    });
                }
            });

            return data;
        }
    """)

    # Attach current UTC timestamp in Python context
    current_time = datetime.now(timezone.utc).isoformat()
    news_list = [
        {
            "headline": item["headline"],
            "url": item["url"],
            "published_at": current_time,
        }
        for item in raw_news
    ]

    return news_list


# ---------- Main Entry Point ----------
def main(page_num: int = 0):
    """Connect to an already-open Steel browser via CDP,

    scrape FinancialJuice news, and insert each item into Windmill Data Table.

    Args:
        page_num: Index of the browser tab of FinancialJuice.
    """
    # 1. Connect to Windmill Data Table and ensure schema exists.
    db = wmill.datatable()
    ensure_table_exists(db)

    # 2. Connect to the running Steel browser.
    with sync_playwright() as p:
        # The working endpoint from your environment (Steel API on port 3000).
        browser = p.chromium.connect_over_cdp("ws://172.22.0.250:3000")

        # Use the requested browser context and its first page.
        context = browser.contexts[page_num]
        page = context.pages[0]

        # 4. Scrape the headlines.
        news_items = scrape_news(page)

        # 5. Insert each item into the Data Table.
        inserted = 0
        for item in news_items:
            try:
                # Matches the UNIQUE INDEX on (headline)
                db.query(
                    """
                    INSERT INTO financial_news (headline, url, published_at)
                    VALUES ($1, $2, $3::timestamptz)
                    ON CONFLICT (headline) DO NOTHING;
                    """,
                    item["headline"],
                    item["url"],
                    item["published_at"],
                ).execute()
                inserted += 1
            except Exception as e:
                # Log and continue; one bad row should not abort the whole batch.
                print(f"Failed to insert '{item['headline'][:50]}...': {e}")

        # Confirm actual row count in the database
        total = db.query("SELECT COUNT(*) FROM financial_news;").fetch_one_scalar()
        print(f"Scraped {len(news_items)} items, inserted {inserted} rows.")
        print(f"Total rows now in financial_news: {total}")

        # Do NOT call browser.close() – we are attached to an external browser.
        # Closing it would shut down the Steel session for other users.