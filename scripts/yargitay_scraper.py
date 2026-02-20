"""
Basit Yargıtay karar toplayıcı.

Özellikler:
- Anahtar kelime veya detaylı arama parametreleri ile /aramalist API'sini çağırır.
- Sayfalar üzerinde gezinip tüm karar id'lerini çeker.
- Her karar için /getDokuman ile HTML gövdesini indirir, isteğe bağlı düz metin üretir.
- Çıktıyı daire bazında klasörlere (HTML + meta + opsiyonel txt) yazar.
- --retry-failed ile başarısız indirmeleri tekrar deneyebilirsiniz.

Uyarılar:
- Site reCAPTCHA gösterebilir; bu durumda istekte "DisplayCaptcha" hatası dönebilir.
- Resmî kullanım koşullarını ve robots.txt'yi gözettiğinizden emin olun.

Örnek kullanım:
python scripts/yargitay_scraper.py \
  --keyword "" \
  --kurul "Hukuk Genel Kurulu" \
  --detail \
  --page-size 50 \
  --start-page 55 \
  --sleep 0.5 \
  --retries 6 \
  --retry-wait 6 \
  --out-dir data/yargitay_hukuk_genel_kurulu \
  --plain-text \
  --no-html \
  --workers 5

Başarısız indirmeleri tekrar denemek için:
python scripts/yargitay_scraper.py \
  --retry-failed \
  --fail-log data/yargitay_failed_ids.txt \
  --out-dir data/yargitay_hukuk_genel_kurulu \
  --daire "Hukuk Genel Kurulu" \
  --plain-text --no-html \
  --retries 10 --retry-wait 10 \
  --workers 2
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://karararama.yargitay.gov.tr"

# Tarayıcıya benzeyen başlıklar; X-Requested-With olmadan arama reddediliyor.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Content-Type": "application/json; charset=utf-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}


def start_session() -> requests.Session:
    """Yeni oturum açar ve JSESSIONID almak için ana sayfayı çeker."""
    session = requests.Session()
    session.get(f"{BASE_URL}/index", headers=HEADERS, timeout=20)
    return session


def build_payload(args: argparse.Namespace, page_number: int) -> Dict[str, str]:
    """Arama isteği gövdesini hazırlar."""
    payload: Dict[str, str] = {
        "arananKelime": args.keyword,
        "aranan": args.keyword,
        "siralama": args.sort_field,
        "siralamaDirection": args.sort_dir,
        "pageSize": str(args.page_size),
        "pageNumber": str(page_number),
    }

    # Detaylı filtreler
    if args.esas_yil:
        payload["esasYil"] = str(args.esas_yil)
    if args.esas_ilk:
        payload["esasIlkSiraNo"] = str(args.esas_ilk)
    if args.esas_son:
        payload["esasSonSiraNo"] = str(args.esas_son)
    if args.karar_yil:
        payload["kararYil"] = str(args.karar_yil)
    if args.karar_ilk:
        payload["kararIlkSiraNo"] = str(args.karar_ilk)
    if args.karar_son:
        payload["kararSonSiraNo"] = str(args.karar_son)
    if args.start_date:
        payload["baslangicTarihi"] = args.start_date
    if args.end_date:
        payload["bitisTarihi"] = args.end_date
    if args.kurul:
        payload["birimYrgKurulDaire"] = "+".join(args.kurul)
    if args.hukuk:
        payload["birimYrgHukukDaire"] = "+".join(args.hukuk)
    if args.ceza:
        payload["birimYrgCezaDaire"] = "+".join(args.ceza)

    return payload


def fetch_page(
    session: requests.Session,
    payload: Dict[str, str],
    *,
    detail: bool,
    retries: int,
    retry_wait: float,
) -> Tuple[List[Dict], int, int]:
    """Tek sayfa arama sonucu döndürür. detail=True ise /aramadetaylist kullanılır."""
    url = f"{BASE_URL}/aramadetaylist" if detail else f"{BASE_URL}/aramalist"
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.post(url, json={"data": payload}, headers=HEADERS, timeout=30)
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{resp.status_code}", response=resp)
            resp.raise_for_status()
            body = resp.json()
            metadata = body.get("metadata", {})
            if metadata.get("FMTY") == "ERROR":
                error_code = metadata.get("FMC", "")
                # RUNTIME_EXCEPTION geçici olabilir, retry yap
                if "RUNTIME_EXCEPTION" in error_code:
                    print(f"[page-warn] Sunucu geçici hatası (attempt {attempt}/{retries}): {error_code}")
                    raise requests.HTTPError(f"RUNTIME_EXCEPTION: {metadata}")
                raise RuntimeError(f"Arama hatası: {metadata}")

            data = body["data"]
            return data["data"], int(data.get("recordsTotal", 0)), int(
                data.get("recordsFiltered", 0)
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= retries:
                break
            wait_time = retry_wait * attempt
            print(f"[page-retry] {wait_time:.1f}s bekleniyor...")
            time.sleep(wait_time)
    raise last_exc  # type: ignore[misc]


def fetch_document(
    session: requests.Session,
    doc_id: str,
    *,
    retries: int,
    retry_wait: float,
) -> Tuple[str, str]:
    """Karar içeriğini (HTML + düz metin) döndürür, 429/5xx için tekrar dener."""
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(
                f"{BASE_URL}/getDokuman?id={doc_id}", headers=HEADERS, timeout=30
            )
            if resp.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"{resp.status_code}", response=resp)
            resp.raise_for_status()
            body = resp.json()
            html = body.get("data")
            if not html:
                raise ValueError("Boş/None html döndü")
            soup = BeautifulSoup(html, "lxml")
            text = soup.get_text("\n", strip=True)
            return html, text
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= retries:
                break
            time.sleep(retry_wait * attempt)
    raise last_exc  # type: ignore[misc]


def sanitize(text: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in text).strip(
        "_"
    )


def save_decision(
    base_dir: Path,
    row: Dict,
    html: str,
    text: str,
    write_text: bool = False,
    write_html: bool = True,
) -> None:
    daire = sanitize(row.get("daire", "unknown"))
    doc_id = row.get("id", "unknown")
    target_dir = base_dir / daire
    target_dir.mkdir(parents=True, exist_ok=True)

    meta_path = target_dir / f"{doc_id}.json"
    meta_path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    if write_html:
        html_path = target_dir / f"{doc_id}.html"
        html_path.write_text(html, encoding="utf-8")
    if write_text:
        txt_path = target_dir / f"{doc_id}.txt"
        txt_path.write_text(text, encoding="utf-8")


def decision_exists(base_dir: Path, row: Dict) -> bool:
    doc_id = row.get("id", "unknown")
    daire = sanitize(row.get("daire", "unknown"))
    html_path = base_dir / daire / f"{doc_id}.html"
    return html_path.exists()


def load_existing_ids(base_dir: Path) -> set:
    """Mevcut indirilen id'leri belleğe yükler (hızlı lookup için)."""
    ids = set()
    # json her zaman yazılır, ona göre kontrol et
    for json_file in base_dir.rglob("*.json"):
        ids.add(json_file.stem)
    return ids


