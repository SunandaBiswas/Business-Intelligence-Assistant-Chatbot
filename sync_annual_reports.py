import re
import urllib.request
from pathlib import Path


SITE_URL = "https://green-delta.com/financial_indicator/annual-reports/"
OUTPUT_DIR = Path(__file__).resolve().parent / "public_data" / "annual_reports"


def download_all():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        SITE_URL,
        headers={"User-Agent": "GreenDeltaAnnualReportSync/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")

    pdf_urls = sorted(
        set(re.findall(r"https://green-delta\.com[^\"'<>\s]+\.pdf", html, flags=re.I)),
        key=str.lower,
    )
    downloaded = 0
    for url in pdf_urls:
        filename = url.rstrip("/").rsplit("/", 1)[-1]
        destination = OUTPUT_DIR / filename
        if destination.exists() and destination.stat().st_size > 100:
            continue
        pdf_request = urllib.request.Request(
            url,
            headers={"User-Agent": "GreenDeltaAnnualReportSync/1.0"},
        )
        with urllib.request.urlopen(pdf_request, timeout=120) as response:
            destination.write_bytes(response.read())
        downloaded += 1

    files = sorted(OUTPUT_DIR.glob("*.pdf"))
    print(f"Annual report folder contains {len(files)} PDFs.")
    print(f"Downloaded {downloaded} new or repaired PDFs.")


if __name__ == "__main__":
    download_all()
