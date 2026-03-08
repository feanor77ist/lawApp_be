"""
Anayasa Mahkemesi Yüce Divan karar toplayıcı.

Kaynak:
- Liste sayfası: https://anayasa.gov.tr/tr/kararlar/yuce-divan/
- Tek sayfa, tablo: Sıra No, Dava Tarihi, Esas ve Karar No, Sanık(lar), Kararın Sonucu.
- Her satırda "Karar metninin tamamına ulaşmak için tıklayınız" linki ile PDF adresi verilir.

Özellikler:
- Liste sayfasını çeker, tabloyu ayrıştırır.
- Her karar için: sira_no, dava_tarihi, esas_karar_no, saniklar, karar_sonucu, pdf_url.
- Tüm kayıtları tek bir index JSON dosyasına yazar; isteğe bağlı olarak her karar için ayrı JSON.
- --download-pdf ile PDF dosyalarını indirir (sira_no ile adlandırma: 1.pdf, 2.pdf, ...).

Örnek kullanım:

  python scripts/yuce_divan_scraper.py --out-dir data/yuce_divan

  python scripts/yuce_divan_scraper.py --out-dir data/yuce_divan --download-pdf --per-json
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://anayasa.gov.tr"
LIST_URL = "https://anayasa.gov.tr/tr/kararlar/yuce-divan/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _clean(s: str) -> str:
    """Metindeki fazla boşluk ve satır sonlarını tek boşluğa indirir."""
    if not s or not isinstance(s, str):
        return ""
    return re.sub(r"\s+", " ", s).strip()


def fetch_list_page(session: requests.Session) -> str:
    """Yüce Divan liste sayfasının HTML'ini döndürür."""
    r = session.get(LIST_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def parse_table(html: str) -> list[dict]:
    """
    Tablodan karar satırlarını çıkarır.
    Her öğe: sira_no, dava_tarihi, esas_karar_no, saniklar, karar_sonucu, pdf_url (mutlak URL).
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="table-bordered")
    if not table:
        return []

    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) < 5:
            continue
        # Başlık satırı: "Sıra No" vb. geçiyorsa atla
        first_text = _clean(cells[0].get_text())
        if first_text in ("Sıra No", "") or not first_text.isdigit():
            if "Sıra" in first_text or "Dava" in first_text:
                continue
            if not first_text.isdigit():
                continue

        sira_no = _clean(cells[0].get_text())
        dava_tarihi = _clean(cells[1].get_text())
        esas_karar_no = _clean(cells[2].get_text())
        saniklar = _clean(cells[3].get_text())
        karar_sonucu = _clean(cells[4].get_text())
        # Link metnini karar sonucundan çıkar
        karar_sonucu = re.sub(
            r"\s*Karar metninin tamamına ulaşmak için tıklayınız\.?\s*$",
            "",
            karar_sonucu,
            flags=re.IGNORECASE,
        ).strip()

        pdf_url = None
        last_cell = cells[4]
        a = last_cell.find("a", href=True)
        if a and a.get("href"):
            pdf_url = urljoin(BASE_URL, a["href"])

        rows.append({
            "sira_no": sira_no,
            "dava_tarihi": dava_tarihi,
            "esas_karar_no": esas_karar_no,
            "saniklar": saniklar,
            "karar_sonucu": karar_sonucu,
            "pdf_url": pdf_url,
        })
    return rows


def download_pdf(session: requests.Session, url: str, path: Path, retries: int = 3) -> bool:
    """PDF indirir; başarılı ise True."""
    for attempt in range(retries):
        try:
            r = session.get(url, headers=HEADERS, timeout=30, stream=True)
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.0 * (attempt + 1))
            else:
                return False
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AYM Yüce Divan karar listesi ve PDF indirici")
    parser.add_argument(
        "--out-dir",
        default="data/yuce_divan",
        help="Çıktı klasörü (index JSON ve isteğe bağlı PDF / per-json)",
    )
    parser.add_argument(
        "--download-pdf",
        action="store_true",
        help="Her kararın PDF dosyasını indir (1.pdf, 2.pdf, ...)",
    )
    parser.add_argument(
        "--per-json",
        action="store_true",
        help="Her karar için ayrı JSON dosyası yaz (1.json, 2.json, ...)",
    )
    parser.add_argument(
        "--sleep-pdf",
        type=float,
        default=0.5,
        help="Her PDF indirmesi arasında bekleme (saniye)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_dir = Path(args.out_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.get(BASE_URL, headers=HEADERS, timeout=10)

    print("Yüce Divan liste sayfası alınıyor...")
    html = fetch_list_page(session)
    rows = parse_table(html)
    print(f"{len(rows)} karar bulundu.")

    index_path = base_dir / "index.json"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f"Index yazıldı: {index_path}")

    if args.per_json:
        for row in rows:
            sn = row["sira_no"]
            p = base_dir / f"{sn}.json"
            with open(p, "w", encoding="utf-8") as f:
                json.dump(row, f, ensure_ascii=False, indent=2)
        print(f"Per-karar JSON: {len(rows)} dosya yazıldı.")

    if args.download_pdf:
        failed = []
        for row in rows:
            url = row.get("pdf_url")
            if not url:
                failed.append((row.get("sira_no", "?"), "pdf_url yok"))
                continue
            sn = row["sira_no"]
            path = base_dir / f"{sn}.pdf"
            print(f"  İndiriliyor: {sn}.pdf ...")
            if download_pdf(session, url, path):
                print(f"  Ok: {path}")
            else:
                failed.append((sn, url))
            time.sleep(args.sleep_pdf)
        if failed:
            print("Başarısız PDF indirmeleri:", failed)


if __name__ == "__main__":
    main()
