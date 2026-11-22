import html
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
    "Which annual report PDFs are available?",
    "Summarize the key financial highlights for 2024.",
    "What was the gross premium in 2024?",
    "What was the profit after tax in 2024?",
    "What were the total assets in 2024?",
    "Compare gross premiums in 2023 and 2024.",
]


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = _plain_text(data)
        if text:
            self.parts.append(text)

    def text(self):
        return "\n".join(dict.fromkeys(self.parts))


def _plain_text(value):
    """Decode HTML entities and remove markup before text reaches the UI or model."""
    text = html.unescape(html.unescape(value))
    text = re.sub(r"<\s*br\b[^>]*>", " ", text, flags=re.I)
    text = re.sub(r"</?(?:td|th)\b[^>]*>", " | ", text, flags=re.I)
    text = re.sub(r"</?(?:p|div|li|tr|h[1-6]|ul|ol)\b[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]*>", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return text.strip()


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
    """Retrieve relevant chunks from the locally downloaded annual reports."""
    if not ANNUAL_REPORT_DIR.exists():
        return "", []

    available_reports = sorted(path.name for path in ANNUAL_REPORT_DIR.glob("*.pdf"))
    if re.search(r"\b(which|what|list|available|availability)\b", question.lower()) and re.search(
        r"\b(annual|reports?)\b", question.lower()
    ):
        return (
            "Available annual report PDFs:\n" + "\n".join(available_reports),
            [ANNUAL_REPORT_URL],
        )

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
    except ImportError as exc:
        raise RuntimeError(
            "RAG dependency missing. Install project requirements in the active app environment."
        ) from exc

    question_lower = question.lower()
    year_match = re.search(r"\b(19[789]\d|20\d{2})\b", question)
    requested_year = year_match.group(1) if year_match else None

    chunks = []
    for pdf_path in sorted(ANNUAL_REPORT_DIR.glob("*.pdf")):
        report_year_match = re.search(r"20\d{2}|19\d{2}", pdf_path.name)
        report_year = report_year_match.group(0) if report_year_match else None
        if requested_year and report_year and report_year != requested_year:
            continue

        text_path = ANNUAL_REPORT_TEXT_DIR / f"{pdf_path.stem}.txt"
        if text_path.exists() and text_path.stat().st_size > 0:
            text = text_path.read_text(encoding="utf-8", errors="replace")
            text = re.sub(r"\s+", " ", text).strip()
            for chunk_number, offset in enumerate(range(0, len(text), 1400), start=1):
                chunk = text[offset:offset + 1600]
                if len(chunk) < 250:
                    continue
                chunks.append({
                    "report": pdf_path.name,
                    "year": report_year,
                    "chunk": chunk_number,
                    "text": chunk,
                })

    if not chunks:
        available = [path.name for path in sorted(ANNUAL_REPORT_DIR.glob("*.pdf"))]
        return "Available local annual reports:\n" + "\n".join(available), [ANNUAL_REPORT_URL]

    documents = [item["text"] for item in chunks]
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2),
        sublinear_tf=True,
        max_features=100000,
    )
    matrix = vectorizer.fit_transform(documents)
    query_vector = vectorizer.transform([question])
    scores = cosine_similarity(query_vector, matrix).ravel()

    ranked = sorted(
        range(len(chunks)),
        key=lambda index: scores[index],
        reverse=True,
    )
    selected = []
    sources = []
    seen_reports = set()
    for index in ranked:
        item = chunks[index]
        if scores[index] <= 0:
            continue
        report_key = (item["report"], item["chunk"])
        if report_key in seen_reports:
            continue
        seen_reports.add(report_key)
        selected.append(
            f"Source: {ANNUAL_REPORT_URL} - Local report: {item['report']} "
            f"- Section {item['chunk']}\n{item['text']}"
        )
        sources.append(f"{ANNUAL_REPORT_URL}#{item['report']}")
        if len(selected) >= 5:
            break

    if not selected:
        available = [path.name for path in sorted(ANNUAL_REPORT_DIR.glob("*.pdf"))]
        return "Available local annual reports:\n" + "\n".join(available), [ANNUAL_REPORT_URL]
    return "\n\n".join(selected), list(dict.fromkeys(sources))


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _public_context(question):
    sources = [ANNUAL_REPORT_URL]
    extracted = []
    available_reports = sorted(path.name for path in ANNUAL_REPORT_DIR.glob("*.pdf"))
    if available_reports:
        extracted.append(
            "Available annual reports in the local public collection:\n"
            + "\n".join(available_reports)
        )

    local_context, local_sources = _local_annual_report_context(question)
    if local_context:
        extracted.append(local_context)
        sources = local_sources + sources

    lower_question = question.lower()
    if re.search(r"\b(annual|report|financial statement|financial highlight)\b", lower_question):
        return "\n\n".join(extracted)[:12000], list(dict.fromkeys(sources))

    try:
        llms_text = _fetch_text(LLMS_URL)
    except Exception:
        llms_text = None
    if llms_text:
        links = re.findall(r"\[([^\]]+)\]\((https://green-delta\.com[^)]+)\)", llms_text)
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

        for _, title, url in sorted(scored, reverse=True)[:2]:
            try:
                page = _fetch_text(url)
                if not page:
                    continue
                parser = _TextExtractor()
                parser.feed(page)
                text = parser.text()[:3500]
                if text:
                    extracted.append(f"Source: {url}\n{text}")
                    sources.append(url)
            except Exception:
                continue

    return "\n\n".join(extracted)[:12000], list(dict.fromkeys(sources))


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
        f"{message['role'].capitalize()}: {_plain_text(message['content'])}"
        for message in history[-4:]
    )
    source_list = "\n".join(f"- {url}" for url in dict.fromkeys(sources))
    system = (
        "You are the public information assistant for Green Delta Insurance. "
        "Answer only from the supplied public website context. "
        "Do not use or reveal private MIS, database, account, internal, or confidential information. "
        "If the context does not contain the answer, say that it is not available on the provided public pages "
        "and suggest the Annual Report_GDIC page or another official public page. "
        "Write readable plain text with simple bullets when useful. Never output HTML tags or HTML entities. "
        "Be concise, factual, and distinguish a report year clearly. "
        "End with a short 'Public sources:' section listing only the supplied source URLs."
    )
    user = (
        f"Question: {question}\n\n"
        f"Conversation:\n{history_text[:2000] or '(none)'}\n\n"
        f"Public context:\n{context[:12000]}\n\n"
        f"Available source URLs:\n{source_list}"
    )
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        temperature=0,
        max_tokens=1200,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return _plain_text(response.choices[0].message.content or "")


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
stale_fallback = "I could not retrieve the official public pages right now."
for message_index, message in enumerate(st.session_state.public_messages):
    if message["role"] == "assistant" and message["content"].startswith(stale_fallback):
        if message_index > 0 and st.session_state.public_messages[message_index - 1]["role"] == "user":
            stale_question = st.session_state.public_messages[message_index - 1]["content"]
            st.session_state.pending_public = stale_question
            del st.session_state.public_messages[message_index - 1:message_index + 1]
        else:
            del st.session_state.public_messages[message_index]
        break

for message in st.session_state.public_messages:
    if message["role"] == "assistant":
        message["content"] = _plain_text(message["content"])
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

with st.bottom:
    faq_col, chat_col, clear_col = st.columns([1.25, 7.5, 1.5], vertical_alignment="center")
    with faq_col:
        with st.popover(
            "FAQs",
            icon=":material/lightbulb:",
            help="Choose a suggested question based on the public annual reports.",
            width="stretch",
        ):
            st.caption("Questions from the public annual reports")
            for faq_index, faq in enumerate(FAQS):
                st.button(
                    faq,
                    key=f"public_faq_{faq_index}",
                    width="stretch",
                    on_click=lambda question=faq: st.session_state.update(pending_public=question),
                )
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
        answer = (
            f"Public Chat could not complete this request ({type(exc).__name__}). "
            f"Please try again, or open the [Annual Report_GDIC page]({ANNUAL_REPORT_URL})."
        )

    reply = {"role": "assistant", "content": answer}
    st.session_state.public_messages.append(reply)
    st.rerun()
