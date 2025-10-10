from datetime import datetime, timezone

from resources.cloudflare_blog.collector import CloudflareBlogCollector, FetchParams


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise ValueError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: dict[str, FakeResponse]) -> None:
        self._responses = responses
        self.headers = {}

    def get(self, url: str, timeout: int = 30) -> FakeResponse:
        response = self._responses.get(url)
        if not response:
            raise ValueError(f"Unexpected URL: {url}")
        return response


def test_collect_and_normalize_cloudflare_blog():
    listing_html = """
    <html>
      <body>
        <article>
          <a data-testid="post-title" href="/example-post/">
            <h2>Example Post</h2>
          </a>
          <p data-testid="post-date">2025-10-09</p>
          <p data-testid="post-content">Concise summary from listing.</p>
          <ul class="author-lists">
            <li><a>Alex Author</a></li>
            <li><a>Jamie Writer</a></li>
          </ul>
          <img src="https://blog.cloudflare.com/images/example.png" />
        </article>
      </body>
    </html>
    """
    detail_html = """
    <html>
      <head>
        <meta property="og:title" content="Example Post" />
        <meta property="og:description" content="Deep dive on an example topic." />
        <meta property="og:image" content="https://assets.cloudflare.com/example.png" />
        <meta property="article:published_time" content="2025-10-09T14:00:00+00:00" />
        <meta property="article:modified_time" content="2025-10-09T15:00:00+00:00" />
        <meta property="article:tag" content="Cloudflare" />
        <meta property="article:tag" content="Networking" />
        <link rel="canonical" href="https://blog.cloudflare.com/example-post/" />
      </head>
      <body>
        <article class="post-full">
          <p>2025-10-09</p>
          <p>First paragraph of the article.</p>
          <p>Second paragraph continues the story.</p>
          <ul class="author-lists">
            <li><a>Alex Author</a></li>
            <li><a>Jamie Writer</a></li>
          </ul>
        </article>
      </body>
    </html>
    """

    responses = {
        "https://blog.cloudflare.com/": FakeResponse(listing_html),
        "https://blog.cloudflare.com/example-post/": FakeResponse(detail_html),
    }

    session = FakeSession(responses)
    collector = CloudflareBlogCollector(session=session)

    bulletins = collector.collect(params=FetchParams(limit=1))
    assert len(bulletins) == 1
    bulletin = bulletins[0]

    assert bulletin.source.source_slug == "cloudflare_blog"
    assert str(bulletin.source.origin_url) == "https://blog.cloudflare.com/example-post/"
    assert bulletin.content.title == "Example Post"
    assert bulletin.content.summary == "Deep dive on an example topic."
    assert bulletin.content.body_text == "First paragraph of the article.\n\nSecond paragraph continues the story."
    assert bulletin.content.published_at == datetime(2025, 10, 9, 14, 0, tzinfo=timezone.utc)
    assert bulletin.topics == ["tech-blog"]

    assert "tag:cloudflare" in bulletin.labels
    assert "tag:networking" in bulletin.labels
    assert "author:alex author" in bulletin.labels
    assert "author:jamie writer" in bulletin.labels

    assert bulletin.extra is not None
    assert bulletin.extra.get("hero_image") == "https://assets.cloudflare.com/example.png"
    assert bulletin.extra.get("listing_image") == "https://blog.cloudflare.com/images/example.png"
    assert bulletin.extra.get("modified_time") == "2025-10-09T15:00:00+00:00"
    assert bulletin.extra.get("tags") == ["Cloudflare", "Networking"]
    assert bulletin.extra.get("authors") == ["Alex Author", "Jamie Writer"]
