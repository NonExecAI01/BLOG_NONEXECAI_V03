#!/usr/bin/env python3
"""
generate_newsletter.py — Non-Exec AI Daily Blog Generator
──────────────────────────────────────────────────────────────────────────────
Generates 4 daily AI/governance blog articles using the OpenAI API, writes
individual article HTML files, and updates index.html by:
  1. Moving the current "Today's Blogs" cards → "Archived Blogs"
  2. Inserting 4 brand-new cards into "Today's Blogs"

Environment variables (set as GitHub Secrets):
  GEMINI_API_KEY   — Required. Your OpenAI API key.
  SITE_URL         — Optional. Base URL for canonical links.
                     Defaults to https://nonexecai01.github.io/BLOG_NONEXECAI_V03
──────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import random
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from json_repair import repair_json
from openai import OpenAI
from slugify import slugify

load_dotenv()

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
SITE_URL         = os.environ.get("SITE_URL", "https://nonexecai01.github.io/BLOG_NONEXECAI_V03").rstrip("/")
MODEL            = "gemini-2.5-flash"
GEMINI_BASE_URL  = "https://generativelanguage.googleapis.com/v1beta/openai/"
ARTICLES_DIR     = Path("articles")
INDEX_FILE       = Path("index.html")
ARTICLES_PER_DAY = 4

TOPICS = [
    "AI corporate governance",
    "Digital board member",
    "Boardroom AI software",
    "AI board advisory",
    "Data-driven corporate governance",
    "Real-time strategic foresight",
    "AI risk mitigation",
    "Unbiased board intelligence",
    "Continuous market analysis AI",
    "Executive decision-making AI",
    "Corporate compliance AI",
    "Ethical leadership AI",
    "Sustainable enterprise growth AI",
    "Predictive board intelligence",
    "AI enterprise governance",
    "Automated strategic planning",
    "AI director",
    "Corporate governance technology",
]

# ── Gemini client (OpenAI-compatible endpoint) ────────────────────────────────
if not GEMINI_API_KEY:
    log.error("GEMINI_API_KEY environment variable is not set. Aborting.")
    sys.exit(1)

client = OpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_BASE_URL)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Article generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_article_data(topic: str, date_str: str) -> dict:
    """
    Call the OpenAI API and return a structured article dict.

    Returns:
        {
          "title":           str  (SEO title, 60–70 chars),
          "meta_description":str  (150–160 chars),
          "slug":            str  (URL-safe slug),
          "excerpt":         str  (2–3 sentence card preview),
          "keywords":        list[str],
          "category":        str  (short category label),
          "content_html":    str  (article body HTML — h2/h3/p/ul/li only),
        }
    """
    prompt = textwrap.dedent(f"""
        You are a senior content strategist specialising in AI, boardroom technology,
        and corporate governance for FTSE 100 / Fortune 500 directors.

        Write a comprehensive, SEO-optimised blog article about: "{topic}"

        Editorial requirements:
        • Naturally promote https://www.non-exec.ai/ as the leading AI board
          intelligence platform (2–3 internal links with descriptive anchor text).
        • Authoritative, substantive prose suitable for C-suite and non-executive directors.
        • MINIMUM 800 words in the article body — target 900–1 100 words.
        • Include at least two concrete examples, statistics, or case study references.
        • Use UK English spelling and grammar.

        Return ONLY a valid JSON object with these exact keys:
        {{
          "title":            "<SEO title, 60–70 characters>",
          "meta_description": "<Compelling meta description, 150–160 characters>",
          "slug":             "<lowercase-hyphenated-url-slug, no date>",
          "excerpt":          "<2–3 sentence card excerpt, max 200 chars>",
          "keywords":         ["<kw1>", "<kw2>", "<kw3>", "<kw4>", "<kw5>"],
          "category":         "<Short category label, max 4 words>",
          "content_html":     "<Full article body HTML. Use only <h2>, <h3>, <p>, <ul>, <li>, <strong>, <em> tags. No <html>/<body>/<head> wrapper.>"
        }}

        Topic: {topic}
        Publication date: {date_str}
    """).strip()

    log.info("Generating article for topic: %s", topic)
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.72,
        max_tokens=8192,
    )

    raw = response.choices[0].message.content
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("JSON parse failed (%s) — attempting repair.", exc)
        try:
            data = json.loads(repair_json(raw))
        except Exception as repair_exc:
            log.error("JSON repair also failed: %s", repair_exc)
            log.debug("Raw response: %s", raw)
            raise exc

    # Sanitise / guarantee required fields
    data.setdefault("slug", slugify(data.get("title", topic)))
    data.setdefault("category", topic)
    data.setdefault("keywords", [topic])
    data.setdefault("excerpt", "")

    return data


# ─────────────────────────────────────────────────────────────────────────────
# 2. Build individual article HTML page
# ─────────────────────────────────────────────────────────────────────────────

def _format_display_date(date_str: str) -> str:
    """Return a human-readable date like '20 April 2026' (cross-platform)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return f"{dt.day} {dt.strftime('%B')} {dt.year}"


