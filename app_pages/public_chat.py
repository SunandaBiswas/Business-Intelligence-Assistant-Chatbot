import os
import re
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from dotenv import load_dotenv

import streamlit as st


SITE_ROOT = "https://green-delta.com"
ANNUAL_REPORT_URL = f"{SITE_ROOT}/financial_indicator/annual-reports/"
LLMS_URL = f"{SITE_ROOT}/llms.txt"
ANNUAL_REPORT_DIR = Path(__file__).resolve().parents[1] / "public_data" / "annual_reports"
ANNUAL_REPORT_TEXT_DIR = ANNUAL_REPORT_DIR.parent / "annual_report_text"
load_dotenv()

FAQS = [
    "Which annual reports are available?",
    "Where can I find GDIC financial highlights?",
    "What insurance products does Green Delta offer?",
    "How can I contact Green Delta Insurance?",
]


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = re.sub(r"\s+", " ", data).strip()
        if text:
            self.parts.append(text)

    def text(self):
        return "\n".join(dict.fromkeys(self.parts))


def _fetch_text(url, timeout=20):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GreenDeltaPublicAssistant/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type()
        if content_type == "application/pdf":
            return None
        return response.read().decode("utf-8", errors="replace")


def _fetch_pdf(url, timeout=30):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "GreenDeltaPublicAssistant/1.0"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def _local_annual_report_context(question):
    """Extract relevant pages from locally downloaded annual reports."""
    from pypdf import PdfReader

    if not ANNUAL_REPORT_DIR.exists():
        return "", []

    question_lower = question.lower()
    year_match = re.search(r"\b(19[789]\d|20\d{2})\b", question)
    requested_year = year_match.group(1) if year_match else None

    stop_words = {
        "the", "a", "an", "and", "or", "of", "to", "for", "from", "what", "which",
        "where", "when", "how", "does", "did", "is", "are", "can", "in", "on",
    }
    keywords = {
        word for word in re.findall(r"[a-z0-9]+", question_lower)
        if len(word) >= 3 and word not in stop_words
    }

    selected = []
    sources = []
    for pdf_path in sorted(ANNUAL_REPORT_DIR.glob("*.pdf")):
        report_year_match = re.search(r"20\d{2}|19\d{2}", pdf_path.name)
        report_year = report_year_match.group(0) if report_year_match else None
        if requested_year and report_year and report_year != requested_year:
            continue

        text_path = ANNUAL_REPORT_TEXT_DIR / f"{pdf_path.stem}.txt"
        if text_path.exists() and text_path.stat().st_size > 0:
            text = text_path.read_text(encoding="utf-8", errors="replace")
            matches = []
            for chunk_number, offset in enumerate(range(0, len(text), 7000), start=1):
                chunk = re.sub(r"\s+", " ", text[offset:offset + 7000])
                normalized = chunk.lower()
                score = sum(normalized.count(word) for word in keywords)
                if report_year and report_year in question_lower:
                    score += 25
                if score:
                    matches.append((score, chunk_number, chunk))
            if matches:
                top_pages = sorted(matches, reverse=True)[:8]
                page_text = "\n".join(
                    f"[Section {section}] {chunk}"
                    for _, section, chunk in top_pages
                )
                selected.append(
                    f"Source: {ANNUAL_REPORT_URL} - Local report: {pdf_path.name}\n{page_text}"
                )
                sources.append(f"{ANNUAL_REPORT_URL}#{pdf_path.name}")
            continue

        try:
            reader = PdfReader(str(pdf_path))
            if len(reader.pages) == 0:
                continue

            pdf_matches = []
            for page_number, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                if not text:
                    continue
                normalized = text.lower()
                score = sum(normalized.count(word) for word in keywords)
                if report_year and report_year in question_lower:
                    score += 25
                if score:
                    pdf_matches.append((score, page_number, re.sub(r"\s+", " ", text)[:7000]))

            if pdf_matches:
                top_pages = sorted(pdf_matches, reverse=True)[:8]
                page_text = "\n".join(
                    f"[Page {page_number}] {text}"
                    for _, page_number, text in top_pages
                )
                selected.append(
                    f"Source: {ANNUAL_REPORT_URL} - Local report: {pdf_path.name}\n{page_text}"
                )
                sources.append(f"{ANNUAL_REPORT_URL}#{pdf_path.name}")
        except Exception:
            continue

    if not selected:
        available = [
            path.name for path in sorted(ANNUAL_REPORT_DIR.glob("*.pdf"))
        ]
        return (
            "Available local annual reports:\n" + "\n".join(available),
            [ANNUAL_REPORT_URL],
        )
    return "\n\n".join(selected[:12]), sources[:12]


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _public_context(question):
    sources = [ANNUAL_REPORT_URL]
    extracted = []

    local_context, local_sources = _local_annual_report_context(question)
    if local_context:
        extracted.append(local_context)
        sources = local_sources + sources

    try:
        llms_text = _fetch_text(LLMS_URL)
    except Exception:
        llms_text = None
    if llms_text:
        extracted.append(f"Source: {LLMS_URL}\n{llms_text[:30000]}")

        links = re.findall(r"\[([^\]]+)\]\((https://green-delta\.com[^)]+)\)", llms_text)
        lower_question = question.lower()
        keywords = set(re.findall(r"[a-z0-9]+", lower_question))
        scored = []
        for title, url in links:
            title_words = set(re.findall(r"[a-z0-9]+", title.lower()))
            score = len(keywords & title_words)
            if any(word in title.lower() for word in ("annual", "financial", "report", "highlight")
                   if word in lower_question):
                score += 3
            if score:
                scored.append((score, title, url))

        for _, title, url in sorted(scored, reverse=True)[:3]:
            try:
                page = _fetch_text(url)
                if not page:
                    continue
                parser = _TextExtractor()
                parser.feed(page)
                text = parser.text()[:12000]
                if text:
                    extracted.append(f"Source: {url}\n{text}")
                    sources.append(url)
            except Exception:
                continue

    return "\n\n".join(extracted), sources


