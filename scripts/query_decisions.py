#!/usr/bin/env python3
"""
Qdrant decisions collection üzerinde vektör sorgusu testi.
Chunk metinleri batch JSONL dosyalarından okunup gösterilir.

Kullanım:
  python scripts/query_decisions.py "iş sözleşmesi feshi tazminat"
  python scripts/query_decisions.py "kira sözleşmesi feshi" --top 5 --batch-dir batch_files_pilot
  python scripts/query_decisions.py   # varsayılan örnek sorgu
"""

import argparse
import json
import os
import sys
from pathlib import Path

# .env yükle
_env_path = Path(__file__).resolve().parent.parent / "ml_simulator" / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            if key not in os.environ:
                os.environ[key] = val.strip()

from openai import OpenAI
from qdrant_client import QdrantClient


def load_chunk_texts(batch_dir: Path, custom_ids: set[str]) -> dict[str, str]:
    """Batch JSONL dosyalarından custom_id'ye göre chunk metinlerini yükle."""
    texts = {}
    batch_files = sorted(batch_dir.glob("batch_*.jsonl"))
    for bf in batch_files:
        if len(texts) >= len(custom_ids):
            break
        for line in bf.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                cid = obj.get("custom_id")
                if cid in custom_ids:
                    body = obj.get("body") or obj
                    text = body.get("input", "")
                    texts[cid] = text
                    if len(texts) >= len(custom_ids):
                        break
            except (json.JSONDecodeError, TypeError):
                continue
    return texts


def main():
    parser = argparse.ArgumentParser(description="Decisions collection vektör sorgusu")
    parser.add_argument("query", nargs="?", default="iş sözleşmesi feshi tazminat", help="Arama metni")
    parser.add_argument("--top", type=int, default=5, help="Döndürülecek sonuç sayısı (varsayılan: 5)")
    parser.add_argument("--batch-dir", default="batch_files_pilot", help="Batch JSONL dosyalarının dizini (chunk metni için)")
    parser.add_argument("--collection", default="decisions")
    parser.add_argument("--qdrant-url", default=None)
    parser.add_argument("--qdrant-api-key", default=None)
    parser.add_argument("--text-limit", type=int, default=600, help="Chunk metninde gösterilecek max karakter (0=sınırsız)")
    args = parser.parse_args()

    qdrant_url = args.qdrant_url or os.getenv("QDRANT_URL", "http://localhost:6333")
    qdrant_api_key = args.qdrant_api_key or os.getenv("QDRANT_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not openai_key:
        print("OPENAI_API_KEY bulunamadı. ml_simulator/.env kontrol edin.")
        sys.exit(1)

    print(f"Sorgu: \"{args.query}\"")
    print(f"Top: {args.top}")
    print()

    # 1) Sorguyu embed et
    client_openai = OpenAI(api_key=openai_key)
    resp = client_openai.embeddings.create(
        model="text-embedding-3-small",
        input=args.query,
    )
    query_vector = resp.data[0].embedding

    # 2) Qdrant'ta ara (query_points API)
    client_qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    response = client_qdrant.query_points(
        collection_name=args.collection,
        query=query_vector,
        limit=args.top,
        with_payload=True,
    )
    results = response.points or []

    # 3) Chunk metinlerini batch dosyalarından yükle
    batch_dir = Path(args.batch_dir)
    custom_ids = set()
    for hit in results:
        p = hit.payload or {}
        fk = p.get("file_key")
        ci = p.get("chunk_index", 0)
        if fk is not None:
            custom_ids.add(f"{fk}-chunk-{ci}")
    chunk_texts = {}
    if batch_dir.exists() and custom_ids:
        chunk_texts = load_chunk_texts(batch_dir, custom_ids)

    # 4) Sonuçları yazdır (metadata + chunk metni)
    print(f"Bulunan: {len(results)} sonuç\n")
    for i, hit in enumerate(results, 1):
        payload = hit.payload or {}
        score = getattr(hit, "score", None) or 0
        fk = payload.get("file_key")
        ci = payload.get("chunk_index", 0)
        custom_id = f"{fk}-chunk-{ci}" if fk is not None else None
        text = chunk_texts.get(custom_id, "") if custom_id else ""

        print(f"--- Sonuç {i} (score: {score:.4f}) ---")
        print(f"  file_key:    {payload.get('file_key', '-')}")
        print(f"  daire:       {payload.get('daire', '-')}")
        print(f"  tarih:       {payload.get('tarih', '-')}")
        print(f"  esas_no:     {payload.get('esas_no', '-')}")
        print(f"  karar_no:    {payload.get('karar_no', '-')}")
        print(f"  chunk_index: {payload.get('chunk_index', '-')}")
        if text:
            display = text if (args.text_limit <= 0 or len(text) <= args.text_limit) else text[: args.text_limit] + "…"
            print(f"  chunk_metni:\n    {display.replace(chr(10), chr(10) + '    ')}")
        else:
            print(f"  chunk_metni: (batch-dir yok veya bulunamadı: {args.batch_dir})")
        print()

    print("Sorgu tamamlandı.")


if __name__ == "__main__":
    main()
