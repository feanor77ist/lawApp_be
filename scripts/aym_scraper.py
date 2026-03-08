"""
Anayasa Mahkemesi (AYM) karar toplayıcı (Bireysel Başvuru + Norm Denetimi + Siyasi Parti).

Kaynaklar:
- Bireysel Başvuru (BB):
  - Ana sayfa: https://kararlarbilgibankasi.anayasa.gov.tr/
  - Arama sonuçları: GET /Ara?KelimeAra[0]=...&page=...
  - Karar detayları: GET /BB/{yil}/{basvuru_no}
- Norm Denetimi (ND):
  - Ana sayfa: https://normkararlarbilgibankasi.anayasa.gov.tr/
  - Arama + sonuçlar: GET /?KelimeAra[0]=...&page=...
  - Karar detayları: GET /ND/{yil}/{karar_no}
- Siyasi Parti Kararları (SP):
  - Ana sayfa: https://siyasipartikararlar.anayasa.gov.tr/
  - Liste: GET /?page=...
  - Karar detayları: GET /SP/{yil}/{karar_no}/{suffix}

Özellikler:
- /Ara, Norm veya Siyasi Parti ana sayfa üzerinden sayfa sayfa karar listelerini çeker.
- Her karar için detay sayfasından:
  - Tam karar metnini (div#Karar) alır,
  - Kimlik / meta bilgilerini (div#KararDetaylari) ayrıştırır.
- Çıktıyı tek klasörde (JSON + opsiyonel TXT, opsiyonel HTML) tutar.
- Fail log desteği ile başarısız id'leri tekrar indirme imkânı sağlar.
- --type parametresiyle BB (bireysel), ND (norm) ve SP (siyasi) arasında geçiş yapılır.

Uyarılar:
- Çok hızlı isteklerde 429 veya reCAPTCHA çıkabilir; workers, sleep ve retries ile hız kontrolü yapın.
- Resmî kullanım koşullarını ve robots.txt'yi gözettiğinizden emin olun.

Örnek kullanım (Bireysel Başvuru, geniş bir kelimeyle başlayarak):

python scripts/aym_scraper.py \
  --type bireysel \
  --keyword "" \
  --page-size 30 \
  --start-page 1 \
  --max-pages 100 \
  --workers 4 \
  --sleep 0.5 \
  --sleep-doc 0.2 \
  --retries 6 \
  --retry-wait 6 \
  --out-dir data/aym_bireysel \
  --plain-text \
  --no-html

Başarısız BB indirmelerini tekrar denemek için:

python scripts/aym_scraper.py \
  --type bireysel \
  --retry-failed \
  --fail-log data/aym_failed_ids.txt \
  --out-dir data/aym_bireysel \
  --daire "Bireysel_Basvuru" \
  --plain-text \
  --no-html \
  --retries 10 --retry-wait 10 \
  --workers 2

Örnek kullanım (Norm Denetimi, tüm kararlar):

python scripts/aym_scraper.py \
  --type norm \
  --keyword "" \
  --page-size 10 \
  --start-page 1 \
  --workers 3 \
  --sleep 0.5 \
  --sleep-doc 0.2 \
  --retries 6 \
  --retry-wait 6 \
  --out-dir data/aym_norm \
  --plain-text \
  --no-html

Başarısız ND indirmelerini tekrar denemek için:

python scripts/aym_scraper.py \
  --type norm \
  --retry-failed \
  --fail-log data/aym_norm_failed_ids.txt \
  --out-dir data/aym_norm \
  --plain-text \
  --no-html \
  --retries 10 --retry-wait 10 \
  --workers 2

Örnek kullanım (Siyasi Parti Kararları, tüm kararlar ~1772):

python scripts/aym_scraper.py \
  --type siyasi \
  --page-size 10 \
  --start-page 1 \
  --workers 3 \
  --sleep 0.5 \
  --sleep-doc 0.2 \
  --retries 6 \
  --retry-wait 6 \
  --out-dir data/aym_siyasi \
  --plain-text \
  --no-html

Başarısız SP indirmelerini tekrar denemek için (liste tekrar dolaşılır):

python scripts/aym_scraper.py \
  --type siyasi \
  --retry-failed \
  --fail-log data/aym_siyasi_failed_ids.txt \
  --out-dir data/aym_siyasi \
  --plain-text \
  --no-html \
  --retries 10 --retry-wait 10 \
  --workers 2
"""

