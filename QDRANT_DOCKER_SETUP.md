# Qdrant Docker Setup (Hetzner AX41-NVMe)

Bu dokuman, Hetzner uzerindeki Docker tabanli Qdrant kurulumunun mevcut durumunu ve tekrar kurulumu anlatir.

## 1) Altyapi Ozeti

- Sunucu: Hetzner Dedicated AX41-NVMe
- IP: 65.21.193.163
- Isletim sistemi: Debian 12 (Bookworm)
- CPU: AMD Ryzen 5 3600 (6 core / 12 thread)
- RAM: 64 GB DDR4
- Disk: 2x 512 GB NVMe SSD (RAID 1 = 476 GB kullanilabilir)
- Qdrant container: `qdrant/qdrant:latest`
- Acik port: `6333/tcp` (HTTP API)

## 2) Sunucu Erisim

- Direkt baglanti: `ssh -i ~/.ssh/hetzner_ml_law root@65.21.193.163`

## 3) Kurulum Dizinleri

Sunucu tarafinda Qdrant dosyalari:

- `/opt/qdrant/docker-compose.yml`
- `/opt/qdrant/storage` (kalici veri)
- `/opt/qdrant/snapshots` (snapshot dosyalari)
- `/opt/qdrant/.env` (Qdrant URL/API key gibi runtime degiskenleri)

## 4) Docker Kurulumu (Sunucu)

```bash
apt-get update
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
docker --version
docker compose version
```

## 5) Qdrant Compose Dosyasi

`/opt/qdrant/docker-compose.yml`:

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: qdrant
    restart: unless-stopped
    ports:
      - "6333:6333"
    environment:
      QDRANT__SERVICE__API_KEY: "${QDRANT_API_KEY}"
    volumes:
      - /opt/qdrant/storage:/qdrant/storage
      - /opt/qdrant/snapshots:/qdrant/snapshots
```

Not:
- `6333` dis erisime aciktir.
- API key'i compose icine plaintext yazmak yerine `.env` dosyasindan almak tercih edilir.

## 6) Qdrant Runtime Env

`/opt/qdrant/.env` (sunucu icinde):

```bash
QDRANT_URL=http://127.0.0.1:6333
QDRANT_API_KEY=...REDACTED...
```

Container env icin iki secenek:
- `docker compose --env-file /opt/qdrant/.env up -d`
- veya compose'ta `env_file` tanimi kullanimi

## 7) Container Isletim Komutlari

```bash
cd /opt/qdrant
docker compose up -d
docker ps
docker logs --tail 100 qdrant
```

Saglik kontrolu:

```bash
source /opt/qdrant/.env
curl -s "$QDRANT_URL/collections" -H "api-key: $QDRANT_API_KEY"
```

## 8) Collection Konfigurasyonu

Olusturulan koleksiyonlar:

- `decisions`
- `user_docs`

Her iki koleksiyonda uygulanan ayarlar:

- `vectors.size = 1536`
- `vectors.distance = Cosine`
- `vectors.on_disk = true`
- `hnsw_config.on_disk = true`
- `quantization_config.scalar.type = int8`
- `quantization_config.scalar.quantile = 0.99`
- `quantization_config.scalar.always_ram = false`

```bash
curl -s "$QDRANT_URL/collections/decisions" \
  -H "api-key: $QDRANT_API_KEY" | jq

curl -s "$QDRANT_URL/collections/user_docs" \
  -H "api-key: $QDRANT_API_KEY" | jq
```

Ornek create komutu:

```bash
curl -s -X PUT "$QDRANT_URL/collections/decisions" \
  -H "api-key: $QDRANT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": { "size": 1536, "distance": "Cosine", "on_disk": true },
    "hnsw_config": { "on_disk": true },
    "quantization_config": { "scalar": { "type": "int8", "quantile": 0.99, "always_ram": false } }
  }'
```

## 9) DRF Uygulamasi ile Entegrasyon

Lokal backend `.env`:

```bash
QDRANT_URL=http://65.21.193.163:6333
QDRANT_API_KEY=...REDACTED...
```

Cloudflare R2 env (dokuman upload pipeline icin):

```bash
R2_ACCOUNT_ID=...
R2_BUCKET_NAME=law-app
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_ENDPOINT_URL=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
```

## 10) Kapasite ve Performans

Mevcut sunucu kapasitesi:

- 64 GB RAM: HNSW index (~4.4 GB) + quantized vektorler (~28.5 GB) tamamen RAM'e sigar
- 476 GB disk (RAID 1): ~19.4M vektor icin ~161-216 GB gerekli, bol alan mevcut
- Beklenen arama latency: 30-100ms (tum quantized vektorler cache'de)

Hedef veri seti:
- 10.8M karar → ~19.4M chunk/vektor
- Scalar INT8 quantization + rescore ile high precision arama

## 11) Guvenlik ve Operasyon Notlari

- API key rotate edilmis olmali; eski key'ler iptal edilmeli.
- SSH sadece key-based kullanilmali.
- Snapshot/backup otomasyonu sonraki adimda zorunlu hale getirilmeli.
- RAID 1 sayesinde disk arizasina karsi koruma mevcut.