def iterate_pages(
    session: requests.Session,
    args: argparse.Namespace,
) -> Iterable[Dict]:
    """Tüm sayfalardaki karar satırlarını üretir."""
    page_number = args.start_page
    seen = (args.start_page - 1) * args.page_size
    detail = (
        args.detail
        or not args.keyword
        or args.kurul
        or args.hukuk
        or args.ceza
        or args.start_date
        or args.end_date
        or args.esas_yil
        or args.karar_yil
    )
    consecutive_failures = 0
    max_consecutive_failures = 3

    while True:
        payload = build_payload(args, page_number)
        try:
            rows, total, _ = fetch_page(
                session,
                payload,
                detail=detail,
                retries=args.retries,
                retry_wait=args.retry_wait,
            )
            consecutive_failures = 0  # Başarılı, sıfırla
        except Exception as e:
            consecutive_failures += 1
            print(f"[page-fail] Sayfa {page_number} başarısız ({consecutive_failures}/{max_consecutive_failures}): {e}")
            if consecutive_failures >= max_consecutive_failures:
                print(f"[!] Ardışık {max_consecutive_failures} sayfa hatası. Durduruluyor.")
                print(f"[!] Kaldığınız yerden devam için: --start-page {page_number}")
                raise
            # Bir sonraki sayfayı dene
            page_number += 1
            time.sleep(args.retry_wait * 2)
            continue

        if not rows:
            break
        print(f"[page {page_number}] {len(rows)} kayıt, toplam: {total}")
        for row in rows:
            yield row
            seen += 1
            if args.max_results and seen >= args.max_results:
                return
        page_number += 1
        if args.max_pages and page_number > args.max_pages:
            return
        # Çok hızlı gitmemek için küçük bekleme
        if args.sleep > 0:
            time.sleep(args.sleep)
        # Sunucunun bildirdiği toplamı aştıysak kır
        if seen >= total:
            return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Yargıtay karar arayıcı")
    parser.add_argument(
        "-k",
        "--keyword",
        default="",
        help="Aranacak kelime (boş bırakılabilir; o durumda birim/tarih filtreleri gerekli)",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Detaylı arama modunu zorla (/aramadetaylist). Birim/tarih filtreleri kullanıyorsanız önerilir.",
    )
    parser.add_argument(
        "--page-size", type=int, default=50, help="Sayfa başına kayıt (varsayılan 50)"
    )
    parser.add_argument("--max-pages", type=int, default=None, help="Maks. sayfa sayısı")
    parser.add_argument("--start-page", type=int, default=1, help="Başlangıç sayfa numarası (varsayılan 1)")
    parser.add_argument("--max-results", type=int, default=None, help="Maks. karar adedi")
    parser.add_argument(
        "--sort-field",
        default="1",
        choices=["1", "2", "3"],
        help="Sıralama alanı: 1=Esas No, 2=Karar No, 3=Karar Tarihi",
    )
    parser.add_argument(
        "--sort-dir",
        default="desc",
        choices=["asc", "desc"],
        help="Sıralama yönü (asc/desc)",
    )
    parser.add_argument("--start-date", help="Başlangıç tarihi (GG.AA.YYYY)")
    parser.add_argument("--end-date", help="Bitiş tarihi (GG.AA.YYYY)")
    parser.add_argument("--esas-yil", type=int, help="Esas yılı")
    parser.add_argument("--esas-ilk", type=int, help="Esas ilk sıra no")
    parser.add_argument("--esas-son", type=int, help="Esas son sıra no")
    parser.add_argument("--karar-yil", type=int, help="Karar yılı")
    parser.add_argument("--karar-ilk", type=int, help="Karar ilk sıra no")
    parser.add_argument("--karar-son", type=int, help="Karar son sıra no")
    parser.add_argument(
        "--kurul",
        nargs="*",
        default=[],
        help="Kurul/dairenin adı (örn: 'Hukuk Genel Kurulu'). Çoklu için boşlukla ayır.",
    )
    parser.add_argument(
        "--hukuk",
        nargs="*",
        default=[],
        help="Hukuk daireleri (örn: '22. Hukuk Dairesi').",
    )
    parser.add_argument(
        "--ceza",
        nargs="*",
        default=[],
        help="Ceza daireleri (örn: '1. Ceza Dairesi').",
    )
    parser.add_argument(
        "--out-dir",
        default="data/yargitay_raw",
        help="Çıktı klasörü (varsayılan: data/yargitay_raw)",
    )
    parser.add_argument(
        "--plain-text",
        action="store_true",
        help="HTML yanında düz metin dosyası da yaz",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        help="HTML dosyası kaydetme (sadece txt + json için)",
    )
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
        help="429/5xx için doküman indirme tekrar sayısı",
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
        default="data/yargitay_failed_ids.txt",
        help="Başarısız id/hata mesajı kaydı (varsayılan: data/yargitay_failed_ids.txt)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Paralel indirme için worker sayısı (varsayılan: 1, önerilen: 3-5)",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Başarısız indirmeleri (fail-log dosyasından) tekrar dene",
    )
    parser.add_argument(
        "--daire",
        default="unknown",
        help="--retry-failed modunda kullanılacak daire adı (varsayılan: unknown)",
    )
    return parser.parse_args()