from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://kararlarbilgibankasi.anayasa.gov.tr"
NORM_BASE_URL = "https://normkararlarbilgibankasi.anayasa.gov.tr"
SIYASI_BASE_URL = "https://siyasipartikararlar.anayasa.gov.tr"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def start_session() -> requests.Session:
    """Yeni oturum açar."""
    session = requests.Session()
    session.get(BASE_URL, headers=HEADERS, timeout=20)
    return session


def start_session_norm() -> requests.Session:
    """Norm Denetimi için yeni oturum açar."""
    session = requests.Session()
    session.get(NORM_BASE_URL, headers=HEADERS, timeout=20)
    return session


def start_session_siyasi() -> requests.Session:
    """Siyasi Parti Kararları için yeni oturum açar."""
    session = requests.Session()
    session.get(SIYASI_BASE_URL, headers=HEADERS, timeout=20)
    return session


def build_query(args: argparse.Namespace, page_number: int) -> Dict[str, str]:
    """Arama sorgusu için query parametrelerini hazırlar."""
    query: Dict[str, str] = {
        "page": str(page_number),
    }
    if args.keyword:
        # KelimeAra[0]=... parametresi ile basit kelime arama
        query["KelimeAra[0]"] = args.keyword
    # Gerekirse ileride başka filtre alanları da buraya eklenebilir.
    return query


def parse_total_pages(soup: BeautifulSoup) -> Optional[int]:
    """Sayfa sayısını pagination bileşeninden okumaya çalışır."""
    pager = soup.find("ul", class_="pagination")
    if not pager:
        return None
    max_page = 1
    for a in pager.find_all("a"):
        text = (a.get_text() or "").strip()
        if text.isdigit():
            try:
                num = int(text)
                if num > max_page:
                    max_page = num
            except ValueError:
                continue
    return max_page or None


def extract_result_rows(soup: BeautifulSoup) -> List[Dict]:
    """
    Arama sonuç sayfasından karar satırlarını çıkarır.

    Sonuçlar, /BB/{yil}/{no} linkleri ile temsil edilir. Aynı karar için
    farklı anchor'lar olabildiğinden id bazında tekilleştirme yapılır.
    """
    rows: List[Dict] = []
    seen_ids: set = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/BB/" not in href:
            continue

        # /BB/2023/78445 veya /BB/2023/78445?Dil= gibi
        # Sorgu parametrelerini at.
        clean_href = href.split("?", 1)[0]
        if not clean_href.startswith("http"):
            clean_href = BASE_URL.rstrip("/") + clean_href

        m = re.search(r"/BB/(\d{4})/(\d+)$", clean_href)
        if not m:
            continue
        year, number = m.group(1), m.group(2)
        doc_id = f"{year}_{number}"
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)

        raw_text = a.get_text(" ", strip=True)
        # Bazı anchor'lar boş veya sadece "Dil" gibi olabilir, onları at.
        if not raw_text or "Bulunan Kelime Sayısı" in raw_text:
            # Sonuç satırındaki ikinci anchor'a bakmak için devam edebiliriz;
            # burada basitçe doc'u yine de kaydediyoruz.
            pass
        # Özet metni normalize et (gereksiz \n ve boşlukları temizle).
        summary = re.sub(r"\s+", " ", raw_text).strip()

        rows.append(
            {
                "id": doc_id,
                "year": year,
                "number": number,
                "url": clean_href,
                "summary": summary,
            }
        )

    return rows


def extract_result_rows_norm(soup: BeautifulSoup) -> List[Dict]:
    """
    Norm Denetimi arama sonuç sayfasından karar satırlarını çıkarır.

    Sonuçlar, /ND/{yil}/{karar_no} linkleri ile temsil edilir.
    """
    rows: List[Dict] = []
    seen_ids: set = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/ND/" not in href:
            continue

        clean_href = href.split("?", 1)[0]
        if not clean_href.startswith("http"):
            clean_href = NORM_BASE_URL.rstrip("/") + clean_href

        m = re.search(r"/ND/(\d{4})/(\d+)$", clean_href)
        if not m:
            continue
        year, number = m.group(1), m.group(2)
        doc_id = f"{year}_{number}"
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)

        raw_text = a.get_text(" ", strip=True)
        if not raw_text or "Bulunan Kelime Sayısı" in raw_text:
            # yine de id'yi kaydediyoruz
            pass
        summary = re.sub(r"\s+", " ", raw_text).strip()

        rows.append(
            {
                "id": doc_id,
                "year": year,
                "number": number,
                "url": clean_href,
                "summary": summary,
            }
        )

    return rows


