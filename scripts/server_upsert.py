#!/usr/bin/env python3
"""
Sunucu üzerinde çalıştırılacak Qdrant upsert scripti.

Kullanım (sunucuda):
  pip install qdrant-client openai
  python server_upsert.py \
    --registry batch_registry.json \
    --metadata metadata_map.json \
    --openai-api-key sk-... \
    --qdrant-api-key ...

Akış:
  1. batch_registry.json'dan output_file_id'leri oku
  2. OpenAI'dan sonuçları doğrudan indir (sunucu bant genişliği ile)
  3. Qdrant'a upsert et (localhost, hızlı)
  4. --cleanup ile dosyaları sil
"""

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path


def load_checkpoint(checkpoint_path: Path) -> set:
    if checkpoint_path.exists():
        return set(json.loads(checkpoint_path.read_text(encoding="utf-8")))
    return set()


def save_checkpoint(checkpoint_path: Path, processed: set):
    checkpoint_path.write_text(json.dumps(sorted(processed)), encoding="utf-8")


def download_results(registry: dict, results_dir: Path, openai_api_key: str, checkpoint: set):
    """OpenAI'dan batch sonuçlarını indir. Zaten mevcutsa pas geç."""
    results_dir.mkdir(parents=True, exist_ok=True)

    to_download = []
    for batch_name, info in registry.items():
        output_file = results_dir / f"{batch_name}.output.jsonl"
        if output_file.exists():
            continue
        if batch_name in checkpoint:
            continue
        ofid = info.get("output_file_id")
        if not ofid:
            continue
        to_download.append((batch_name, ofid, output_file))

    if not to_download:
        print("[download] Tüm sonuçlar zaten mevcut.")
        return

    from openai import OpenAI
    client = OpenAI(api_key=openai_api_key)

    print(f"[download] {len(to_download)} dosya OpenAI'dan indirilecek...")
    for idx, (name, ofid, out_path) in enumerate(to_download):
        content = client.files.content(ofid)
        out_path.write_bytes(content.read())
        size_mb = out_path.stat().st_size / 1024 / 1024
        print(f"  [{idx+1}/{len(to_download)}] {name} → {size_mb:.1f} MB")

    print("[download] İndirme tamamlandı.")


def upsert_results(results_dir: Path, metadata_map: dict, collection: str,
                   qdrant_url: str, qdrant_api_key: str, batch_size: int,
                   checkpoint_path: Path):
    """Embedding sonuçlarını Qdrant'a yaz."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import PointStruct

    client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)

    collections = [c.name for c in client.get_collections().collections]
    if collection not in collections:
        print(f"HATA: '{collection}' collection bulunamadı!")
        return 0

    processed_files = load_checkpoint(checkpoint_path)
    if processed_files:
        print(f"[upsert] Checkpoint: {len(processed_files)} dosya pas geçilecek.")

    output_files = sorted(results_dir.glob("*.output.jsonl"))
    if not output_files:
        print("HATA: Sonuç dosyası bulunamadı!")
        return 0

    pending = [f for f in output_files if f.name not in processed_files]
    skipped = len(output_files) - len(pending)
    if skipped:
        print(f"[upsert] {skipped} dosya zaten işlenmiş.")
    if not pending:
        print("[upsert] Tüm dosyalar işlenmiş!")
        return 0

    print(f"[upsert] {len(pending)} dosya işlenecek...")

    total_upserted = 0
    total_files = len(pending)

    for file_idx, of in enumerate(pending):
        file_points = 0
        points = []
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

        processed_files.add(of.name)
        save_checkpoint(checkpoint_path, processed_files)
        print(f"  [{file_idx+1}/{total_files}] {of.name}: {file_points:,} → toplam: {total_upserted:,}")

    return total_upserted


def _cleanup(work_dir: Path):
    print("\n[cleanup] Temizlik yapılıyor...")
    resolved = work_dir.resolve()
    for item in list(resolved.iterdir()):
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
        print(f"    {item.name} silindi.")
    print("[cleanup] Tamamlandı.")


def main():
    parser = argparse.ArgumentParser(description="Qdrant Upsert (Server)")
    parser.add_argument("--registry", required=True, help="batch_registry.json dosya yolu")
    parser.add_argument("--metadata", required=True, help="metadata_map.json dosya yolu")
    parser.add_argument("--collection", default="decisions")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--qdrant-api-key", default=None)
    parser.add_argument("--openai-api-key", default=None)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--cleanup", action="store_true", help="Tamamlandıktan sonra tüm dosyaları sil")
    args = parser.parse_args()

    metadata_path = Path(args.metadata)
    registry_path = Path(args.registry)
    work_dir = registry_path.parent
    results_dir = work_dir / "results"
    checkpoint_path = work_dir / "upsert_checkpoint.json"

    if not registry_path.exists():
        print(f"HATA: {registry_path} bulunamadı!")
        return
    if not metadata_path.exists():
        print(f"HATA: {metadata_path} bulunamadı!")
        return

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    openai_key = args.openai_api_key or os.getenv("OPENAI_API_KEY")
    qdrant_key = args.qdrant_api_key or os.getenv("QDRANT_API_KEY")

    print(f"[+] {len(registry)} batch kayıtlı.")

    # 1) OpenAI'dan sonuçları indir
    checkpoint = load_checkpoint(checkpoint_path)
    download_results(registry, results_dir, openai_key, checkpoint)

    # 2) metadata yükle
    print(f"[+] metadata_map.json yükleniyor...")
    metadata_map = json.loads(metadata_path.read_text(encoding="utf-8"))
    print(f"    {len(metadata_map):,} kayıt yüklendi.")

    # 3) Qdrant'a upsert et
    total = upsert_results(results_dir, metadata_map, args.collection,
                           args.qdrant_url, qdrant_key, args.batch_size,
                           checkpoint_path)

    print(f"\n[✓] Tamamlandı: {total:,} vektör Qdrant'a yazıldı.")

    if args.cleanup:
        _cleanup(work_dir)


if __name__ == "__main__":
    main()
