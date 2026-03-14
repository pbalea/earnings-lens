import time
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from app.config import settings

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


def fetch_motley_fool_transcript(ticker: str, url: str) -> str:
    """Fetch a Motley Fool earnings call transcript page and return plain text.

    Args:
        ticker: Company ticker symbol (used for logging / future filtering).
        url:    Full URL to the Motley Fool transcript article.

    Returns:
        Plain text of the article body, HTML stripped.

    Raises:
        httpx.HTTPStatusError: on non-2xx responses.
    """
    headers = {"User-Agent": _USER_AGENT}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=30) as client:
        response = client.get(url)
        response.raise_for_status()

    time.sleep(settings.scrape_delay_seconds)

    soup = BeautifulSoup(response.text, "html.parser")

    # Motley Fool wraps article content in <div class="article-body"> or
    # falls back to the first <article> element.
    article = (
        soup.find("div", class_="article-body")
        or soup.find("article")
        or soup.find("main")
        or soup.body
    )

    if article is None:
        return soup.get_text(separator="\n", strip=True)

    return article.get_text(separator="\n", strip=True)


def fetch_by_ticker(ticker: str, quarter: str, year: int) -> Optional[str]:
    """Stub — search for and fetch a transcript by ticker/quarter/year.

    TODO: implement transcript search (e.g. via site search or a transcript
    index API) to resolve a URL automatically, then delegate to
    fetch_motley_fool_transcript().

    Args:
        ticker:  Company ticker, e.g. "AAPL".
        quarter: Fiscal quarter, e.g. "Q3".
        year:    Fiscal year, e.g. 2024.

    Returns:
        Raw transcript text, or None if not found.
    """
    raise NotImplementedError(
        "fetch_by_ticker is a stub. "
        "Provide an explicit URL via fetch_motley_fool_transcript() for now."
    )
