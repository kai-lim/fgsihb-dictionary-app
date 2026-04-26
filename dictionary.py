import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.fgsihb.org/dictionary/"
DETAIL_BASE = "https://www.fgsihb.org"
PARAMS_BASE = {"__locale": "zh_TW", "callback": "Y"}

_session = requests.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; FGS-Translator-Agent/1.0)"
})


def _fetch_detail(path: str) -> dict:
    """Fetch a detail page and extract the full entry content.

    Args:
        path: The relative URL path, e.g. /dictionary/search-result/00931/?__locale=zh_TW

    Returns:
        Dict with keys: chinese_title, english_title, category,
        chinese_body, english_body, reference.
    """
    url = f"{DETAIL_BASE}{path}"
    print(f"    --> Fetching detail page: {url}")
    resp = _session.get(url, timeout=10)
    resp.raise_for_status()
    print(f"        Response status: {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    content = soup.select_one("div.dictionary_detail-content")
    if not content:
        print("        WARNING: Could not find div.dictionary_detail-content on page")
        return {}

    # Title: Chinese heading (strip the romanization in <em>)
    chinese_title_tag = content.select_one("div.info div.heading")
    if chinese_title_tag:
        for tag in chinese_title_tag.select("span"):
            tag.decompose()
        chinese_title = chinese_title_tag.get_text(strip=True)
    else:
        chinese_title = ""
    print(f"        Chinese title: {chinese_title!r}")

    # English heading sits in <div class="heading mb-4">
    english_title_tag = content.select_one("div.heading.mb-4")
    english_title = english_title_tag.get_text(strip=True) if english_title_tag else ""
    print(f"        English title: {english_title!r}")

    # Extract all title/text section pairs (Category, Description, References, etc.)
    category = ""
    chinese_body = ""
    english_body = ""
    reference = ""

    title_tags = content.select("div.title")
    print(f"        Found {len(title_tags)} section(s): {[t.get_text(strip=True) for t in title_tags]}")

    for title_tag in title_tags:
        label = title_tag.get_text(strip=True).rstrip(":")
        text_tag = title_tag.find_next_sibling("div", class_="text")
        if not text_tag:
            print(f"        WARNING: No <div class='text'> found after section '{label}'")
            continue

        if label == "Category":
            category = text_tag.get_text(strip=True)
            print(f"        Category: {category!r}")

        elif label == "Description":
            columns = text_tag.select("div.col-md-6")
            print(f"        Description columns found: {len(columns)}")
            if len(columns) >= 2:
                chinese_body = columns[0].get_text(strip=True)
                english_body = columns[1].get_text(" ", strip=True)
                print(f"        Chinese body: {chinese_body!r}")
                print(f"        English body: {english_body!r}")
            else:
                english_body = text_tag.get_text(strip=True)
                print(f"        Single-column body: {english_body!r}")

        elif label == "References":
            reference = text_tag.get_text(strip=True)
            print(f"        Reference: {reference!r}")

    return {
        "chinese_title": chinese_title,
        "english_title": english_title,
        "category": category,
        "chinese_body": chinese_body,
        "english_body": english_body,
        "reference": reference,
    }


def _rank_title(title: str, keyword: str) -> int:
    """Score a title by how prominently the keyword appears.

    3 = exact match, 2 = keyword in title, 1 = no title match.
    """
    if title == keyword:
        return 3
    if keyword in title:
        return 2
    return 1


def lookup(keyword: str, max_results: int = 5, max_pages: int = 3) -> list[dict]:
    """Search the FGS Buddhist dictionary and return full entry details.

    Fetches up to max_pages of search results (10 per page), ranks all
    candidates by title match, then fetches full details only for the
    top max_results entries.

    Args:
        keyword: Chinese term to search for.
        max_results: Number of top-ranked entries to return with full details.
        max_pages: Number of search result pages to scan before ranking.

    Returns:
        List of dicts with keys: chinese_title, english_title, category,
        chinese_body, english_body, reference. Ordered by title relevance.
    """
    print(f"\n{'='*60}")
    print(f"LOOKUP: {keyword!r}  (top {max_results} results, scanning {max_pages} page(s))")
    print(f"{'='*60}")

    # Step 1: collect candidates across multiple pages
    candidates = []
    for page_num in range(1, max_pages + 1):
        params = {**PARAMS_BASE, "keyword": keyword, "page": page_num}
        print(f"\nStep 1 — Page {page_num}/{max_pages}: fetching {BASE_URL}")
        print(f"  Parameters: {params}")

        resp = _session.get(BASE_URL, params=params, timeout=10)
        resp.raise_for_status()
        print(f"  Response status: {resp.status_code}")

        soup = BeautifulSoup(resp.text, "html.parser")

        # Extract total result count from the first page
        if page_num == 1:
            count_tag = soup.select_one("div.result-search div.title")
            if count_tag:
                print(f"  {count_tag.get_text(strip=True)}")

        page_items = soup.select("div.result-item")
        print(f"  Found {len(page_items)} result(s) on this page:")

        if not page_items:
            print("  No results on this page — stopping pagination early")
            break

        for item in page_items:
            link_tag = item.select_one("h4 a.vocabularyWord")
            if not link_tag or not link_tag.get("href"):
                print("  WARNING: result-item has no link, skipping")
                continue
            title = link_tag.get_text(strip=True)
            href = link_tag["href"]
            candidates.append((title, href))
            print(f"    - {title!r}  →  {href}")

    print(f"\n  Total candidates collected: {len(candidates)}")

    # Step 2: rank all candidates by title match, take top max_results
    print(f"\nStep 2 — Ranking all {len(candidates)} candidate(s) by title match:")
    candidates.sort(key=lambda c: _rank_title(c[0], keyword), reverse=True)
    for i, (title, _) in enumerate(candidates):
        score = _rank_title(title, keyword)
        label = {3: "EXACT", 2: "PARTIAL", 1: "body-only"}.get(score, "?")
        print(f"  #{i+1} [{label}] {title!r}")

    top_candidates = candidates[:max_results]
    print(f"\n  → Keeping top {len(top_candidates)} candidate(s) for detail fetch")

    # Step 3: fetch full details only for the top candidates
    print(f"\nStep 3 — Fetching full details for top {len(top_candidates)} entry/entries:")
    results = []
    for i, (title, href) in enumerate(top_candidates):
        print(f"\n  [{i+1}/{len(top_candidates)}] {title!r}")
        detail = _fetch_detail(href)
        if detail:
            results.append(detail)
        else:
            print(f"  WARNING: No detail returned for {href!r}")

    print(f"\n{'='*60}")
    print(f"LOOKUP COMPLETE — returning {len(results)} result(s)")
    print(f"{'='*60}\n")
    return results


def format_for_prompt(lookups: dict[str, list[dict]]) -> str:
    """Format dictionary lookup results as a reference block for a prompt.

    Args:
        lookups: Dict mapping searched keyword to its list of results.

    Returns:
        A formatted string to include in a translation prompt.
    """
    lines = ["FGS DICTIONARY REFERENCE (use these approved translations):"]
    for keyword, results in lookups.items():
        if not results:
            lines.append(f"  {keyword}: (no results found)")
            continue
        for r in results:
            lines.append(f"  {r['chinese_title']} = {r['english_title']}")
            if r["chinese_body"] and r["english_body"]:
                lines.append(f"    Context: {r['chinese_body']}")
                lines.append(f"    Translation: {r['english_body']}")
    return "\n".join(lines)


if __name__ == "__main__":
    test_terms = ["淨土", "人間佛教", "菩薩"]
    for term in test_terms:
        results = lookup(term, max_results=2)
        print(f"Final results for {term!r}:")
        for r in results:
            print(f"  {r['chinese_title']} = {r['english_title']}")
            if r["chinese_body"]:
                print(f"  Chinese body: {r['chinese_body'][:80]}...")
            if r["english_body"]:
                print(f"  English body: {r['english_body'][:80]}...")
            if r["reference"]:
                print(f"  Source: {r['reference']}")
        print()
