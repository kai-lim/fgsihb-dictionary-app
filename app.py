import json
import os

from google import genai
import streamlit as st
from dotenv import load_dotenv

from dictionary import lookup, _rank_title

load_dotenv()

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FGS Buddhist Dictionary",
    page_icon="☸️",
    layout="wide",
)

st.title("☸️ FGS Buddhist Dictionary")
st.caption("Search the Fo Guang Shan dictionary with keyword matching and optional AI relevance scoring")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Search settings")

    max_pages = st.slider(
        "Pages to scan",
        min_value=1, max_value=15, value=3,
        help="The site shows 10 results per page. More pages = wider coverage but slower.",
    )
    max_results = st.slider(
        "Results to return",
        min_value=1, max_value=20, value=5,
        help="After scanning and ranking all candidates, show this many entries.",
    )

    st.divider()
    st.header("AI relevance scoring")
    enable_scoring = st.toggle("Score results with Gemini", value=True)

    gemini_key = os.getenv("GEMINI_API_KEY", "")

    st.divider()
    st.caption("Built for Fo Guang Shan London Translation Team")


# ── Gemini scoring ────────────────────────────────────────────────────────────
def score_with_gemini(keyword: str, results: list[dict], api_key: str, on_progress=None) -> list[dict]:
    """Ask Gemini to score how relevant each result is to the search keyword.

    Returns a list of dicts with keys: score (1-10), reason (str).
    """
    client = genai.Client(api_key=api_key)
    scores = []

    for i, r in enumerate(results):
        entry = f"Title: {r['chinese_title']} / {r['english_title']}"
        if r["chinese_body"]:
            entry += f"\nBody: {r['chinese_body']} / {r['english_body']}"

        prompt = f"""You are a Buddhist scholar. A user searched for the Chinese term: "{keyword}"

Score the relevance of the following dictionary entry to the search term on a scale of 1 to 10, where:
- 10 = the entry is directly about this term
- 5  = the entry is related but not a direct match
- 1  = the entry is barely relevant

Return ONLY a valid JSON object with:
- "score": integer 1-10
- "reason": one short English sentence explaining the score

Entry:
{entry}

JSON:"""

        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        scores.append(json.loads(raw.strip()))

        if on_progress:
            on_progress(i + 1, len(results))

    return scores


# ── Helpers ───────────────────────────────────────────────────────────────────
RANK_LABELS = {3: ("EXACT", "🟢"), 2: ("PARTIAL", "🟡"), 1: ("body only", "🔵")}

def rank_badge(title: str, keyword: str) -> str:
    score = _rank_title(title, keyword)
    label, dot = RANK_LABELS[score]
    return f"{dot} {label}"


# ── Main UI ───────────────────────────────────────────────────────────────────
keyword = st.text_input(
    "Search term (Chinese)",
    placeholder="e.g. 淨土, 人間佛教, 菩薩",
)
search_btn = st.button("Search", type="primary", use_container_width=False)

if search_btn:
    if not keyword.strip():
        st.warning("Please enter a search term.")
        st.stop()

    # ── Search ────────────────────────────────────────────────────────────────
    status = st.empty()
    progress = st.progress(0.0)

    def on_progress(stage, current, total):
        if stage == "page":
            status.text(f"Scanning page {current} of {total}…")
            progress.progress(current / total * 0.5)
        elif stage == "detail":
            status.text(f"Fetching entry {current} of {total}…")
            progress.progress(0.5 + current / total * 0.5)

    results = lookup(keyword, max_results=max_results, max_pages=max_pages, on_progress=on_progress)
    progress.empty()
    status.empty()

    if not results:
        st.error("No results found. Try a different term or increase the number of pages.")
        st.stop()

    st.success(f"Found {len(results)} result(s) — ranked by title relevance")

    # ── AI scoring ────────────────────────────────────────────────────────────
    if enable_scoring:
        if not gemini_key:
            st.warning("AI scoring is unavailable: GEMINI_API_KEY is not configured.")
        else:
            ai_status = st.empty()
            ai_progress = st.progress(0.0)

            def on_ai_progress(current, total):
                ai_status.text(f"Scoring entry {current} of {total} with Gemini…")
                ai_progress.progress(current / total)

            try:
                scores = score_with_gemini(keyword, results, gemini_key, on_progress=on_ai_progress)
                for i, r in enumerate(results):
                    r["ai_score"] = scores[i].get("score")
                    r["ai_reason"] = scores[i].get("reason", "")
            except Exception as e:
                st.warning(f"AI scoring failed: {e}")
            finally:
                ai_progress.empty()
                ai_status.empty()

    # ── Sort: keyword match first, then AI score ──────────────────────────────
    results.sort(
        key=lambda r: (_rank_title(r["chinese_title"], keyword), r.get("ai_score") or 0),
        reverse=True,
    )

    # ── Summary table ─────────────────────────────────────────────────────────
    table_rows = []
    for r in results:
        row = {
            "Chinese": r["chinese_title"],
            "English": r["english_title"],
            "Keyword Match": RANK_LABELS[_rank_title(r["chinese_title"], keyword)][0],
        }
        if enable_scoring:
            row["AI Score"] = r["ai_score"] if r.get("ai_score") is not None else "—"
            row["AI Reason"] = r.get("ai_reason", "")
        table_rows.append(row)

    st.table(table_rows)

    st.divider()

    # ── Detailed entries ──────────────────────────────────────────────────────
    for i, r in enumerate(results):
        badge = rank_badge(r["chinese_title"], keyword)
        header = f"**{i+1}. {r['chinese_title']}** — {r['english_title']}   {badge}"
        if r.get("ai_score") is not None:
            score_colour = "🟢" if r["ai_score"] >= 8 else "🟡" if r["ai_score"] >= 5 else "🔴"
            header += f"   |   {score_colour} AI score: **{r['ai_score']}/10**"

        with st.expander(header, expanded=(i == 0)):
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**Chinese**")
                st.write(r["chinese_title"])
                if r["chinese_body"]:
                    st.write(r["chinese_body"])

            with col2:
                st.markdown("**English**")
                st.write(r["english_title"])
                if r["english_body"]:
                    st.write(r["english_body"])

            if r["category"]:
                st.caption(f"Category: {r['category']}")
            if r["reference"]:
                st.caption(f"Source: {r['reference']}")
            if r.get("ai_reason"):
                st.info(f"💬 Gemini: {r['ai_reason']}")
