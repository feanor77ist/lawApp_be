"""
Production-ready Embedding Pipeline for Karar Veritabanı.

README §7 spesifikasyonlarına uygun:
  - Model: text-embedding-3-small (1536 dim)
  - Chunking: ~1000 token hedef, 200 overlap
  - Batch API: max 50K request/file, max 200MB/file
  - Qdrant decisions collection: cosine, 1536 dim

Batch Boyutu Stratejisi (Tier 3 - 100M enqueued token limiti):
  ┌─────────────────┬──────────────┬─────────────┬────────────────────────────────┐
  │ Batch boyutu    │ Paralel batch│ Toplam batch│ Notlar                         │
  ├─────────────────┼──────────────┼─────────────┼────────────────────────────────┤
  │ 50M tok (~50K)  │ 2            │ ~280        │ Az dosya ama düşük paralellik  │
  │ 10M tok (~10K)  │ 10           │ ~1.400      │ ÖNERİLEN: iyi denge            │
  │ 2.8M tok (~3K)  │ 35           │ ~5.000      │ Tier 1 için uygun              │
  └─────────────────┴──────────────┴─────────────┴────────────────────────────────┘

  Yargıtay kararları (decision_contents): 9.8M karar → ~13.9M chunk → ~13.9B token
    - MAX_TOKENS_PER_BATCH = 10_000_000 (10M)
    - ~1.400 batch dosyası, 10 tanesi paralel işlenir
    - Tahmini maliyet: ~$140 (batch %50 indirimli, $0.01/1M token)
    - Tahmini süre: 2-3 gün (OpenAI işleme + indirme + upsert)

Kullanım:
  # 1) PostgreSQL'den oku, chunk'la ve JSONL batch dosyaları üret
  python scripts/embedding_pipeline.py prepare --table decision_contents --out-dir batches/yargitay

  # 2) Batch dosyalarını OpenAI'a gönder
  python scripts/embedding_pipeline.py submit --batch-dir batches/yargitay

  # 3) Batch durumlarını izle ve sonuçları indir
  python scripts/embedding_pipeline.py poll --batch-dir batches/yargitay

  # 4) Embedding sonuçlarını Qdrant'a yaz (sunucuda çalıştır - hızlı)
  python scripts/embedding_pipeline.py upsert --batch-dir batches/yargitay --remote --cleanup
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import tiktoken

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
CHUNK_TARGET_TOKENS = 1000
CHUNK_OVERLAP_TOKENS = 200
MAX_REQUESTS_PER_BATCH = 50_000
MAX_BYTES_PER_BATCH = 200 * 1024 * 1024  # 200 MB
MAX_ENQUEUED_TOKENS = 100_000_000  # Tier 3: aynı anda kuyrukta max 100M token
MAX_TOKENS_PER_BATCH = 10_000_000  # Tier 3: tek batch dosyasının token üst sınırı
CHECKPOINT_FILE = "checkpoint.json"
BATCH_REGISTRY = "batch_registry.json"

# PostgreSQL bağlantı bilgileri (.env'den yüklenir)
DB_TABLES = {
    "decision_contents": {
        "kaynak": "yargitay",
        "id_col": "id",
        "text_col": "text_content",
        "columns": ["id", "text_content", "daire", "karar_tarihi", "esas_no", "karar_no", "discovered_by_filter"],
    },
    "uyap_decision_contents": {
        "kaynak": "uyap",
        "id_col": "id",
        "text_col": "text_content",
        "columns": ["id", "text_content", "daire", "karar_tarihi", "esas_no", "karar_no", "discovered_by_filter", "durum"],
    },
    "danistay_decision_contents": {
        "kaynak": "danistay",
        "id_col": "id",
        "text_col": "text_content",
        "columns": ["id", "text_content", "daire", "karar_tarihi", "esas_no", "karar_no", "discovered_by_filter"],
    },
    "aym_decision_contents": {
        "kaynak": "aym",
        "id_col": "id",
        "text_col": "text_content",
        "columns": ["id", "text_content", "karar_tarihi", "esas_no", "karar_no", "discovered_by_filter", "karar_turu", "metadata"],
    },
}


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_enc = tiktoken.encoding_for_model(EMBEDDING_MODEL)


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def chunk_text(text: str, target: int = CHUNK_TARGET_TOKENS, overlap: int = CHUNK_OVERLAP_TOKENS) -> list[str]:
    """Token-bazlı chunking. Her chunk ≤ target token, komşu chunk'lar overlap kadar örtüşür."""
    tokens = _enc.encode(text)
    if len(tokens) <= target:
        return [text]

    chunks = []
    start = 0
    step = target - overlap
    while start < len(tokens):
        end = min(start + target, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(_enc.decode(chunk_tokens))
        if end >= len(tokens):
            break
        start += step
    return chunks


# ---------------------------------------------------------------------------
# PREPARE — PostgreSQL'den oku, chunk'la ve JSONL batch dosyaları üret
# ---------------------------------------------------------------------------

def cmd_prepare(args):
    import psycopg2
    
    table = args.table
    if table not in DB_TABLES:
        print(f"[prepare] HATA: Bilinmeyen tablo '{table}'. Desteklenen: {list(DB_TABLES.keys())}")
        return
    
    table_config = DB_TABLES[table]
    kaynak = table_config["kaynak"]
    text_col = table_config["text_col"]
    columns = table_config["columns"]
    
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_path = out_dir / CHECKPOINT_FILE
    processed_ids = set()
    if checkpoint_path.exists():
        processed_ids = set(json.loads(checkpoint_path.read_text()))
        print(f"[checkpoint] {len(processed_ids)} kayıt zaten işlenmiş, kaldığı yerden devam ediyor.")

    _load_env()
    db_config = {
        "host": os.getenv("KARAR_DB_HOST", "localhost"),
        "port": os.getenv("KARAR_DB_PORT", "5432"),
        "dbname": os.getenv("KARAR_DB_NAME", "karar_db"),
        "user": os.getenv("KARAR_DB_USER", os.getenv("DB_USER", "ardaarli")),
        "password": os.getenv("KARAR_DB_PASSWORD", os.getenv("DB_PASSWORD", "")),
    }
    
    print(f"[prepare] Tablo: {table} (kaynak: {kaynak})")
    print(f"[prepare] DB: {db_config['host']}:{db_config['port']}/{db_config['dbname']}")
    
    conn = psycopg2.connect(**db_config)
    cursor = conn.cursor(name="embedding_cursor")
    cursor.itersize = 10000
    
    # Toplam kayıt sayısı
    with conn.cursor() as count_cur:
        count_cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {text_col} IS NOT NULL AND {text_col} != ''")
        total_records = count_cur.fetchone()[0]
    print(f"[prepare] Toplam kayıt: {total_records:,}")
    
    # Ana sorgu
    col_str = ", ".join(columns)
    limit_clause = f" LIMIT {args.limit}" if args.limit else ""
    cursor.execute(f"SELECT {col_str} FROM {table} WHERE {text_col} IS NOT NULL AND {text_col} != '' ORDER BY id{limit_clause}")

    batch_idx = 0
    request_count = 0
    byte_count = 0
    batch_token_count = 0
    current_batch_lines: list[str] = []
    total_chunks = 0
    total_tokens = 0
    newly_processed: list[str] = []
    metadata_map = {}
    processed_count = 0
    skipped_count = 0

    def flush_batch():
        nonlocal batch_idx, request_count, byte_count, batch_token_count, current_batch_lines
        if not current_batch_lines:
            return
        batch_file = out_dir / f"batch_{batch_idx:04d}.jsonl"
        batch_file.write_text("\n".join(current_batch_lines) + "\n", encoding="utf-8")
        print(f"  [batch_{batch_idx:04d}.jsonl] {request_count} request, "
              f"{batch_token_count:,} token, {byte_count / 1024 / 1024:.1f} MB")
        batch_idx += 1
        request_count = 0
        byte_count = 0
        batch_token_count = 0
        current_batch_lines = []

    for row in cursor:
        row_dict = dict(zip(columns, row))
        file_id = str(row_dict["id"])
        
        if file_id in processed_ids:
            skipped_count += 1
            continue
        
        text = row_dict.get(text_col, "") or ""
        text = text.strip()
        if not text:
            skipped_count += 1
            continue
        
        processed_count += 1
        
        # Tarih formatı: dd.MM.yyyy -> ISO 8601
        tarih_raw = row_dict.get("karar_tarihi", "") or ""
        tarih_iso = None
        if tarih_raw and tarih_raw != "-":
            try:
                parts = tarih_raw.split(".")
                if len(parts) == 3:
                    tarih_iso = f"{parts[2]}-{parts[1]}-{parts[0]}T00:00:00Z"
            except Exception:
                pass
        
        # AYM için metadata'dan basvuru_no ve basvuru_tarihi çek
        extra_fields = {}
        if kaynak == "aym" and "metadata" in row_dict and row_dict["metadata"]:
            try:
                meta = row_dict["metadata"] if isinstance(row_dict["metadata"], dict) else json.loads(row_dict["metadata"])
                if meta.get("basvuru_no"):
                    extra_fields["basvuru_no"] = meta["basvuru_no"]
                if meta.get("basvuru_tarihi"):
                    extra_fields["basvuru_tarihi"] = meta["basvuru_tarihi"]
            except Exception:
                pass
        
        # Metadata map'e kaydet
        metadata_map[file_id] = {
            "kaynak": kaynak,
            "daire": row_dict.get("daire", "") or "",
            "tarih": tarih_iso,
            "esas_no": row_dict.get("esas_no", "") or "",
            "karar_no": row_dict.get("karar_no", "") or "",
            "discovered_by_filter": row_dict.get("discovered_by_filter", "") or "",
            **extra_fields,
        }
        
        # UYAP için durum alanı
        if kaynak == "uyap" and row_dict.get("durum"):
            metadata_map[file_id]["durum"] = row_dict["durum"]

        chunks = chunk_text(text)

        for chunk_i, chunk in enumerate(chunks):
            chunk_tokens = count_tokens(chunk)
            record = {
                "custom_id": f"{file_id}-chunk-{chunk_i}",
                "method": "POST",
                "url": "/v1/embeddings",
                "body": {
                    "model": EMBEDDING_MODEL,
                    "input": chunk,
                    "encoding_format": "float",
                },
            }
            line = json.dumps(record, ensure_ascii=False)
            line_bytes = len(line.encode("utf-8"))

            needs_flush = (
                (request_count >= MAX_REQUESTS_PER_BATCH)
                or (byte_count + line_bytes > MAX_BYTES_PER_BATCH)
                or (batch_token_count + chunk_tokens > MAX_TOKENS_PER_BATCH)
            )
            if needs_flush:
                flush_batch()

            current_batch_lines.append(line)
            request_count += 1
            byte_count += line_bytes
            batch_token_count += chunk_tokens
            total_chunks += 1
            total_tokens += chunk_tokens

        newly_processed.append(file_id)

        if len(newly_processed) % 50000 == 0:
            all_processed = list(processed_ids | set(newly_processed))
            checkpoint_path.write_text(json.dumps(all_processed))
            (out_dir / "metadata_map.json").write_text(
                json.dumps(metadata_map, ensure_ascii=False), encoding="utf-8"
            )
            print(f"  [checkpoint] {len(all_processed):,} kayıt, {total_chunks:,} chunk, {batch_idx} batch")

    flush_batch()

    cursor.close()
    conn.close()

    all_processed = list(processed_ids | set(newly_processed))
    checkpoint_path.write_text(json.dumps(all_processed))
    (out_dir / "metadata_map.json").write_text(
        json.dumps(metadata_map, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\n[prepare] Tamamlandı:")
    print(f"  Kayıt: {processed_count:,} yeni + {len(processed_ids):,} önceki = {len(all_processed):,} toplam")
    print(f"  Atlanan: {skipped_count:,}")
    print(f"  Chunk: {total_chunks:,}")
    print(f"  Token: {total_tokens:,}")
    print(f"  Batch dosyası: {batch_idx}")
    print(f"  Tahmini maliyet: ${total_tokens * 0.02 / 1_000_000 * 0.5:.2f} (batch %50 indirimli)")


# ---------------------------------------------------------------------------
# SUBMIT — JSONL dosyalarını OpenAI'a yükle ve batch oluştur
# ---------------------------------------------------------------------------

def cmd_submit(args):
    """
    Batch dosyalarını toplu gönderir; enqueued token limiti dolunca otomatik bekler.
    Kuyrukta yer açıldığında gönderime devam eder. PC açık olmalı ama
    hepsi gönderilince (tüm batch'ler kuyruğa girince) kapatılabilir.
    """
    from openai import OpenAI
    client = OpenAI(api_key=_get_api_key())
    batch_dir = Path(args.batch_dir)
    registry_path = batch_dir / BATCH_REGISTRY
    poll_interval = args.poll_interval

    registry = {}
    if registry_path.exists():
        registry = json.loads(registry_path.read_text())

    jsonl_files = sorted(batch_dir.glob("batch_*.jsonl"))
    pending = []
    for jf in jsonl_files:
        if jf.name in registry and registry[jf.name].get("status") not in ("failed", "expired", "cancelled"):
            print(f"  [{jf.name}] zaten gönderilmiş (batch_id: {registry[jf.name]['batch_id']}), atlanıyor.")
            continue
        pending.append(jf)

    print(f"[submit] {len(pending)} batch gönderilecek (toplam {len(jsonl_files)} dosya).")
    if not pending:
        print("[submit] Gönderilecek batch yok.")
        return

    idx = 0
    while idx < len(pending):
        jf = pending[idx]
        print(f"\n--- [{idx+1}/{len(pending)}] {jf.name} ---")
        print(f"  Yükleniyor...")
        with open(jf, "rb") as f:
            file_obj = client.files.create(file=f, purpose="batch")

        print(f"  Batch oluşturuluyor (file_id: {file_obj.id})...")
        try:
            batch = client.batches.create(
                input_file_id=file_obj.id,
                endpoint="/v1/embeddings",
                completion_window="24h",
            )
        except Exception as e:
            err_msg = str(e)
            if "token_limit_exceeded" in err_msg or "enqueued" in err_msg.lower():
                print(f"  ⏳ Kuyruk dolu, tamamlanan batch bekleniyor...")
                _wait_for_any_in_progress(client, registry, registry_path, poll_interval)
                print(f"  Kuyrukta yer açıldı, tekrar deneniyor...")
                continue
            else:
                raise

        registry[jf.name] = {
            "batch_id": batch.id,
            "file_id": file_obj.id,
            "status": batch.status,
            "output_file_id": None,
            "error_file_id": None,
        }
        registry_path.write_text(json.dumps(registry, indent=2))
        print(f"  batch_id: {batch.id}, status: {batch.status}")
        idx += 1

    print(f"\n[submit] Tüm batch'ler gönderildi ({len(pending)} adet).")
    print(f"  Sonuçları indirmek için: python scripts/embedding_pipeline.py poll --batch-dir {batch_dir}")


def _wait_for_any_in_progress(client, registry, registry_path, interval=60):
    """Kuyrukta yer açılana kadar in_progress batch'lerden birinin bitmesini bekler."""
    while True:
        time.sleep(interval)
        for fname, info in registry.items():
            if info["status"] not in ("validating", "in_progress", "finalizing"):
                continue
            batch = client.batches.retrieve(info["batch_id"])
            info["status"] = batch.status
            counts = batch.request_counts
            print(f"    [{fname}] {batch.status} "
                  f"(completed: {counts.completed}/{counts.total}, failed: {counts.failed})")

            if batch.status == "completed":
                if batch.output_file_id:
                    info["output_file_id"] = batch.output_file_id
                if batch.error_file_id:
                    info["error_file_id"] = batch.error_file_id
                registry_path.write_text(json.dumps(registry, indent=2))
                return

            if batch.status in ("failed", "expired", "cancelled"):
                if batch.error_file_id:
                    info["error_file_id"] = batch.error_file_id
                registry_path.write_text(json.dumps(registry, indent=2))
                return

        registry_path.write_text(json.dumps(registry, indent=2))


# ---------------------------------------------------------------------------
# POLL — Batch durumlarını izle, bitince sonuçları indir
# ---------------------------------------------------------------------------

def cmd_poll(args):
    from openai import OpenAI
    client = OpenAI(api_key=_get_api_key())
    batch_dir = Path(args.batch_dir)
    registry_path = batch_dir / BATCH_REGISTRY
    results_dir = batch_dir / "results"
    results_dir.mkdir(exist_ok=True)

    if not registry_path.exists():
        print("[poll] Kayıt dosyası yok. Önce 'submit' çalıştırın.")
        return

    registry = json.loads(registry_path.read_text())
    interval = args.interval

    # Önce: completed ama sonuç dosyası indirilmemiş batch'leri indir
    for fname, info in registry.items():
        if info["status"] == "completed" and info.get("output_file_id"):
            out_path = results_dir / f"{fname}.output.jsonl"
            if not out_path.exists():
                print(f"  [{fname}] sonuç dosyası eksik, indiriliyor...")
                content = client.files.content(info["output_file_id"])
                out_path.write_text(content.text, encoding="utf-8")
                print(f"    → indirildi: {out_path}")

    while True:
        all_done = True
        for fname, info in registry.items():
            if info["status"] in ("completed", "failed", "expired", "cancelled"):
                continue
            all_done = False

            batch = client.batches.retrieve(info["batch_id"])
            info["status"] = batch.status
            counts = batch.request_counts
            print(f"  [{fname}] status: {batch.status} "
                  f"(completed: {counts.completed}/{counts.total}, failed: {counts.failed})")

            if batch.status == "completed":
                if batch.output_file_id:
                    info["output_file_id"] = batch.output_file_id
                    out_path = results_dir / f"{fname}.output.jsonl"
                    if not out_path.exists():
                        content = client.files.content(batch.output_file_id)
                        out_path.write_text(content.text, encoding="utf-8")
                        print(f"    → sonuç indirildi: {out_path}")

                if batch.error_file_id:
                    info["error_file_id"] = batch.error_file_id
                    err_path = results_dir / f"{fname}.errors.jsonl"
                    if not err_path.exists():
                        content = client.files.content(batch.error_file_id)
                        err_path.write_text(content.text, encoding="utf-8")
                        print(f"    → hatalar indirildi: {err_path}")

            elif batch.status in ("failed", "expired", "cancelled"):
                print(f"    → batch {batch.status}!")
                if batch.error_file_id:
                    info["error_file_id"] = batch.error_file_id

        registry_path.write_text(json.dumps(registry, indent=2))

        if all_done:
            print("\n[poll] Tüm batch'ler tamamlandı.")
            break

        print(f"\n  Bekleniyor ({interval}s)...\n")
        time.sleep(interval)


# ---------------------------------------------------------------------------
# UPSERT — Embedding sonuçlarını Qdrant'a yaz
# ---------------------------------------------------------------------------

def cmd_upsert(args):
    """
    Embedding sonuçlarını Qdrant'a yazar.
    --remote ile dosyaları sunucuya yükler ve orada çalıştırır (hızlı).
    --remote olmadan lokal'den bağlanır (yavaş, network latency).
    """
    if args.remote:
        _upsert_remote(args)
    else:
        _upsert_local(args)


def _upsert_remote(args):
    """Küçük dosyaları sunucuya yükle, sonuçları sunucunun OpenAI'dan indirmesini sağla, upsert yap."""
    import subprocess

    batch_dir = Path(args.batch_dir)
    metadata_map_path = batch_dir / "metadata_map.json"
    registry_path = batch_dir / "batch_registry.json"
    server_script = Path(__file__).parent / "server_upsert.py"

    if not registry_path.exists():
        print("[upsert] batch_registry.json bulunamadı. Önce 'submit' çalıştırın.")
        return
    if not metadata_map_path.exists():
        print("[upsert] metadata_map.json bulunamadı. Önce 'prepare' çalıştırın.")
        return
    if not server_script.exists():
        print("[upsert] server_upsert.py bulunamadı!")
        return

    _load_env()
    qdrant_url = args.qdrant_url or os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_api_key = args.qdrant_api_key or os.getenv("QDRANT_API_KEY", "")
    openai_api_key = _get_api_key()
    ssh_key = args.ssh_key or os.getenv("HETZNER_SSH_KEY", str(Path.home() / ".ssh" / "hetzner_ml_law"))

    import re
    match = re.search(r"https?://([^:/]+)", qdrant_url)
    if not match:
        print(f"[upsert] QDRANT_URL parse edilemedi: {qdrant_url}")
        return
    server_host = match.group(1)
    if server_host in ("localhost", "127.0.0.1"):
        print("[upsert] QDRANT_URL localhost, --remote kullanılamaz.")
        return

    ssh_target = f"root@{server_host}"
    ssh_opts = ["-i", ssh_key]
    remote_dir = "/opt/qdrant/upsert_data"

    meta_size = metadata_map_path.stat().st_size / 1024 / 1024
    reg_size = registry_path.stat().st_size / 1024
    print(f"[upsert] Sunucu: {ssh_target}")
    print(f"[upsert] Transfer: metadata ({meta_size:.0f} MB) + registry ({reg_size:.0f} KB) + script")
    print(f"         Sonuçlar sunucu tarafından OpenAI'dan indirilecek")

    print("\n[1/3] Dosyalar sunucuya yükleniyor...")
    subprocess.run(["ssh", *ssh_opts, ssh_target, f"mkdir -p {remote_dir}"], check=True)
    subprocess.run(["scp", *ssh_opts, str(server_script), str(metadata_map_path), str(registry_path),
                     f"{ssh_target}:{remote_dir}/"], check=True)

    print("[2/3] Sunucuda venv + bağımlılıklar kuruluyor...")
    venv_dir = f"{remote_dir}/venv"
    setup_cmd = (
        f"apt-get install -y -qq python3-venv > /dev/null 2>&1; "
        f"test -d {venv_dir} || python3 -m venv {venv_dir}; "
        f"{venv_dir}/bin/pip install -q qdrant-client openai"
    )
    subprocess.run(["ssh", *ssh_opts, ssh_target, setup_cmd], check=True)

    print("[3/3] Sunucuda indirme + upsert başlatılıyor...")
    cleanup_flag = "--cleanup" if args.cleanup else ""
    remote_cmd = (
        f"cd {remote_dir} && {venv_dir}/bin/python server_upsert.py"
        f" --registry ./batch_registry.json"
        f" --metadata ./metadata_map.json"
        f" --collection {args.collection}"
        f" --openai-api-key '{openai_api_key}'"
        f" --qdrant-api-key '{qdrant_api_key}'"
        f" --batch-size {args.upsert_batch_size}"
        f" {cleanup_flag}"
    )
    subprocess.run(["ssh", *ssh_opts, "-t", ssh_target, remote_cmd], check=True)

    print("\n[upsert] Tamamlandı!")


def _upsert_local(args):
    """Lokal'den Qdrant'a bağlanarak upsert yap (yavaş)."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct
    import hashlib

    batch_dir = Path(args.batch_dir)
    results_dir = batch_dir / "results"
    metadata_map_path = batch_dir / "metadata_map.json"

    if not metadata_map_path.exists():
        print("[upsert] metadata_map.json bulunamadı. Önce 'prepare' çalıştırın.")
        return

    metadata_map = json.loads(metadata_map_path.read_text(encoding="utf-8"))

    _load_env()
    qdrant_url = args.qdrant_url or os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_api_key = args.qdrant_api_key or os.getenv("QDRANT_API_KEY")
    collection = args.collection

    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)

    collections = [c.name for c in client.get_collections().collections]
    if collection not in collections:
        print(f"[upsert] HATA: '{collection}' collection bulunamadı!")
        return
    else:
        print(f"[upsert] '{collection}' collection mevcut, upsert başlıyor...")
        print(f"  (Lokal mod - yavaş olabilir, --remote önerilir)")

    output_files = sorted(results_dir.glob("*.output.jsonl"))
    if not output_files:
        print("[upsert] Sonuç dosyası bulunamadı. Önce 'poll' çalıştırın.")
        return

    batch_size = args.upsert_batch_size
    total_upserted = 0
    total_files = len(output_files)

    for file_idx, of in enumerate(output_files):
        file_points = 0
        points: list[PointStruct] = []
        lines = of.read_text(encoding="utf-8").strip().split("\n")

        for line in lines:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("error"):
                continue

            custom_id = record["custom_id"]
            id_parts = custom_id.rsplit("-chunk-", 1)
            file_id = id_parts[0]
            chunk_index = int(id_parts[1]) if len(id_parts) > 1 else 0

            embedding = record["response"]["body"]["data"][0]["embedding"]
            meta = metadata_map.get(file_id, {})

            payload = {
                "file_key": file_id,
                "kaynak": meta.get("kaynak", ""),
                "daire": meta.get("daire", ""),
                "tarih": meta.get("tarih"),
                "esas_no": meta.get("esas_no", ""),
                "karar_no": meta.get("karar_no", ""),
                "chunk_index": chunk_index,
                "discovered_by_filter": meta.get("discovered_by_filter", ""),
            }
            
            # Ek alanlar (varsa)
            for extra_key in ["durum", "basvuru_no", "basvuru_tarihi"]:
                if meta.get(extra_key):
                    payload[extra_key] = meta[extra_key]

            point_id = int(hashlib.sha256(custom_id.encode()).hexdigest()[:16], 16)
            points.append(PointStruct(id=point_id, vector=embedding, payload=payload))

            if len(points) >= batch_size:
                client.upsert(collection_name=collection, points=points, wait=False)
                file_points += len(points)
                total_upserted += len(points)
                points = []

        if points:
            client.upsert(collection_name=collection, points=points, wait=False)
            file_points += len(points)
            total_upserted += len(points)

        print(f"  [{file_idx+1}/{total_files}] {of.name}: {file_points:,} → toplam: {total_upserted:,}")

    print(f"\n[upsert] Toplam {total_upserted:,} vektör Qdrant'a yazıldı.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_env():
    """ml_simulator/.env dosyasından ortam değişkenlerini yükler."""
    env_path = Path(__file__).resolve().parent.parent / "ml_simulator" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                if key not in os.environ:
                    os.environ[key] = val.strip()


def _get_api_key() -> str:
    _load_env()
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        print("OPENAI_API_KEY bulunamadı. .env dosyasını veya ortam değişkenini kontrol edin.")
        sys.exit(1)
    return key


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Karar Embedding Pipeline")
    sub = parser.add_subparsers(dest="command")

    # prepare
    p_prepare = sub.add_parser("prepare", help="PostgreSQL'den oku, chunk'la ve JSONL batch dosyaları üret")
    p_prepare.add_argument("--table", required=True, choices=list(DB_TABLES.keys()),
                           help="PostgreSQL tablo adı")
    p_prepare.add_argument("--out-dir", default="batch_files", help="Çıktı dizini (varsayılan: batch_files)")
    p_prepare.add_argument("--limit", type=int, default=None, help="İşlenecek maksimum kayıt sayısı (test için)")

    # submit
    p_submit = sub.add_parser("submit", help="Batch dosyalarını OpenAI'a gönder")
    p_submit.add_argument("--batch-dir", default="batch_files", help="JSONL batch dosyalarının dizini")
    p_submit.add_argument("--poll-interval", type=int, default=60, help="Kuyruk dolduğunda bekleme kontrol aralığı (saniye)")

    # poll
    p_poll = sub.add_parser("poll", help="Batch durumlarını izle ve sonuçları indir")
    p_poll.add_argument("--batch-dir", default="batch_files", help="Batch dosyalarının dizini")
    p_poll.add_argument("--interval", type=int, default=60, help="Kontrol aralığı (saniye, varsayılan: 60)")

    # upsert
    p_upsert = sub.add_parser("upsert", help="Embedding sonuçlarını Qdrant'a yaz")
    p_upsert.add_argument("--batch-dir", default="batch_files", help="Batch dosyalarının dizini")
    p_upsert.add_argument("--collection", default="decisions", help="Qdrant collection adı")
    p_upsert.add_argument("--qdrant-url", default=None, help="Qdrant URL (varsayılan: QDRANT_URL env)")
    p_upsert.add_argument("--qdrant-api-key", default=None, help="Qdrant API key (varsayılan: QDRANT_API_KEY env)")
    p_upsert.add_argument("--upsert-batch-size", type=int, default=500, help="Qdrant upsert batch boyutu (varsayılan: 500)")
    p_upsert.add_argument("--remote", action="store_true", help="Dosyaları sunucuya yükle ve orada çalıştır (hızlı)")
    p_upsert.add_argument("--cleanup", action="store_true", help="Upsert sonrası sunucudaki dosyaları sil")
    p_upsert.add_argument("--ssh-key", default=None, help="SSH key dosyası (varsayılan: ~/.ssh/hetzner_ml_law)")

    args = parser.parse_args()

    if args.command == "prepare":
        cmd_prepare(args)
    elif args.command == "submit":
        cmd_submit(args)
    elif args.command == "poll":
        cmd_poll(args)
    elif args.command == "upsert":
        cmd_upsert(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
