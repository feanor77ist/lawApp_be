# AI Destekli Hukuki Asistan Uygulaması — Tasarım / Teknik Spesifikasyon

Bu doküman; hukuk profesyonellerine (avukat, hukuk müşaviri vb.) yönelik **bireysel asistan** işlevleri sunan web uygulamasının hedeflerini, veri modelini ve ana modüllerini tanımlar.

> **Not:** Uygulama tekil kullanıcı bazlıdır (multi-tenant değil). Her kullanıcı kendi verilerine erişir.

---

## 1) Amaç ve Kapsam

Uygulama, kullanıcıların:

- **Karar/İçtihat veritabanı** üzerinden arama & sohbet (retrieval + RAG)
- **Kendi dokümanlarını** yükleyip (sözleşme, dilekçe, pdf/word vb.) arama & sohbet
- **Dava dosyası (case) yönetimi** + **masraf/avans takibi**
- **Takvim / bildirim** entegrasyonları
- (Opsiyonel) **UYAP / E-Tebligat** süreç otomasyonları

yapabileceği bir çalışma ortamı sunar.

---

## 2) Sistem Mimarisi

### 2.1 Mimari Diyagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Render Cloud                             │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐            │
│  │ Django API  │   │   Celery    │   │    Redis    │            │
│  │  (Web Svc)  │   │  (Worker)   │   │  (Queue)    │            │
│  └──────┬──────┘   └──────┬──────┘   └─────────────┘            │
│         │                 │                                     │
│         ▼                 ▼                                     │
│  ┌─────────────────────────────────────────────────────┐        │
│  │           Render PostgreSQL (Ana DB)                │        │
│  │  User, CaseFile, Expense, Document (metadata)       │        │
│  └─────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────┘
         │                        │
         ▼                        ▼