def extract_result_rows_siyasi(soup: BeautifulSoup) -> List[Dict]:
    """
    Siyasi Parti Kararları arama sonuç sayfasından karar satırlarını çıkarır.

    Sonuçlar, /SP/{yil}/{karar_no}/{suffix} linkleri ile temsil edilir.
    doc_id = year_karar_no (örn. 2025_58).
    """
    rows: List[Dict] = []
    seen_ids: set = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/SP/" not in href:
            continue

        clean_href = href.split("?", 1)[0]
        if not clean_href.startswith("http"):
            clean_href = SIYASI_BASE_URL.rstrip("/") + clean_href

        # /SP/2025/58/2 veya /SP/2025/9/4
        m = re.search(r"/SP/(\d{4})/(\d+)/\d+$", clean_href)
        if not m:
            continue
        year, number = m.group(1), m.group(2)
        doc_id = f"{year}_{number}"
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)

        raw_text = a.get_text(" ", strip=True)
        summary = re.sub(r"\s+", " ", raw_text).strip()

        rows.append(
            {
                "id": doc_id,
                "year": year,
                "number": number,
                "url": clean_href,
                "summary": summary,
            }
        )

    return rows


def fetch_search_page(
    session: requests.Session,
    query: Dict[str, str],
    *,
    retries: int,
    retry_wait: float,
) -> Tuple[List[Dict], Optional[int]]:
    """
    Tek sayfalık arama sonucu döndürür.

    Geri dönen tuple:
    - rows: karar satırları listesi
    - total_pages: varsa toplam sayfa sayısı (pagination'dan okunur)
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(
                f"{BASE_URL}/Ara",
                params=query,
                headers=HEADERS,
                timeout=30,
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{resp.status_code}", response=resp)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            rows = extract_result_rows(soup)
            total_pages = parse_total_pages(soup)
            return rows, total_pages
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= retries:
                break
            wait_time = retry_wait * attempt
            print(f"[page-retry] {wait_time:.1f}s bekleniyor... ({exc})")
            time.sleep(wait_time)
    raise last_exc  # type: ignore[misc]


def fetch_search_page_norm(
    session: requests.Session,
    query: Dict[str, str],
    *,
    retries: int,
    retry_wait: float,
) -> Tuple[List[Dict], Optional[int]]:
    """
    Norm Denetimi için tek sayfalık arama sonucu döndürür.

    Geri dönen tuple:
    - rows: karar satırları listesi
    - total_pages: varsa toplam sayfa sayısı (pagination'dan okunur)
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(
                NORM_BASE_URL,
                params=query,
                headers=HEADERS,
                timeout=30,
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{resp.status_code}", response=resp)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            rows = extract_result_rows_norm(soup)
            total_pages = parse_total_pages(soup)
            return rows, total_pages
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= retries:
                break
            wait_time = retry_wait * attempt
            print(f"[page-retry-norm] {wait_time:.1f}s bekleniyor... ({exc})")
            time.sleep(wait_time)
    raise last_exc  # type: ignore[misc]


def fetch_search_page_siyasi(
    session: requests.Session,
    query: Dict[str, str],
    *,
    retries: int,
    retry_wait: float,
) -> Tuple[List[Dict], Optional[int]]:
    """
    Siyasi Parti Kararları için tek sayfalık liste sonucu döndürür.
    Liste: GET SIYASI_BASE_URL/?page=N
    """
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(
                SIYASI_BASE_URL,
                params=query,
                headers=HEADERS,
                timeout=30,
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{resp.status_code}", response=resp)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            rows = extract_result_rows_siyasi(soup)
            total_pages = parse_total_pages(soup)
            return rows, total_pages
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= retries:
                break
            wait_time = retry_wait * attempt
            print(f"[page-retry-siyasi] {wait_time:.1f}s bekleniyor... ({exc})")
            time.sleep(wait_time)
    raise last_exc  # type: ignore[misc]


def fetch_decision(
    session: requests.Session,
    row: Dict,
    *,
    retries: int,
    retry_wait: float,
) -> Tuple[str, str, Dict]:
    """
    Karar içeriğini (HTML + düz metin) ve temel meta'yı döndürür.

    - Tam karar metni: div#Karar içeriği
    - Kimlik/metaveri: div#KararDetaylari içeriğinden ayrıştırılır.
    """
    url = row["url"]
    last_exc: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers=HEADERS, timeout=40)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{resp.status_code}", response=resp)
            resp.raise_for_status()
            html = resp.text
            soup = BeautifulSoup(html, "lxml")

            # Tam karar metni
            karar_div = soup.find("div", id="Karar")
            if karar_div:
                # Hem BB hem ND sayfalarında esas karar metni çoğunlukla
                # div.KararMetni altında tutuluyor; varsa onu kullan.
                karar_metni_div = karar_div.find("div", class_="KararMetni")
                hedef_div = karar_metni_div or karar_div
                text = hedef_div.get_text("\n", strip=True)
            else:
                # Yedek: tüm sayfa metni
                text = soup.get_text("\n", strip=True)

            # Karar detayları (kimlik bilgileri)
            meta: Dict[str, str] = {
                "id": row.get("id"),
                "year": row.get("year"),
                "number": row.get("number"),
                "url": row.get("url"),
                "summary": row.get("summary"),
            }
            detay_div = soup.find("div", id="KararDetaylari")
            if detay_div:
                lines = [
                    ln.strip()
                    for ln in detay_div.get_text("\n", strip=True).splitlines()
                    if ln.strip()
                ]
                for i, ln in enumerate(lines):
                    # Bireysel başvuru etiketleri
                    if ln.startswith("Kararı Veren Birim") and i + 1 < len(lines):
                        meta["karari_veren_birim"] = lines[i + 1]
                    elif ln.startswith("Başvuru No") and i + 1 < len(lines):
                        meta["basvuru_no"] = lines[i + 1]
                    elif ln.startswith("Başvuru Tarihi") and i + 1 < len(lines):
                        meta["basvuru_tarihi"] = lines[i + 1]
                    elif ln.startswith("Karar Tarihi") and i + 1 < len(lines):
                        meta["karar_tarihi"] = lines[i + 1]
                    elif ln.startswith("Başvuru Adı") and i + 1 < len(lines):
                        meta["basvuru_adi"] = lines[i + 1]

                    # Norm denetimi etiketleri
                    def _value_from_line(label: str, key: str) -> None:
                        nonlocal meta
                        if label not in ln:
                            return
                        # Satır içinde değer olabilir: "Label: Değer"
                        val: Optional[str] = None
                        if ":" in ln:
                            after = ln.split(":", 1)[1].strip()
                            if after:
                                val = after
                        # Aksi halde bir sonraki satırı değer olarak al
                        if not val and i + 1 < len(lines):
                            val = lines[i + 1]
                        if val:
                            meta[key] = val

                    _value_from_line("Normun Türü", "normun_turu")
                    # \"Normun Numarası – Adı\" satırı genelde sadece başlık içeriyor;
                    # JSON'da ayrı alan olarak tutulmuyor.
                    _value_from_line("Esas No", "esas_no")
                    _value_from_line("Karar No", "karar_no")
                    _value_from_line("Resmi Gazete Tarihi", "resmi_gazete_tarihi")
                    _value_from_line("Resmi Gazete Sayısı", "resmi_gazete_sayisi")

            return html, text, meta
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= retries:
                break
            wait = retry_wait * attempt
            print(f"[doc-retry] {wait:.1f}s bekleniyor... ({url} -> {exc})")
            time.sleep(wait)

    raise last_exc  # type: ignore[misc]


def sanitize(text: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in text).strip("_")


def save_decision(
    base_dir: Path,
    meta: Dict,
    html: str,
    text: str,
    *,
    write_text: bool,
    write_html: bool,
) -> None:
    """
    Kararı diske yazar.

    Not: Tüm çıktılar tek klasörde tutulur; kararı veren birime göre alt klasör oluşturulmaz.
    """
    doc_id = meta.get("id") or "unknown"

    target_dir = base_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    meta_path = target_dir / f"{doc_id}.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    if write_html:
        html_path = target_dir / f"{doc_id}.html"
        html_path.write_text(html, encoding="utf-8")
    if write_text:
        txt_path = target_dir / f"{doc_id}.txt"
        txt_path.write_text(text, encoding="utf-8")


def load_existing_ids(base_dir: Path) -> set:
    ids = set()
    for json_file in base_dir.rglob("*.json"):
        ids.add(json_file.stem)
    return ids


def iterate_pages(
    session: requests.Session,
    args: argparse.Namespace,
) -> Iterable[Dict]:
    """
    Tüm sayfalardaki karar satırlarını üretir.

    - page_size: site/iç mantıktan bağımsız olarak sayfa başına satır adedi, yalnızca
      max_results hesaplamasında kullanılır.
    """
    page_number = args.start_page
    seen = (args.start_page - 1) * args.page_size
    total_pages_known: Optional[int] = None
    consecutive_failures = 0
    max_consecutive_failures = 3

    while True:
        query = build_query(args, page_number)
        try:
            rows, total_pages = fetch_search_page(
                session,
                query,
                retries=args.retries,
                retry_wait=args.retry_wait,
            )
            consecutive_failures = 0
            if total_pages is not None and total_pages_known is None:
                total_pages_known = total_pages
        except Exception as exc:  # noqa: BLE001
            consecutive_failures += 1
            print(
                f"[page-fail] Sayfa {page_number} başarısız "
                f"({consecutive_failures}/{max_consecutive_failures}): {exc}"
            )
            if consecutive_failures >= max_consecutive_failures:
                print(
                    f"[!] Ardışık {max_consecutive_failures} sayfa hatası. "
                    f"Durduruluyor. Devam için --start-page {page_number} deneyin."
                )
                return
            time.sleep(args.retry_wait * 2)
            page_number += 1
            continue

        if not rows:
            print(f"[page {page_number}] sonuç yok, döngü sonlandırılıyor.")
            break

        print(
            f"[page {page_number}] {len(rows)} karar bulundu."
            + (f" (toplam sayfa: {total_pages_known})" if total_pages_known else "")
        )

        for row in rows:
            yield row
            seen += 1
            if args.max_results and seen >= args.max_results:
                return

        page_number += 1
        if args.max_pages and page_number > args.max_pages:
            return
        if total_pages_known and page_number > total_pages_known:
            return
        if args.sleep > 0:
            time.sleep(args.sleep)


def iterate_pages_norm(
    session: requests.Session,
    args: argparse.Namespace,
) -> Iterable[Dict]:
    """
    Norm Denetimi için tüm sayfalardaki karar satırlarını üretir.
    """
    page_number = args.start_page
    seen = (args.start_page - 1) * args.page_size
    total_pages_known: Optional[int] = None
    consecutive_failures = 0
    max_consecutive_failures = 3

    while True:
        query = build_query(args, page_number)
        try:
            rows, total_pages = fetch_search_page_norm(
                session,
                query,
                retries=args.retries,
                retry_wait=args.retry_wait,
            )
            consecutive_failures = 0
            if total_pages is not None and total_pages_known is None:
                total_pages_known = total_pages
        except Exception as exc:  # noqa: BLE001
            consecutive_failures += 1
            print(
                f"[page-fail-norm] Sayfa {page_number} başarısız "
                f"({consecutive_failures}/{max_consecutive_failures}): {exc}"
            )
            if consecutive_failures >= max_consecutive_failures:
                print(
                    f"[!] Ardışık {max_consecutive_failures} sayfa hatası. "
                    f"Durduruluyor. Devam için --start-page {page_number} deneyin."
                )
                return
            time.sleep(args.retry_wait * 2)
            page_number += 1
            continue

        if not rows:
            print(f"[page {page_number}] (norm) sonuç yok, döngü sonlandırılıyor.")
            break

        print(
            f"[page {page_number}] (norm) {len(rows)} karar bulundu."
            + (f" (toplam sayfa: {total_pages_known})" if total_pages_known else "")
        )

        for row in rows:
            yield row
            seen += 1
            if args.max_results and seen >= args.max_results:
                return

        page_number += 1
        if args.max_pages and page_number > args.max_pages:
            return
        if total_pages_known and page_number > total_pages_known:
            return
        if args.sleep > 0:
            time.sleep(args.sleep)


def iterate_pages_siyasi(
    session: requests.Session,
    args: argparse.Namespace,
) -> Iterable[Dict]:
    """
    Siyasi Parti Kararları için tüm sayfalardaki karar satırlarını üretir.
    Liste sayfaları: ?page=1, ?page=2, ...
    """
    page_number = args.start_page
    seen = (args.start_page - 1) * args.page_size
    total_pages_known: Optional[int] = None
    consecutive_failures = 0
    max_consecutive_failures = 3

    while True:
        query = {"page": str(page_number)}
        try:
            rows, total_pages = fetch_search_page_siyasi(
                session,
                query,
                retries=args.retries,
                retry_wait=args.retry_wait,
            )
            consecutive_failures = 0
            if total_pages is not None and total_pages_known is None:
                total_pages_known = total_pages
        except Exception as exc:  # noqa: BLE001
            consecutive_failures += 1
            print(
                f"[page-fail-siyasi] Sayfa {page_number} başarısız "
                f"({consecutive_failures}/{max_consecutive_failures}): {exc}"
            )
            if consecutive_failures >= max_consecutive_failures:
                print(
                    f"[!] Ardışık {max_consecutive_failures} sayfa hatası. "
                    f"Durduruluyor. Devam için --start-page {page_number} deneyin."
                )
                return
            time.sleep(args.retry_wait * 2)
            page_number += 1
            continue

        if not rows:
            print(f"[page {page_number}] (siyasi) sonuç yok, döngü sonlandırılıyor.")
            break

        print(
            f"[page {page_number}] (siyasi) {len(rows)} karar bulundu."
            + (f" (toplam sayfa: {total_pages_known})" if total_pages_known else "")
        )

        for row in rows:
            yield row
            seen += 1
            if args.max_results and seen >= args.max_results:
                return

        page_number += 1
        if args.max_pages and page_number > args.max_pages:
            return
        if total_pages_known and page_number > total_pages_known:
            return
        if args.sleep > 0:
            time.sleep(args.sleep)


def download_one(
    row: Dict,
    args: argparse.Namespace,
    base_dir: Path,
    fail_log_path: Path,
    print_lock: Lock,
    counter: Dict,
) -> None:
    doc_id = row.get("id")
    if not doc_id:
        return

    session = start_session()
    try:
        html, text, meta = fetch_decision(
            session,
            row,
            retries=args.retries,
            retry_wait=args.retry_wait,
        )
    except Exception as exc:  # noqa: BLE001
        with print_lock:
            counter["failed"] += 1
            msg = f"{doc_id}\t{exc}"
            print(f"[fail] {msg}")
            with fail_log_path.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")
        return

    save_decision(
        base_dir,
        meta,
        html,
        text,
        write_text=args.plain_text,
        write_html=not args.no_html,
    )
    with print_lock:
        counter["saved"] += 1
        print(f"[{counter['saved']}] kaydedildi -> {meta.get('karari_veren_birim')} | {doc_id}")


def download_one_norm(
    row: Dict,
    args: argparse.Namespace,
    base_dir: Path,
    fail_log_path: Path,
    print_lock: Lock,
    counter: Dict,
) -> None:
    """Norm Denetimi için tek kararı indirir."""
    doc_id = row.get("id")
    if not doc_id:
        return

    session = start_session_norm()
    try:
        html, text, meta = fetch_decision(
            session,
            row,
            retries=args.retries,
            retry_wait=args.retry_wait,
        )
    except Exception as exc:  # noqa: BLE001
        with print_lock:
            counter["failed"] += 1
            msg = f"{doc_id}\t{exc}"
            print(f"[fail-norm] {msg}")
            with fail_log_path.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")
        return

    save_decision(
        base_dir,
        meta,
        html,
        text,
        write_text=args.plain_text,
        write_html=not args.no_html,
    )
    with print_lock:
        counter["saved"] += 1
        print(f"[{counter['saved']}] (norm) kaydedildi -> {meta.get('normun_turu')} | {doc_id}")


def download_one_siyasi(
    row: Dict,
    args: argparse.Namespace,
    base_dir: Path,
    fail_log_path: Path,
    print_lock: Lock,
    counter: Dict,
) -> None:
    """Siyasi Parti Kararları için tek kararı indirir."""
    doc_id = row.get("id")
    if not doc_id:
        return

    session = start_session_siyasi()
    try:
        html, text, meta = fetch_decision(
            session,
            row,
            retries=args.retries,
            retry_wait=args.retry_wait,
        )
    except Exception as exc:  # noqa: BLE001
        with print_lock:
            counter["failed"] += 1
            msg = f"{doc_id}\t{exc}"
            print(f"[fail-siyasi] {msg}")
            with fail_log_path.open("a", encoding="utf-8") as f:
                f.write(msg + "\n")
        return

    save_decision(
        base_dir,
        meta,
        html,
        text,
        write_text=args.plain_text,
        write_html=not args.no_html,
    )
    with print_lock:
        counter["saved"] += 1
        print(f"[{counter['saved']}] (siyasi) kaydedildi -> {doc_id}")


def load_failed_ids(fail_log_path: Path) -> List[str]:
    ids: List[str] = []
    if not fail_log_path.exists():
        return ids
    with fail_log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if "\t" in line:
                doc_id = line.split("\t", 1)[0]
                if doc_id:
                    ids.append(doc_id)
            else:
                ids.append(line)
    return ids


def make_row_from_id(doc_id: str, decision_type: str) -> Optional[Dict]:
    """
    Fail log'dan gelen bir id için satır nesnesi üretir.

    decision_type:
    - \"bireysel\" -> /BB/{yil}/{no}
    - \"norm\"     -> /ND/{yil}/{no}
    - \"siyasi\"   -> URL listeyi tekrar dolaşarak bulunur; burada None döner.
    """
    year = None
    number = None
    if "_" in doc_id:
        year, number = doc_id.split("_", 1)
    if not (year and number):
        return {"id": doc_id, "year": None, "number": None, "url": None, "summary": None}

    if decision_type == "siyasi":
        # Siyasi Parti URL'si /SP/{yil}/{no}/{suffix} biçiminde; suffix listeye göre değişir.
        # Retry akışında listeyi tekrar dolaşıp row'ları alıyoruz, burada None dönmeyelim
        # ama retry_failed_downloads siyasi için make_row_from_id kullanmayacak.
        return None

    if decision_type == "norm":
        base = NORM_BASE_URL.rstrip("/")
        path = "ND"
    else:
        base = BASE_URL.rstrip("/")
        path = "BB"

    url = f"{base}/{path}/{year}/{number}"
    return {"id": doc_id, "year": year, "number": number, "url": url, "summary": None}


def retry_failed_downloads(args: argparse.Namespace) -> None:
    """Başarısız indirmeleri tekrar dener."""
    base_dir = Path(args.out_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    fail_log_path = Path(args.fail_log)

    failed_ids = load_failed_ids(fail_log_path)
    if not failed_ids:
        print("Tekrar denenecek başarısız id bulunamadı.")
        return

    print(f"{len(failed_ids)} başarısız id tekrar denenecek...")

    new_fail_log = fail_log_path.with_suffix(".txt.new")
    counter = {"saved": 0, "failed": 0}
    print_lock = Lock()
    decision_type = getattr(args, "type", "bireysel")

    if decision_type == "siyasi":
        # Siyasi Parti URL'leri /SP/yil/no/suffix biçiminde; suffix listeye göre değişir.
        # Listeyi tekrar dolaşıp başarısız id'ler için row'ları topluyoruz.
        failed_set = set(failed_ids)
        session = start_session_siyasi()
        rows: List[Dict] = []
        for row in iterate_pages_siyasi(session, args):
            if row.get("id") in failed_set:
                rows.append(row)
        if not rows:
            print("Başarısız id'lerin hiçbiri listede bulunamadı.")
            return
        download_fn = download_one_siyasi
    else:
        download_fn = download_one_norm if decision_type == "norm" else download_one
        rows = []
        for doc_id in failed_ids:
            r = make_row_from_id(doc_id, decision_type)
            if r is not None:
                rows.append(r)
        if not rows:
            print("Geçerli satır üretilemedi.")
            return

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(
                download_fn,
                row,
                args,
                base_dir,
                new_fail_log,
                print_lock,
                counter,
            )
            for row in rows
        ]
        for _ in as_completed(futures):
            pass

    if new_fail_log.exists():
        new_fail_log.replace(fail_log_path)
    else:
        fail_log_path.write_text("", encoding="utf-8")

    print(
        f"Tamamlandı. {counter['saved']} karar indirildi, "
        f"{counter['failed']} hala başarısız."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AYM Bireysel Başvuru / Norm Denetimi karar toplayıcı",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--type",
        choices=["bireysel", "norm", "siyasi"],
        default="bireysel",
        help="Karar türü: bireysel başvuru, norm denetimi veya siyasi parti kararları",
    )
    parser.add_argument(
        "-k",
        "--keyword",
        default="",
        help="Aranacak kelime (KelimeAra[0]). Boş bırakılırsa site tüm kararları döndürmeye çalışabilir; dikkatli kullanın.",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=30,
        help="Sayfa başına beklenen karar sayısı (yalnızca max_results hesaplaması için).",
    )
    parser.add_argument("--start-page", type=int, default=1, help="Başlangıç sayfa numarası")
    parser.add_argument("--max-pages", type=int, default=None, help="Maks. sayfa sayısı")
    parser.add_argument("--max-results", type=int, default=None, help="Maks. karar adedi")
    parser.add_argument(
        "--out-dir",
        default="data/aym_bireysel",
        help="Çıktı klasörü",
    )
    parser.add_argument("--plain-text", action="store_true", help="Tam karar metnini TXT olarak yaz")
    parser.add_argument("--no-html", action="store_true", help="HTML dosyası kaydetme")
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.4,
        help="Sayfa istekleri arasında bekleme (saniye)",
    )
    parser.add_argument(
        "--sleep-doc",
        type=float,
        default=0.2,
        help="Her doküman indirmesi sonrası bekleme (saniye)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=5,
        help="429/5xx için tekrar sayısı",
    )
    parser.add_argument(
        "--retry-wait",
        type=float,
        default=5.0,
        help="İlk tekrar bekleme süresi (saniye); her denemede katlanır",
    )
    parser.add_argument(
        "--no-skip-existing",
        action="store_true",
        help="Aynı id için mevcut dosyaları yok sayma (varsayılan: atla)",
    )
    parser.add_argument(
        "--fail-log",
        default="data/aym_failed_ids.txt",
        help="Başarısız id/hata mesajı kaydı",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=3,
        help="Paralel indirme için worker sayısı (önerilen: 2-5)",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Başarısız indirmeleri (fail-log dosyasından) tekrar dene",
    )
    parser.add_argument(
        "--daire",
        default="Bireysel_Basvuru",
        help="--retry-failed modunda kullanılacak daire adı (klasör ismi)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.retry_failed:
        retry_failed_downloads(args)
        return

    base_dir = Path(args.out_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    fail_log_path = Path(args.fail_log)
    fail_log_path.parent.mkdir(parents=True, exist_ok=True)

    existing_ids: set = set()
    if not args.no_skip_existing:
        print("Mevcut dosyalar taranıyor...")
        existing_ids = load_existing_ids(base_dir)
        print(f"{len(existing_ids)} mevcut karar bulundu.")

    # Tür bazlı yardımcı fonksiyonlar
    if args.type == "norm":
        start_session_fn = start_session_norm
        iterate_fn = iterate_pages_norm
        download_fn = download_one_norm
    elif args.type == "siyasi":
        start_session_fn = start_session_siyasi
        iterate_fn = iterate_pages_siyasi
        download_fn = download_one_siyasi
    else:
        start_session_fn = start_session
        iterate_fn = iterate_pages
        download_fn = download_one

    session = start_session_fn()
    total_skipped = 0
    counter = {"saved": 0, "failed": 0}
    print_lock = Lock()

    pending_rows: List[Dict] = []

    for row in iterate_fn(session, args):
        doc_id = row.get("id")
        if not doc_id:
            continue
        if doc_id in existing_ids and not args.no_skip_existing:
            total_skipped += 1
            continue

        pending_rows.append(row)

        if len(pending_rows) >= args.workers * 2:
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = [
                    executor.submit(
                        download_fn,
                        r,
                        args,
                        base_dir,
                        fail_log_path,
                        print_lock,
                        counter,
                    )
                    for r in pending_rows
                ]
                for _ in as_completed(futures):
                    pass
            pending_rows.clear()
            if args.sleep_doc > 0:
                time.sleep(args.sleep_doc)

    if pending_rows:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [
                executor.submit(
                    download_fn,
                    r,
                    args,
                    base_dir,
                    fail_log_path,
                    print_lock,
                    counter,
                )
                for r in pending_rows
            ]
            for _ in as_completed(futures):
                pass

    print(
        f"Tamamlandı. {counter['saved']} karar indirildi, "
        f"{total_skipped} atlandı, {counter['failed']} başarısız. Çıkış: {base_dir}"
    )


if __name__ == "__main__":
    main()