def _groq_answer(question, history, context, sources):
    from groq import Groq

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        try:
            api_key = st.secrets["GROQ_API_KEY"]
        except Exception:
            api_key = None
    if not api_key:
        return "The public chat is temporarily unavailable because the chat service is not configured."

    history_text = "\n".join(
        f"{message['role'].capitalize()}: {message['content']}"
        for message in history[-8:]
    )
    source_list = "\n".join(f"- {url}" for url in dict.fromkeys(sources))
    system = (
        "You are the public information assistant for Green Delta Insurance. "
        "Answer only from the supplied public website context. "
        "Do not use or reveal private MIS, database, account, internal, or confidential information. "
        "If the context does not contain the answer, say that it is not available on the provided public pages "
        "and suggest the Annual Report_GDIC page or another official public page. "
        "Be concise, factual, and distinguish a report year clearly. "
        "End with a short 'Public sources:' section listing only the supplied source URLs."
    )
    user = (
        f"Question: {question}\n\n"
        f"Conversation:\n{history_text or '(none)'}\n\n"
        f"Public context:\n{context[:60000]}\n\n"
        f"Available source URLs:\n{source_list}"
    )
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=0,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (response.choices[0].message.content or "").strip()


st.html("""
<style>
  .ask-here-heading {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.55rem;
    margin: 0.55rem 0 0.15rem;
  }
  .ask-here-heading .globe {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2.5rem;
    height: 2.5rem;
    border-radius: 50%;
    background: #eef7ff;
    font-size: 1.65rem;
    line-height: 1;
  }
  .ask-here-heading h1 {
    margin: 0;
    color: #102a43;
    font-size: 2rem;
    line-height: 1.2;
  }
</style>
<div class="ask-here-heading">
  <span class="globe" aria-hidden="true">🌐</span>
  <h1>Ask Here</h1>
</div>
""")

st.caption(
    "Ask about public annual reports, financial disclosures, insurance products, "
    "company information, and other information published on the Green Delta website."
)

st.session_state.setdefault("public_messages", [])

if not st.session_state.public_messages:
    st.markdown("**Suggested questions**")
    for faq in FAQS:
        st.button(faq, key=f"public_faq_{faq}", width="stretch",
                  on_click=lambda question=faq: st.session_state.update(pending_public=question))

for message in st.session_state.public_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

with st.bottom:
    chat_col, clear_col = st.columns([8, 1.5], vertical_alignment="center")
    with chat_col:
        question = st.chat_input("Ask about public Green Delta information...")
    with clear_col:
        clear_clicked = st.button(
            "Clear chat",
            icon=":material/delete:",
            width="stretch",
            key="public_chat_clear",
        )
    st.html("""
    <style>
      [data-testid="stChatInput"] { min-height: 3rem; }
      .st-key-public_chat_clear button {
        height: 3rem;
        min-height: 3rem;
        color: #B3261E;
        border-color: #E4A8A4;
        background: #FDF1F0;
      }
      .st-key-public_chat_clear button:hover {
        color: #FFFFFF;
        background: #C62828;
        border-color: #C62828;
      }
    </style>
    """)

if clear_clicked:
    st.session_state.public_messages = []
    st.rerun()

question = question or st.session_state.pop("pending_public", None)

if question:
    history = list(st.session_state.public_messages)
    st.session_state.public_messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    try:
        with st.spinner("Checking official public pages..."):
            context, sources = _public_context(question)
            answer = _groq_answer(question, history, context, sources)
    except Exception as exc:
        del exc
        answer = (
            "I could not retrieve the official public pages right now. "
            f"You can open the [Annual Report_GDIC page]({ANNUAL_REPORT_URL})."
        )
        # Do not expose implementation or network errors to public users.

    reply = {"role": "assistant", "content": answer}
    st.session_state.public_messages.append(reply)
    st.rerun()
