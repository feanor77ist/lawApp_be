"""
Emsal Karar Arama (emsal.uyap.gov.tr) karar toplayıcı - Async versiyon.

Özellikler:
- asyncio + aiohttp ile yüksek performanslı paralel indirme.
- Adaptive rate limiting: yanıt süresi izleme, otomatik hız ayarlama.
- Global pause: 429/DisplayCaptcha durumunda tüm istekleri durdurur.
- Exponential backoff with jitter.
- Connection pooling ve session reuse.

Kullanım:
python scripts/emsal_scraper.py \
  --keyword "" \
  --chamber-field "Bam Hukuk Mahkemeleri" \
  --chambers "İstanbul Bölge Adliye Mahkemesi 18. Hukuk Dairesi" \
  --page-size 50 --start-page 1 \
  --concurrency 8 --min-delay 0.1 --max-delay 2.0 \
  --retries 6 --retry-wait 5 \
  --plain-text --no-html \
  --out-dir data/emsal_bam

Önemli:
- En azından bir filtre (daire veya tarih) verin; kelime boş bırakılabilir.
- concurrency: eşzamanlı doküman indirme sayısı (varsayılan 8).
- min-delay/max-delay: adaptive throttling aralığı.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup

BASE_URL = "https://emsal.uyap.gov.tr"

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


@dataclass
class RateLimiter:
    """Adaptive rate limiter with response time monitoring."""

    min_delay: float = 0.1
    max_delay: float = 2.0
    current_delay: float = 0.2
    # Response time thresholds (seconds)
    fast_threshold: float = 1.0  # Below this = speed up
    slow_threshold: float = 3.0  # Above this = slow down
    # Adjustment factors
    speedup_factor: float = 0.85
    slowdown_factor: float = 1.5
    # Global pause state
    paused_until: float = 0.0
    pause_duration: float = 30.0  # Initial pause on 429
    consecutive_429s: int = 0
    # Rolling average response time
    response_times: List[float] = field(default_factory=list)
    max_samples: int = 20
    # Lock for thread safety
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def wait(self) -> None:
        """Wait according to current rate limit state."""
        async with self._lock:
            # Check global pause
            now = time.time()
            if now < self.paused_until:
                wait_time = self.paused_until - now
                print(f"[throttle] Global pause: {wait_time:.1f}s kaldı...")
                await asyncio.sleep(wait_time)

            # Add jitter to prevent thundering herd
            jitter = random.uniform(0, self.current_delay * 0.3)
            await asyncio.sleep(self.current_delay + jitter)

    async def record_response(self, response_time: float, status: int) -> None:
        """Record response and adjust rate."""
        async with self._lock:
            if status == 429:
                self.consecutive_429s += 1
                # Exponential backoff on consecutive 429s
                pause = self.pause_duration * (2 ** min(self.consecutive_429s - 1, 4))
                self.paused_until = time.time() + pause
                self.current_delay = min(self.max_delay, self.current_delay * 2)
                print(
                    f"[throttle] 429 alındı! {pause:.0f}s pause, "
                    f"delay -> {self.current_delay:.2f}s"
                )
                return

            # Success - reset 429 counter
            self.consecutive_429s = 0

            # Update rolling average
            self.response_times.append(response_time)
            if len(self.response_times) > self.max_samples:
                self.response_times.pop(0)

            avg_time = sum(self.response_times) / len(self.response_times)

            # Adaptive adjustment
            if avg_time < self.fast_threshold and len(self.response_times) >= 5:
                # Server responding fast - speed up
                new_delay = max(self.min_delay, self.current_delay * self.speedup_factor)
                if new_delay < self.current_delay:
                    self.current_delay = new_delay
            elif avg_time > self.slow_threshold:
                # Server slowing down - back off before 429
                new_delay = min(self.max_delay, self.current_delay * self.slowdown_factor)
                if new_delay > self.current_delay:
                    print(
                        f"[throttle] Yavaşlama algılandı (avg={avg_time:.2f}s), "
                        f"delay -> {new_delay:.2f}s"
                    )
                    self.current_delay = new_delay


async def get_session_cookies(session: aiohttp.ClientSession) -> None:
    """Initialize session by visiting index page."""
    async with session.get(f"{BASE_URL}/index", headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)):
        pass  # Just need to get cookies


def build_payload(
    args: argparse.Namespace,
    page_number: int,
    chamber_value: Optional[str] = None,
) -> Dict[str, str]:
    payload: Dict[str, str] = {
        "arananKelime": args.keyword,
        "aranan": args.keyword,
        "siralama": args.sort_field,
        "siralamaDirection": args.sort_dir,
        "pageSize": str(args.page_size),
        "pageNumber": str(page_number),
    }
    if chamber_value:
        val_str = (
            "+".join(chamber_value)
            if isinstance(chamber_value, (list, tuple))
            else str(chamber_value)
        )
        payload["birimHukukMah"] = val_str
        payload[args.chamber_field] = val_str
        payload["hukuk"] = val_str
    if args.start_date:
        payload["baslangicTarihi"] = args.start_date
    if args.end_date:
        payload["bitisTarihi"] = args.end_date
    return payload


async def fetch_page(
    session: aiohttp.ClientSession,
    payload: Dict[str, str],
    rate_limiter: RateLimiter,
    retries: int,
    retry_wait: float,
) -> Tuple[List[Dict], int, int]:
    """Fetch a single search result page with rate limiting."""
    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        # Wait for rate limiter (respects global pause)
        await rate_limiter.wait()
        start_time = time.time()

        try:
            async with session.post(
                f"{BASE_URL}/aramadetaylist",
                json={"data": payload},
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                response_time = time.time() - start_time

                if resp.status == 429:
                    await rate_limiter.record_response(response_time, 429)
                    raise aiohttp.ClientResponseError(
                        resp.request_info,
                        resp.history,
                        status=429,
                    )
                if resp.status in (500, 502, 503, 504):
                    raise aiohttp.ClientResponseError(
                        resp.request_info,
                        resp.history,
                        status=resp.status,
                    )

                await rate_limiter.record_response(response_time, resp.status)
                resp.raise_for_status()
                body = await resp.json()
                if body.get("metadata", {}).get("FMTY") == "ERROR":
                    raise RuntimeError(f"Arama hatası: {body.get('metadata')}")
                data = body["data"]
                return (
                    data["data"],
                    int(data.get("recordsTotal", 0)),
                    int(data.get("recordsFiltered", 0)),
                )
        except Exception as exc:
            last_exc = exc
            if attempt >= retries:
                break
            wait = retry_wait * attempt + random.uniform(0, 2)
            await asyncio.sleep(wait)
    raise last_exc  # type: ignore[misc]


async def fetch_document(
    session: aiohttp.ClientSession,
    doc_id: str,
    rate_limiter: RateLimiter,
    retries: int,
    retry_wait: float,
) -> Tuple[str, str]:
    """Fetch document content with rate limiting."""
    last_exc: Optional[Exception] = None

    for attempt in range(1, retries + 1):
        await rate_limiter.wait()
        start_time = time.time()

        try:
            async with session.get(
                f"{BASE_URL}/getDokuman?id={doc_id}",
                headers=HEADERS,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                response_time = time.time() - start_time
                await rate_limiter.record_response(response_time, resp.status)

                if resp.status == 429:
                    raise aiohttp.ClientResponseError(
                        resp.request_info,
                        resp.history,
                        status=429,
                    )
                if resp.status in (500, 502, 503, 504):
                    raise aiohttp.ClientResponseError(
                        resp.request_info,
                        resp.history,
                        status=resp.status,
                    )
                resp.raise_for_status()
                body = await resp.json()

                # Check for DisplayCaptcha error
                if body.get("metadata", {}).get("FMTY") == "ERROR":
                    msg = body.get("metadata", {}).get("MSG", "")
                    if "Captcha" in msg or "DisplayCaptcha" in msg:
                        # Treat like 429
                        await rate_limiter.record_response(response_time, 429)
                        raise RuntimeError(f"DisplayCaptcha: {msg}")
                    raise RuntimeError(f"API Error: {msg}")

                html = body.get("data")
                if not html:
                    raise ValueError("Boş/None html döndü")
                soup = BeautifulSoup(html, "lxml")
                text = soup.get_text("\n", strip=True)
                return html, text

        except Exception as exc:
            last_exc = exc
            if attempt >= retries:
                break
            # Exponential backoff with jitter
            wait = retry_wait * attempt + random.uniform(0, 2)
            await asyncio.sleep(wait)

    raise last_exc  # type: ignore[misc]


def save_decision(
    base_dir: Path,
    row: Dict,
    html: str,
    text: str,
    write_text: bool,
    write_html: bool,
) -> None:
    daire = row.get("daire", "unknown").replace("/", "-")
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


def load_existing_ids(base_dir: Path) -> set:
    ids = set()
    for json_file in base_dir.rglob("*.json"):
        ids.add(json_file.stem)
    return ids


async def download_worker(
    queue: asyncio.Queue,
    session: aiohttp.ClientSession,
    rate_limiter: RateLimiter,
    args: argparse.Namespace,
    base_dir: Path,
    fail_log_path: Path,
    counter: Dict,
    counter_lock: asyncio.Lock,
) -> None:
    """Worker coroutine that processes download tasks from queue."""
    while True:
        try:
            row = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break

        if row is None:  # Poison pill
            queue.task_done()
            break

        doc_id = row.get("id")
        if not doc_id:
            queue.task_done()
            continue

        try:
            html, text = await fetch_document(
                session, doc_id, rate_limiter, args.retries, args.retry_wait
            )
            save_decision(
                base_dir,
                row,
                html,
                text,
                write_text=args.plain_text,
                write_html=not args.no_html,
            )
            async with counter_lock:
                counter["saved"] += 1
                print(f"[{counter['saved']}] kaydedildi -> {row.get('daire')} | {doc_id}")

        except Exception as exc:
            async with counter_lock:
                counter["failed"] += 1
                msg = f"{doc_id}\t{exc}"
                print(f"[fail] {msg}")
                with fail_log_path.open("a", encoding="utf-8") as f:
                    f.write(msg + "\n")

        queue.task_done()


async def async_main(args: argparse.Namespace) -> None:
    base_dir = Path(args.out_dir)
    base_dir.mkdir(parents=True, exist_ok=True)
    fail_log_path = Path(args.fail_log)
    fail_log_path.parent.mkdir(parents=True, exist_ok=True)

    existing_ids: set = set()
    if not args.no_skip_existing:
        print("Mevcut dosyalar taranıyor...")
        existing_ids = load_existing_ids(base_dir)
        print(f"{len(existing_ids)} mevcut karar bulundu.")

    # Initialize rate limiter
    rate_limiter = RateLimiter(
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        current_delay=(args.min_delay + args.max_delay) / 2,  # Start in the middle
        pause_duration=args.pause_duration,
    )

    # Connection pooling
    connector = aiohttp.TCPConnector(
        limit=args.concurrency + 2,  # Extra for page fetches
        limit_per_host=args.concurrency + 2,
        ttl_dns_cache=300,
        enable_cleanup_closed=True,
    )

    # Cookie jar for session persistence
    cookie_jar = aiohttp.CookieJar()

    counter = {"saved": 0, "failed": 0}
    counter_lock = asyncio.Lock()
    total_skipped = 0

    async with aiohttp.ClientSession(
        connector=connector,
        cookie_jar=cookie_jar,
    ) as session:
        # Initialize session cookies
        await get_session_cookies(session)

        # Initialize detailed search
        chamber_values = args.chambers or [None]

        # Create work queue
        queue: asyncio.Queue = asyncio.Queue(maxsize=args.concurrency * 3)

        # Start workers
        workers = [
            asyncio.create_task(
                download_worker(
                    queue,
                    session,
                    rate_limiter,
                    args,
                    base_dir,
                    fail_log_path,
                    counter,
                    counter_lock,
                )
            )
            for _ in range(args.concurrency)
        ]

        try:
            for chamber in chamber_values:
                page = args.start_page
                seen = 0

                # Initialize detailed search for this chamber
                try:
                    init_payload = build_payload(args, page, chamber)
                    async with session.post(
                        f"{BASE_URL}/detayliArama",
                        json={"data": init_payload},
                        headers=HEADERS,
                        timeout=aiohttp.ClientTimeout(total=20),
                    ):
                        pass
                except Exception:
                    pass

                while True:
                    payload = build_payload(args, page, chamber)
                    try:
                        rows, total, _ = await fetch_page(
                            session, payload, rate_limiter, args.retries, args.retry_wait
                        )
                    except Exception as exc:
                        print(f"[page-fail] page={page} chamber={chamber} -> {exc}")
                        break

                    if not rows:
                        break

                    print(
                        f"[page {page}] {len(rows)} kayıt, toplam: {total}, "
                        f"delay: {rate_limiter.current_delay:.2f}s"
                    )

                    # Filter and queue downloads
                    for row in rows:
                        doc_id = row.get("id")
                        if not doc_id:
                            continue
                        if doc_id in existing_ids and not args.no_skip_existing:
                            total_skipped += 1
                            continue

                        await queue.put(row)
                        seen += 1

                        if args.max_results and seen >= args.max_results:
                            break

                    if args.max_results and seen >= args.max_results:
                        break

                    page += 1
                    if args.max_pages and page > args.max_pages:
                        break

                    # No extra delay - rate_limiter handles it in fetch_page

            # Wait for queue to be processed
            await queue.join()

        finally:
            # Send poison pills to stop workers
            for _ in workers:
                await queue.put(None)

            # Cancel and wait for workers
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)

    print(
        f"\nTamamlandı. {counter['saved']} indirildi, {total_skipped} atlandı, "
        f"{counter['failed']} başarısız. Çıkış: {base_dir}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emsal Karar Arama toplayıcı (async)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-k",
        "--keyword",
        default="",
        help="Aranacak kelime. Boş bırakılırsa sadece seçili daire/tarih filtresi ile arar.",
    )
    parser.add_argument(
        "--chamber-field",
        default="Bam Hukuk Mahkemeleri",
        choices=["Bam Hukuk Mahkemeleri", "Hukuk Mahkemeleri"],
        help="Seçilecek birim alan adı",
    )
    parser.add_argument(
        "--chambers",
        nargs="*",
        default=[],
        help="Seçilecek birim değerleri",
    )
    parser.add_argument("--page-size", type=int, default=50, help="Sayfa başına kayıt")
    parser.add_argument("--start-page", type=int, default=1, help="Başlangıç sayfa no")
    parser.add_argument("--max-pages", type=int, default=None, help="Maks. sayfa sayısı")
    parser.add_argument("--max-results", type=int, default=None, help="Maks. karar adedi")
    parser.add_argument(
        "--sort-field",
        default="1",
        choices=["1", "2", "3"],
        help="1=Esas No, 2=Karar No, 3=Karar Tarihi",
    )
    parser.add_argument("--sort-dir", default="desc", choices=["asc", "desc"])
    parser.add_argument("--start-date", help="GG.AA.YYYY")
    parser.add_argument("--end-date", help="GG.AA.YYYY")
    parser.add_argument("--out-dir", default="data/emsal_bam", help="Çıktı klasörü")
    parser.add_argument("--plain-text", action="store_true", help="TXT yaz")
    parser.add_argument("--no-html", action="store_true", help="HTML yazma")

    # Async/rate limiting options
    parser.add_argument(
        "--concurrency",
        type=int,
        default=8,
        help="Eşzamanlı doküman indirme sayısı",
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        default=0.1,
        help="İstekler arası minimum bekleme (saniye)",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=2.0,
        help="İstekler arası maksimum bekleme (saniye)",
    )
    parser.add_argument(
        "--pause-duration",
        type=float,
        default=30.0,
        help="429 durumunda başlangıç pause süresi (saniye)",
    )

    parser.add_argument("--retries", type=int, default=6, help="Tekrar deneme sayısı")
    parser.add_argument(
        "--retry-wait", type=float, default=5.0, help="Tekrar deneme arası bekleme"
    )
    parser.add_argument("--fail-log", default="data/emsal_failed_ids.txt")
    parser.add_argument("--no-skip-existing", action="store_true")

    # Backward compatibility (ignored)
    parser.add_argument("--workers", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--sleep", type=float, default=None, help=argparse.SUPPRESS)

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Backward compat: map workers to concurrency if provided
    if args.workers is not None and args.concurrency == 8:
        args.concurrency = args.workers

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