┌─────────────────┐      ┌─────────────────────────┐
│  Cloudflare R2  │      │      Qdrant Db (Hetzner Server)       │
│  ───────────────│      │   ─────────────────────  │
│  - karar .txt   │      │   - decisions collection │
│  - user docs    │      │   - user_docs collection │
│  - JSON metadata│      │   - HNSW + cosine        │
└─────────────────┘      └─────────────────────────┘
```

### 2.2 Depolama Seçimleri


| Bileşen            | Teknoloji                               | Açıklama                                                     |
| ------------------ | --------------------------------------- | ------------------------------------------------------------ |
| **Object Storage** | Cloudflare R2                           | Karar dosyaları (.txt), kullanıcı dokümanları, metadata JSON |
| **Vector Store**   | Qdrant OSS (Self-hosted, Hetzner CCX23) | Embedding'ler (1536 dim), HNSW index, cosine similarity      |
| **Ana Veritabanı** | Render PostgreSQL                       | User, CaseFile, Expense, Document metadata                   |
| **Cache/Queue**    | Redis                                   | Celery task queue, session cache                             |


### 2.3 Uygulama Servisleri


| Servis           | Teknoloji             | Açıklama                                   |
| ---------------- | --------------------- | ------------------------------------------ |
| Backend API      | Django + DRF          | ASGI/Uvicorn, REST endpoints               |
| Worker           | Celery                | Async jobs: embedding, indexleme, bildirim |
| LLM Orkestrasyon | LangChain / LangGraph | RAG pipeline, agent flows                  |
| Deploy           | Render Cloud          | Web service, Postgres, Redis, Worker       |


### 2.4 Embedding Stratejisi


| Parametre      | Değer                           |
| -------------- | ------------------------------- |
| **Model**      | OpenAI `text-embedding-3-small` |
| **Boyut**      | 1536 dim                        |
| **Yöntem**     | OpenAI Batch API                |
| **Maliyet**    | $0.01 / 1M token (batch fiyatı) |
| **Similarity** | Cosine                          |


> **Neden 1536 dim?** Hukuki metinlerde kavram nüansları, istisnalar ve benzer olaylar için yüksek temsil kapasitesi gerekir. 1536 dim ile daha iyi recall elde edilir.

---

## 3) Ana İşlevler

### 3.1 Karar Sorgulama & Asistan Sohbet

- Retrieval: karar metinleri + metadata filtreleme
- RAG: ilgili chunk'lar ile cevap üretimi
- Agents: (opsiyonel) task bazlı akışlar (özet, karşı argüman, emsal bulma, timeline çıkarma)

### 3.1.1 Dilekçe Üretimi / Oluşturma

- Kullanıcı, ilgili dava dosyası veya doküman üstünde chatSession başlatır.
- Chat akışı, RAG + şablonlama ile dilekçe taslağı üretir.
- Kullanıcı düzenleyip indirebilir (PDF/Word).

### 3.2 Kullanıcı Dokümanı Yükleme & Indexleme

- `Document` kaydı `created_by` ile kullanıcıya bağlanır
- Dosya yüklenir (R2)
- Metin çıkarımı (pdf/word → text)
- Chunking (örn: 1000 token hedef, overlap 200)
- Embedding → Qdrant'a yazma
- Bu süreç **async job** olmalı (Celery)

> Not: Signals / `post_save` ile tetikleme opsiyonu var; pratikte "upload sonrası job enqueue" daha kontrollü.

### 3.3 Takvim / Bildirim Entegrasyonu

- Google Calendar entegrasyonu veya agentic node'lar
- Notification işleri (deadline yaklaşıyor, duruşma tarihi, yapılacaklar)

### 3.4 Dava Dosyası CRUD + Takvim Entegrasyonu + Muhasebe

- Dava dosyası kaydı (müvekkil, karşı taraf, esas/karar no, konu, durum)
- Masraf/avans kayıtları (ofis ödedi mi, müvekkile yansıtılacak mı?)
- Bakiye hesaplama: devreden + avans - iade - harcama

### 3.5 (Opsiyonel) UYAP / E-Tebligat Entegrasyonu

- Duruşma/tebligat takibi → otomatik görevler (dosya bazlı checklist)
- Süre hesaplayıcı (HMK/İYUK/CMK farkları, resmi tatil/hafta sonu)
- Hatırlatma + taslak hazırlık akışları

### 3.6 (Opsiyonel) Dönüşüm Paneli

- UDF / Word / PDF dönüşüm paneli (gömülü araç veya servis)

### 3.7 Sözleşme İnceleme

- Doküman upload ederek RAG chain çalıştırma (risk maddeleri, eksik hükümler, özet, öneri)

### 3.8 Agentic İşlevler (LangFlow)

- Google Calendar entegrasyonu, URL agent vb. akışlar LangFlow üzerinde tanımlanır.
- Backend, LangFlow API’leri üzerinden bu agentic akışları tetikler.

---

## 4) Veri Modeli (DB Şeması)

Aşağıdaki modeller; `dava-masraf_tables.xlsx` içeriği ve tasarım dokümanına göre önerilen minimum çekirdektir.

### 4.1 User

- Django `AbstractUser` veya `AbstractBaseUser` extend
- Tekil kullanıcı bazlı sistem (multi-tenant yok)

### 4.2 CaseFile (Dava Dosyası)

XLSX sayfa: `Dosya-kaydı(case)` örneğine göre alanlar:

- `case_id` (UUID) — örn: `CASE-0001`
- `dosya_kodu` (string, opsiyonel) — ofis içi takip
- `dosya_adi` (string)
- `dosya_turu` (enum) — örn: `DAVA`
- `yargi_mercii` / `birim_adi` (string) — örn: "İstanbul 10. İş Mahkemesi"
- `esas_no` (string) — örn: `2026/123 E.`
- `karar_no` (string, nullable)
- `konu_ozeti` (text)
- `durum` (enum) — `ACIK | KAPALI | ASKIDA`
- `acilis_tarihi` (date)
- `kapanis_tarihi` (date, nullable)
- `muvekkil_ad_unvan` (string)
- `karsi_taraf_ad_unvan` (string)
- `para_birimi` (string, default `TRY`)
- `devreden_bakiye` (decimal, default 0) — "önceki dönem" devri

**Güvenlik alanları**

- `created_by` (FK User)
- `created_at`, `updated_at`

> Not: UYAP entegrasyonu varsa `esas_no` genelde benzersizdir; yine de ofis içi `dosya_kodu` ayrı tutulabilir.

### 4.3 Expense (Masraf / Avans Kaydı)

XLSX sayfa: `Masraf_kaydı(expence)` örneğine göre:

- `expense_id` (UUID) — örn: `EXP-0001`
- `case_id` (FK CaseFile)
- `islem_tarihi` (date)
- `islem_tipi` (enum)
  - `MASRAF`
  - `AVANS_ALINDI`
  - `AVANS_IADE`
- `kategori` (string) — masraf türü
- `aciklama` (text)
- `receipt_type` (enum, nullable)
  - `BELGELI`
  - `BELGESIZ`
- `tutar` (decimal)
- `para_birimi` (string, default `TRY`)
- `odeme_yapan` (enum, nullable)
  - `OFIS`
  - `MUVEKKIL`
- `muvekkile_yansit` (bool) — XLSX'te `E/H`

**Güvenlik**

- `created_by` (FK User)
- `created_at`, `updated_at`

### 4.4 Masraf Türü Sözlüğü (ExpenseCategory) — opsiyonel ama önerilir

XLSX sayfa: `Masraf_Kategorileri`

Başlangıç listesi:

- Harç
- Tebligat / Posta (PTT, UETS)
- Bilirkişi / Keşif
- Tanık / Yolluk
- İcra Giderleri (dosya, haciz, satış vb.)
- (İhtiyaca göre genişler)

Alanlar:

- `id` (UUID)
- `name` (unique)
- `is_active` (bool)

### 4.5 Document (Kullanıcı Dokümanı)

- `document_id` (UUID)
- `created_by` (FK User)
- `case` (FK CaseFile, nullable) — doküman bir dosyaya bağlanabilir
- `title`
- `file_url` (R2 path)
- `file_type` (pdf/docx/txt)
- `text_extracted` (bool)
- `indexed` (bool)
- `metadata` (JSON) — sayfa sayısı, kaynak, etiketler vs.
- timestamps

> **Not:** Vektör verileri Qdrant'ta tutulur. PostgreSQL'de `VectorRecord` tablosu gerekmez.

---

## 5) Bakiye Hesaplama Mantığı (Masraf/Avans)

XLSX'teki örnek "BAKİYE HESAPLAMA" kısmına göre:

**Formül:**
`Bakiye = Devreden + Σ(AVANS_ALINDI) − Σ(AVANS_IADE) − Σ(MASRAF)`

Örnek (`CASE-0001`, 2026-02-28'e kadar):

- Devreden: 1000
- Alınan Avans: 3000
- Avans İade: 500
- Harcamalar Toplamı: 1444.90
- Toplam Mevcut (Bakiye): 2055.10

API seviyesinde öneri:

- `GET /cases/{id}/balance?as_of=YYYY-MM-DD`
  - DB'den `<= as_of` filtreli aggregate hesap

---

## 6) API Taslağı (DRF)

### Auth

- `POST /auth/register`
- `POST /auth/login`
- `POST /auth/logout`
- `GET /auth/me`

### CaseFile

- `GET /cases`
- `POST /cases`
- `GET /cases/{case_id}`
- `PATCH /cases/{case_id}`
- `DELETE /cases/{case_id}`

### Expense

- `GET /cases/{case_id}/expenses`
- `POST /cases/{case_id}/expenses`
- `PATCH /expenses/{expense_id}`
- `DELETE /expenses/{expense_id}`

### Balance

- `GET /cases/{case_id}/balance?as_of=2026-02-28`

### Document

- `POST /documents` (multipart upload)
- `GET /documents`
- `GET /documents/{document_id}`
- `DELETE /documents/{document_id}`
- `POST /documents/{document_id}/index` (enqueue job)

### AI / Chat

- `POST /chat`
  - body: `{ mode: "decisions"|"user_docs"|"hybrid", query, filters, case_id? }`
- `POST /decisions/search`
- `POST /documents/search`

---

## 7) Embedding / Indexleme Pipeline

### 7.1 Genel Parametreler


| Parametre       | Değer                    |
| --------------- | ------------------------ |
| Chunking hedef  | ~1000 token              |
| Overlap         | ~200 token               |
| Embedding model | `text-embedding-3-small` |
| Embedding boyut | 1536                     |
| API yöntemi     | OpenAI Batch API         |
| Vector store    | Qdrant Cloud             |


### 7.2 Qdrant Collection Şeması

`**decisions` collection:**

```json
{
  "vectors": {
    "size": 1536,
    "distance": "Cosine"
  },
  "payload_schema": {
    "file_key": "keyword",
    "daire": "keyword",
    "tarih": "datetime",
    "esas_no": "keyword",
    "karar_no": "keyword",
    "chunk_index": "integer"
  }
}
```

`**user_docs` collection:**

```json
{
  "vectors": {
    "size": 1536,
    "distance": "Cosine"
  },
  "payload_schema": {
    "document_id": "keyword",
    "user_id": "keyword",
    "case_id": "keyword",
    "chunk_index": "integer",
    "title": "text"
  }
}
```

### 7.3 Karar Veritabanı Import (Batch Embedding)

**Ölçek:**

- ~12M karar dosyası
- Ortalama ~~10 KB/dosya (~~3000-4000 token)
- Chunking sonrası: ~48M chunk
- Toplam token: ~48B

**Maliyet tahmini:**

- Batch API fiyatı: $0.01 / 1M token
- Toplam: ~$480 (tek seferlik)

**Süre:**

- OpenAI Batch API SLA: 24 saat
- Tipik tamamlanma: 4-12 saat

**Pipeline adımları:**

1. Karar dosyalarını R2'den oku
2. Chunking yap (1000 token, 200 overlap)
3. JSONL batch dosyaları hazırla (her biri max 50K request)
4. OpenAI Batch API'ye yükle
5. Tamamlanınca sonuçları indir
6. Embedding'leri Qdrant'a upsert et
7. Checkpoint tut (hata durumunda devam edebilmek için)

**Örnek batch request formatı:**

```json
{
  "custom_id": "decision-1234567890-chunk-0",
  "method": "POST",
  "url": "/v1/embeddings",
  "body": {
    "model": "text-embedding-3-small",
    "input": "Karar metni chunk içeriği...",
    "encoding_format": "float"
  }
}
```

### 7.4 Kullanıcı Dokümanı Indexleme (Real-time)

Kullanıcı dokümanları için real-time API kullanılır (daha küçük ölçek):

1. Doküman yüklenir → R2'ye kaydet
2. Celery task tetiklenir
3. Metin çıkarımı (pdfplumber / python-docx)
4. Chunking
5. OpenAI embedding API (real-time, küçük batch)
6. Qdrant `user_docs` collection'a upsert
7. Document.indexed = True

---

## 8) UI Modülleri (Minimum)

- Dashboard
  - Son dosyalar
  - Yaklaşan duruşmalar / görevler (takvim entegrasyonu varsa)
- Karar Arama + Chat
  - Filtreler (daire, tarih aralığı, anahtar kelime)
  - Sonuç listesi + seçili karar metni
  - Chat paneli (kaynak gösterimi)
- Dokümanlarım
  - Upload
  - Index durumları
  - Doküman üstünde sohbet
- Dava Dosyaları
  - Liste
  - Dosya detay (özet, taraflar, esas no)
  - Masraf/Avans tablosu
  - Bakiye kartı (as_of seçilebilir)
- Masraf Türleri (admin)
  - Kategori listesi

---

## 9) Yetkilendirme / Veri İzolasyonu

- Tüm `CaseFile`, `Expense`, `Document` kayıtları `created_by` ile kullanıcıya aittir.
- Queryset'ler her zaman `request.user` ile filtrelenmeli.
- Qdrant sorguları `user_id` payload filtresi ile kısıtlanmalı.
- Admin rolü varsa: kategori yönetimi, sistem ayarları.

---

## 10) Maliyet Tahmini (Aylık)


| Bileşen                | Plan                       | Maliyet         |
| ---------------------- | -------------------------- | --------------- |
| Render Web Service     | Starter                    | ~$7             |
| Render Postgres        | Starter                    | ~$7             |
| Render Redis           | Free                       | $0              |
| Render Worker          | Starter                    | ~$7             |
| Cloudflare R2          | 10GB free, sonra $0.015/GB | ~$0-15          |
| Qdrant Cloud           | Free (1GB) / Paid          | $0-35           |
| OpenAI API (chat)      | Kullanıma göre             | ~$10-50         |
| **Toplam (başlangıç)** |                            | **~$30-120/ay** |


**Tek seferlik maliyetler:**

- Karar embedding: ~$480 (OpenAI Batch API)

---

## 11) Geliştirme Fazları

### Faz 0: Altyapı Kurulumu

- Cloudflare R2 bucket oluştur
- Hetzner CCX23 sunucu hazırla (Docker + Qdrant)
- Qdrant collection'ları oluştur (`decisions`, `user_docs`)
- Qdrant collection optimizasyonları (`on_disk` + `scalar int8 quantization`)
- Render ortamı hazırla (web, postgres, redis, worker)
- Env vars yapılandır (`QDRANT_URL`, `QDRANT_API_KEY` lokal backend)

### Faz 1: Karar Veritabanı Pipeline

- Mevcut .txt dosyalarını R2'ye yükle
- Batch embedding pipeline scripti yaz
- Qdrant'a import et
- Search API endpoint (`POST /decisions/search`)

### Faz 2: Kullanıcı Doküman Modülü

- Document model + API
- Metin çıkarımı (pdfplumber / python-docx)
- Indexleme Celery job
- Doküman arama endpoint

### Faz 3: RAG / Chat Modülü

- LangChain retriever (Qdrant)
- Chat endpoint (`POST /chat`)
- Streaming response (SSE)
- Kaynak gösterimi
- WebSocket stream altyapısı (ASGI/uvicorn + `ws/rag/<session_id>/`)

### Faz 4: Dava Dosyası & Masraf Modülü

- CaseFile CRUD
- Expense CRUD
- Balance hesaplama (`GET /cases/{id}/balance?as_of=YYYY-MM-DD`)
- ExpenseCategory seed

### Faz 5: UI / Frontend

- (Ayrı plana bağlı)

---

## 12) Teknik Notlar / TODO

- Storage seçimi: **Cloudflare R2**
- Vector store seçimi: **Qdrant OSS (Self-hosted on Hetzner)**
- Embedding model: **text-embedding-3-small (1536 dim)**
- Embedding yöntemi: **OpenAI Batch API**
- Qdrant deployment: **Hetzner CCX23 + Docker**
- Qdrant erişimi: **public 6333 + API key** (geliştirme fazı)
- Hetzner SSH erişimi (alias): `ssh qdrant-ccx23`
- Hetzner SSH erişimi (direkt): `ssh -i ~/.ssh/hetzner_ml_law root@89.167.99.177`
- Metin çıkarımı kütüphaneleri: pdfplumber, python-docx, unstructured
- Takvim entegrasyonu (Google Calendar) auth akışı
- UYAP/E-tebligat kapsamı (faz-2+)
- Observability: Sentry + structured logs + celery monitoring
- Hybrid search (BM25 + vector) değerlendirmesi
- Reranking (cross-encoder) değerlendirmesi

---

## 13) Referans Dosyalar

- Tasarım dokümanı: `lawApp_design.pages` (preview görseli üzerinden çıkarım)
- Tablo örnekleri: `dava-masraf_tables.xlsx`