def download_single(
    row: Dict,
    args: argparse.Namespace,
    base_dir: Path,
    fail_log_path: Path,
    print_lock: Lock,
    counter: Dict,
) -> None:
    """Tek bir dokümanı indir ve kaydet (paralel worker için)."""
    doc_id = row.get("id")
    if not doc_id:
        return
    # Her worker kendi session'ını kullanır
    session = requests.Session()
    session.get(f"{BASE_URL}/index", headers=HEADERS, timeout=20)

    try:
        html, text = fetch_document(
            session,
            doc_id,
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

    save_decision(base_dir, row, html, text, write_text=args.plain_text, write_html=not args.no_html)
    with print_lock:
        counter["saved"] += 1
        print(f"[{counter['saved']}] kaydedildi -> {row.get('daire')} | {doc_id}")


def load_failed_ids(fail_log_path: Path) -> List[str]:
    """Fail log dosyasından başarısız id'leri yükler."""
    ids = []
    if fail_log_path.exists():
        with fail_log_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and "\t" in line:
                    doc_id = line.split("\t")[0]
                    if doc_id:
                        ids.append(doc_id)
                elif line:
                    ids.append(line)
    return ids


def retry_failed_downloads(args: argparse.Namespace) -> None:
    """Başarısız indirmeleri tekrar dener."""
    base_dir = Path(args.out_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    fail_log_path = Path(args.fail_log)

    if not fail_log_path.exists():
        print(f"Fail log dosyası bulunamadı: {fail_log_path}")
        return

    failed_ids = load_failed_ids(fail_log_path)
    if not failed_ids:
        print("Tekrar denenecek başarısız id bulunamadı.")
        return

    print(f"{len(failed_ids)} başarısız id tekrar denenecek...")

    # Yeni fail log için geçici dosya
    new_fail_log = fail_log_path.with_suffix(".txt.new")
    counter = {"saved": 0, "failed": 0}
    print_lock = Lock()

    # Her id için row oluştur
    rows = [{"id": doc_id, "daire": args.daire} for doc_id in failed_ids]

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(
                download_single, row, args, base_dir, new_fail_log, print_lock, counter
            )
            for row in rows
        ]
        for _ in as_completed(futures):
            pass

    # Eski fail log'u yenisiyle değiştir
    if new_fail_log.exists():
        new_fail_log.replace(fail_log_path)
    else:
        # Tüm indirmeler başarılı, fail log'u temizle
        fail_log_path.write_text("", encoding="utf-8")

    print(
        f"Tamamlandı. {counter['saved']} karar indirildi, "
        f"{counter['failed']} hala başarısız."
    )


def main() -> None:
    args = parse_args()

    # --retry-failed modu
    if args.retry_failed:
        retry_failed_downloads(args)
        return

    base_dir = Path(args.out_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    fail_log_path = Path(args.fail_log)
    fail_log_path.parent.mkdir(parents=True, exist_ok=True)

    # Mevcut id'leri belleğe yükle (hızlı skip için)
    existing_ids: set = set()
    if not args.no_skip_existing:
        print("Mevcut dosyalar taranıyor...")
        existing_ids = load_existing_ids(base_dir)
        print(f"{len(existing_ids)} mevcut karar bulundu.")

    session = start_session()
    total_skipped = 0
    counter = {"saved": 0, "failed": 0}
    print_lock = Lock()

    # Satırları topla, filtrelenmişleri paralel indir
    pending_rows: List[Dict] = []
    page_fail_count = 0
    max_page_failures = 3  # Ardışık sayfa hatasında dur

    try:
        for row in iterate_pages(session, args):
            page_fail_count = 0  # Başarılı sayfa, sıfırla
            doc_id = row.get("id")
            if not doc_id:
                continue
            if doc_id in existing_ids:
                total_skipped += 1
                continue
            pending_rows.append(row)

            # Batch halinde paralel indir
            if len(pending_rows) >= args.workers * 2:
                with ThreadPoolExecutor(max_workers=args.workers) as executor:
                    futures = [
                        executor.submit(download_single, r, args, base_dir, fail_log_path, print_lock, counter)
                        for r in pending_rows
                    ]
                    for f in as_completed(futures):
                        pass  # Hataları download_single içinde yakalıyoruz
                pending_rows.clear()
                if args.sleep > 0:
                    time.sleep(args.sleep)
    except RuntimeError as e:
        error_msg = str(e)
        if "ADALET_RUNTIME_EXCEPTION" in error_msg or "Arama hatası" in error_msg:
            print(f"\n[!] Sunucu hatası: {error_msg}")
            print("[!] Kaldığınız yerden devam etmek için --start-page parametresini kullanın.")
            print(f"[!] Şu ana kadar {counter['saved']} karar indirildi, {total_skipped} atlandı.")
        else:
            raise

    # Kalan satırları indir
    if pending_rows:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [
                executor.submit(download_single, r, args, base_dir, fail_log_path, print_lock, counter)
                for r in pending_rows
            ]
            for f in as_completed(futures):
                pass

    print(f"Tamamlandı. {counter['saved']} karar indirildi, {total_skipped} atlandı, {counter['failed']} başarısız. Çıkış: {base_dir}")


if __name__ == "__main__":
    main()