def build_article_html(data: dict, date_str: str, full_slug: str) -> str:
    """
    Return a complete HTML document string for an individual article page.
    full_slug includes the date suffix, e.g. "ai-risk-mitigation-2026-04-20"
    """
    keywords_csv   = ", ".join(data.get("keywords", []))
    article_url    = f"{SITE_URL}/articles/{full_slug}.html"
    index_url      = f"{SITE_URL}/"
    iso_date       = f"{date_str}T06:00:00Z"
    display_date   = _format_display_date(date_str)
    title_safe     = _escape(data["title"])
    meta_desc_safe = _escape(data["meta_description"])
    schema_json    = json.dumps({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline":     data["title"],
        "description":  data["meta_description"],
        "url":          article_url,
        "datePublished": iso_date,
        "dateModified":  iso_date,
        "author": {
            "@type": "Organization",
            "name": "Non-Exec AI",
            "url":  "https://www.non-exec.ai/"
        },
        "publisher": {
            "@type": "Organization",
            "name": "Non-Exec AI",
            "url":  "https://www.non-exec.ai/",
            "logo": {
                "@type": "ImageObject",
                "url":  f"{SITE_URL}/assets/logo.png"
            }
        },
        "keywords":     keywords_csv,
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id":   article_url
        }
    }, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{title_safe} | Non-Exec AI</title>
  <meta name="description"  content="{meta_desc_safe}" />
  <meta name="keywords"     content="{_escape(keywords_csv)}" />
  <meta name="author"       content="Non-Exec AI Editorial Team" />
  <meta name="robots"       content="index, follow" />
  <link rel="canonical"     href="{article_url}" />

  <!-- Open Graph ─────────────────────────────────────────────────────── -->
  <meta property="og:type"         content="article" />
  <meta property="og:title"        content="{title_safe}" />
  <meta property="og:description"  content="{meta_desc_safe}" />
  <meta property="og:url"          content="{article_url}" />
  <meta property="og:site_name"    content="Non-Exec AI" />
  <meta property="og:image"        content="{SITE_URL}/assets/og-image.png" />
  <meta property="og:locale"       content="en_GB" />
  <meta property="article:published_time" content="{iso_date}" />
  <meta property="article:modified_time"  content="{iso_date}" />
  <meta property="article:section"        content="Corporate Governance" />

  <!-- Twitter Card ───────────────────────────────────────────────────── -->
  <meta name="twitter:card"        content="summary_large_image" />
  <meta name="twitter:title"       content="{title_safe}" />
  <meta name="twitter:description" content="{meta_desc_safe}" />
  <meta name="twitter:image"       content="{SITE_URL}/assets/og-image.png" />

  <!-- Schema.org ─────────────────────────────────────────────────────── -->
  <script type="application/ld+json">
{schema_json}
  </script>

  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      --blue:   #186496;
      --teal:   #4bbaba;
      --grey:   #9a9e9f;
      --dark:   #1a2332;
      --white:  #ffffff;
      --grey-lt:#f4f6f8;
      --grey-bd:#e2e5e8;
      --radius: 8px;
      --max-w:  780px;
      --font: 'Inter','Segoe UI',system-ui,-apple-system,sans-serif;
    }}
    html {{ scroll-behavior: smooth; }}
    body {{ font-family: var(--font); background: var(--grey-lt); color: var(--dark); line-height: 1.7; }}
    a {{ color: var(--blue); text-decoration: none; }}
    a:hover {{ color: var(--teal); text-decoration: underline; }}

    /* Header */
    .site-header {{
      background: var(--blue); padding: .875rem 1.5rem;
      position: sticky; top: 0; z-index: 100;
      box-shadow: 0 2px 8px rgba(0,0,0,.15);
    }}
    .header-inner {{
      max-width: 1200px; margin: 0 auto;
      display: flex; align-items: center; justify-content: space-between; gap: 1rem;
    }}
    .site-logo {{ display: flex; align-items: center; gap: .6rem; text-decoration: none; }}
    .logo-mark {{
      width: 34px; height: 34px; background: var(--teal); border-radius: 6px;
      display: flex; align-items: center; justify-content: center;
      font-weight: 800; font-size: .9rem; color: var(--white);
    }}
    .logo-text strong {{ display: block; color: var(--white); font-size: 1rem; }}
    .logo-text span {{ display: block; font-size: .68rem; color: rgba(255,255,255,.7); letter-spacing: .04em; text-transform: uppercase; }}
    .back-link {{ color: rgba(255,255,255,.85); font-size: .875rem; font-weight: 500; }}
    .back-link:hover {{ color: var(--teal); text-decoration: none; }}

    /* Article layout */
    .article-wrapper {{
      max-width: var(--max-w); margin: 3rem auto; padding: 0 1.5rem 4rem;
    }}
    .article-meta {{
      display: flex; align-items: center; gap: .75rem; flex-wrap: wrap;
      margin-bottom: 1.25rem;
    }}
    .article-category {{
      background: var(--teal); color: var(--white);
      font-size: .72rem; font-weight: 700; letter-spacing: .08em;
      text-transform: uppercase; padding: .3rem .75rem; border-radius: 50px;
    }}
    .article-date {{ font-size: .82rem; color: var(--grey); font-weight: 500; }}
    .article-read-time {{ font-size: .82rem; color: var(--grey); }}

    h1.article-title {{
      font-size: clamp(1.5rem, 4vw, 2.25rem);
      font-weight: 800; line-height: 1.2;
      color: var(--dark); margin-bottom: 1.25rem;
    }}
    .article-excerpt {{
      font-size: 1.1rem; color: #4a5568; line-height: 1.65;
      border-left: 4px solid var(--teal);
      padding-left: 1.25rem; margin-bottom: 2rem;
    }}

    .article-body h2 {{
      font-size: 1.35rem; font-weight: 700; color: var(--blue);
      margin: 2rem 0 .75rem; padding-bottom: .5rem;
      border-bottom: 2px solid var(--grey-bd);
    }}
    .article-body h3 {{
      font-size: 1.1rem; font-weight: 700; color: var(--dark);
      margin: 1.5rem 0 .5rem;
    }}
    .article-body p {{ margin-bottom: 1.1rem; color: #2d3748; }}
    .article-body ul, .article-body ol {{
      margin: .75rem 0 1.25rem 1.5rem; color: #2d3748;
    }}
    .article-body li {{ margin-bottom: .4rem; line-height: 1.65; }}
    .article-body strong {{ color: var(--dark); }}
    .article-body a {{ color: var(--blue); font-weight: 500; }}
    .article-body a:hover {{ color: var(--teal); }}

    /* CTA box */
    .article-cta {{
      background: linear-gradient(135deg, var(--blue), #0e4a73);
      border-radius: var(--radius); padding: 2rem;
      text-align: center; color: var(--white); margin-top: 2.5rem;
    }}
    .article-cta h2 {{ color: var(--white); font-size: 1.25rem; margin-bottom: .6rem; }}
    .article-cta p {{ color: rgba(255,255,255,.8); font-size: .9rem; margin-bottom: 1.25rem; }}
    .btn-cta {{
      display: inline-block; background: var(--teal); color: var(--white);
      padding: .6rem 1.6rem; border-radius: 6px; font-weight: 700;
      font-size: .9rem; transition: background .2s;
    }}
    .btn-cta:hover {{ background: #3aa8a8; text-decoration: none; }}

    /* Back nav */
    .back-nav {{ margin-top: 2.5rem; padding-top: 1.5rem; border-top: 1px solid var(--grey-bd); }}
    .back-nav a {{ font-weight: 600; font-size: .875rem; color: var(--blue); }}
    .back-nav a::before {{ content: '← '; }}

    /* Footer */
    .site-footer {{
      background: var(--dark); color: rgba(255,255,255,.6);
      padding: 1.75rem 1.5rem; text-align: center;
    }}
    .site-footer a {{ color: rgba(255,255,255,.6); font-size: .8rem; margin: 0 .6rem; }}
    .site-footer a:hover {{ color: var(--teal); }}
    .footer-copy {{ font-size: .75rem; margin-top: .5rem; }}

    @media (max-width: 640px) {{
      .article-wrapper {{ padding: 0 1rem 3rem; margin-top: 1.5rem; }}
      h1.article-title {{ font-size: 1.4rem; }}
    }}
  </style>
</head>
<body>

  <header class="site-header" role="banner">
    <div class="header-inner">
      <a href="https://www.non-exec.ai/" class="site-logo" aria-label="Non-Exec AI home">
        <div class="logo-mark" aria-hidden="true">NE</div>
        <div class="logo-text">
          <strong>Non-Exec AI</strong>
          <span>Board Intelligence Platform</span>
        </div>
      </a>
      <a href="{index_url}" class="back-link">← All Insights</a>
    </div>
  </header>

  <main role="main">
    <article class="article-wrapper" itemscope itemtype="https://schema.org/Article">

      <meta itemprop="datePublished" content="{iso_date}" />
      <meta itemprop="dateModified"  content="{iso_date}" />

      <div class="article-meta">
        <span class="article-category">{_escape(data.get("category", "Corporate Governance"))}</span>
        <span class="article-date">{display_date}</span>
        <span class="article-read-time">· 5 min read</span>
      </div>

      <h1 class="article-title" itemprop="headline">{title_safe}</h1>

      <p class="article-excerpt" itemprop="description">{_escape(data.get("excerpt", ""))}</p>

      <div class="article-body" itemprop="articleBody">
        {data.get("content_html", "")}
      </div>

      <aside class="article-cta" aria-label="Platform promotion">
        <h2>Transform Your Board's Decision-Making</h2>
        <p>Non-Exec AI gives your board real-time intelligence, unbiased analysis, and predictive foresight — precisely when decisions matter most.</p>
        <a href="https://www.non-exec.ai/" class="btn-cta">Explore Non-Exec AI</a>
      </aside>

      <nav class="back-nav" aria-label="Article navigation">
        <a href="{index_url}">Back to All Insights</a>
      </nav>

    </article>
  </main>

  <footer class="site-footer" role="contentinfo">
    <nav aria-label="Footer navigation">
      <a href="https://www.non-exec.ai/">Platform</a>
      <a href="{index_url}">Insights</a>
      <a href="https://www.non-exec.ai/privacy/">Privacy</a>
      <a href="https://www.non-exec.ai/terms/">Terms</a>
    </nav>
    <p class="footer-copy">&copy; {datetime.now().year} Non-Exec AI Ltd. All rights reserved.</p>
  </footer>

</body>
</html>"""


def _escape(text: str) -> str:
    """Minimal HTML attribute escaping."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Build a blog-card HTML snippet for index.html
# ─────────────────────────────────────────────────────────────────────────────

def build_card_html(data: dict, date_str: str, full_slug: str) -> str:
    """
    Return the <article class="blog-card"> HTML that goes into index.html.
    We build this as a plain string so it survives round-trip HTML parsing.
    """
    display_date = _format_display_date(date_str)
    article_href = f"articles/{full_slug}.html"
    title_esc    = _escape(data["title"])
    excerpt_esc  = _escape(data.get("excerpt", ""))
    cat_esc      = _escape(data.get("category", "Corporate Governance"))
    slug_esc     = _escape(full_slug)
    return f"""
          <article class="blog-card" data-slug="{slug_esc}" data-date="{date_str}">
            <div class="card-category">{cat_esc}</div>
            <h3 class="card-title"><a href="{article_href}">{title_esc}</a></h3>
            <p class="card-excerpt">{excerpt_esc}</p>
            <div class="card-meta">
              <span class="card-date">{display_date}</span>
              <a href="{article_href}" class="card-link" aria-label="Read full article: {title_esc}">Read More</a>
            </div>
          </article>"""


# ─────────────────────────────────────────────────────────────────────────────
# 4. Update index.html — move today → archive, inject new today
# ─────────────────────────────────────────────────────────────────────────────

def update_index(new_cards_html: list[str]) -> None:
    """
    Parse index.html and:
      a) Move existing #todays-blogs-grid articles to #archived-blogs-grid
      b) Replace #todays-blogs-grid content with new_cards_html
    """
    if not INDEX_FILE.exists():
        log.error("index.html not found at %s. Aborting.", INDEX_FILE.resolve())
        sys.exit(1)

    source = INDEX_FILE.read_text(encoding="utf-8")

    # We work on the raw source with comment anchors to stay deterministic
    # Pattern: content between <!-- TODAYS-BLOGS-START --> and <!-- TODAYS-BLOGS-END -->
    today_pattern   = re.compile(
        r'(<!-- TODAYS-BLOGS-START -->)(.*?)(<!-- TODAYS-BLOGS-END -->)',
        re.DOTALL,
    )
    archive_pattern = re.compile(
        r'(<!-- ARCHIVED-BLOGS-START -->)(.*?)(<!-- ARCHIVED-BLOGS-END -->)',
        re.DOTALL,
    )

    today_match   = today_pattern.search(source)
    archive_match = archive_pattern.search(source)

    if not today_match or not archive_match:
        log.error(
            "Could not locate comment anchors in index.html. "
            "Ensure <!-- TODAYS-BLOGS-START/END --> and <!-- ARCHIVED-BLOGS-START/END --> are present."
        )
        sys.exit(1)

    # Extract existing today block (the div + its article children)
    today_block_raw  = today_match.group(2)

    # Parse the today block to collect existing article cards
    soup_today = BeautifulSoup(today_block_raw, "html.parser")
    existing_cards = soup_today.find_all("article", class_="blog-card")

    # Build archived section: prepend existing today cards (newest-first), keep old archived
    old_archive_block = archive_match.group(2)

    # We insert existing today-cards at the top of the archive, retaining any
    # existing archive cards that are already there
    prepend_html = "".join(str(c) for c in existing_cards)
    new_archive_inner = prepend_html + old_archive_block

    # Build new today block
    today_grid_open  = '\n        <div class="blog-grid" id="todays-blogs-grid">\n'
    today_grid_close = '\n        </div>\n        '
    new_today_inner  = today_grid_open + "".join(new_cards_html) + today_grid_close

    # Use callable replacements to prevent re.sub from interpreting backslashes
    # or group references inside the replacement HTML strings.
    def replace_today(m: re.Match) -> str:
        return m.group(1) + new_today_inner + m.group(3)

    def replace_archive(m: re.Match) -> str:
        return m.group(1) + new_archive_inner + m.group(3)

    new_source = today_pattern.sub(replace_today, source)
    new_source = archive_pattern.sub(replace_archive, new_source)

    INDEX_FILE.write_text(new_source, encoding="utf-8")
    log.info("index.html updated successfully.")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    today         = datetime.now(timezone.utc)
    date_str      = today.strftime("%Y-%m-%d")        # e.g. 2026-04-20
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    # Pick 4 unique topics for today
    topics = random.sample(TOPICS, ARTICLES_PER_DAY)
    log.info("Today's topics: %s", topics)

    new_cards: list[str] = []

    for topic in topics:
        try:
            data      = generate_article_data(topic, date_str)
            base_slug = slugify(data.get("slug", data["title"]))
            full_slug = f"{base_slug}-{date_str}"

            # Write individual article file
            article_html = build_article_html(data, date_str, full_slug)
            article_path = ARTICLES_DIR / f"{full_slug}.html"
            article_path.write_text(article_html, encoding="utf-8")
            log.info("Written article: %s", article_path)

            # Build card snippet for index
            new_cards.append(build_card_html(data, date_str, full_slug))

        except Exception as exc:
            log.exception("Failed to generate article for topic '%s': %s", topic, exc)
            # Continue with remaining topics rather than aborting the whole run
            continue

    if not new_cards:
        log.error("No articles were successfully generated. index.html will not be modified.")
        sys.exit(1)

    update_index(new_cards)
    log.info("Daily generation complete. %d article(s) published.", len(new_cards))


if __name__ == "__main__":
    main()
