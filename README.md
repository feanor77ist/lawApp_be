# ML Simulator

Kurumsal eğitim senaryolarını gerçekçi diyaloglarla deneyimletmek ve performansını ölçmek için geliştirilmiş Django tabanlı bir platform. REST API, WebSocket (Django Channels) ve LLM tabanlı chatbot bileşeniyle uçtan uca eğitim simülasyonu sağlar.

---

## İçindekiler

1. [Teknoloji Yığını](#teknoloji-yığını)
2. [Genel Mimarî](#genel-mimarî)
3. [Uygulama Bileşenleri](#uygulama-bileşenleri)
4. [Veri Modeli](#veri-modeli)
5. [Chatbot Diyalog Akışı](#chatbot-diyalog-akışı)
6. [REST API Uçları](#rest-api-uçları)
7. [Kurulum ve Çalıştırma](#kurulum-ve-çalıştırma)
8. [Yönetim Paneli](#yönetim-paneli)
9. [Geliştirme / Test Notları](#geliştirme--test-notları)

---

## Teknoloji Yığını

- **Backend:** Django 4.2, Django REST Framework
- **Gerçek Zamanlı:** Django Channels + Redis (Upstash)
- **LLM / RAG:** LangChain, LangGraph, OpenAI API (GPT-4.1 mini, gpt-4o-mini-tts)
- **Veritabanı:** PostgreSQL
- **Önbellekleme:** Redis
- **Depolama:** Django `FileField`/`ImageField` + `documents/` klasörü
- **İletişim:** Token tabanlı kimlik doğrulama, CSRF uyumlu cookie ayarları
- **Dağıtım:** ASGI (uvicorn / gunicorn), Whitenoise ile statik dosya servisleri
- **İstemci yönlendirme:** Backend ana URL’si Vue/React türü frontend’e (`ml-simulator-fe.vercel.app` / `localhost:3000`) yönlendirir.

---

## Genel Mimarî

```
+----------------+      REST / Token     +--------------------------+
|   Frontend     | <-------------------> | Django REST API (my_app) |
| (Next.js vb.)  |                       +--------------------------+
|                | WebSocket / token     | ChatbotAPI & ViewSets    |
|                | <-------------------> |                          |
+----------------+                       |                          |
                                         | Channels (ASGI)          |
                                         +------------+-------------+
                                                      |
                                                      v
                                         +--------------------------+
                                         | ChatConsumer (WebSocket) |
                                         | LangGraph Chatbot        |
                                         +------------+-------------+
                                                      |
                                     Senaryo & KPI    v
                                 +--------------------------+
                                 | PostgreSQL (models.py)   |
                                 |  + documents/ dosyaları  |
                                 +--------------------------+
                                                      |
                                                      v
                                 +--------------------------+
                                 | Redis (Channel layer)    |
                                 +--------------------------+
```

---

## Uygulama Bileşenleri

### `chatbot/`
- `chatbot.py`: LangGraph ile rol oynama (RAG) ve değerlendirme düğümlerini yöneten akış.
  - `rag_chain`: Senaryo bağlamını kullanarak karakter yanıtı üretir.
  - `evaluation_node`: Sohbet kapanırken KPI bazlı değerlendirme raporu üretir, JSON şemasını pydantic ile doğrular.
- `context_utils.py`: Senaryo dokümanlarını (PDF/DOCX) okuyup LangChain `HumanMessage`/`AIMessage` listesi kurar.
- `llm_utils.py`: Kullanılan model kimlikleri (LLM ve embedding).
- `Chatbot` sınıfı:
  - OpenAI Chat modeli için streaming yanıt.
  - Yapay zekâ değerlendirmesi sırasında JSON üretimi ve fallback mekanizması.
  - KPI raporundan `Toplam Puan` hesaplayıp rapor metnini biçimlendirir.

### `my_app/`
- **`models.py`**: Eğitim kurgusunun çekirdeği.
  - `Customer`, `Program` ve `Scenario` ilişkileri.
  - `ProgramScenario`: Ağırlık yüzdesi, yayın/eğitim/kapanış tarihleri ve maksimum deneme sayısı.
  - `TrainingGroup` / `GroupUser`: Katılımcı ilerleme ve toplam skor takibi.
  - `UserEntry`, `UserChatHistory`: Chat oturumu ve mesaj kayıtları.
  - `EvaluationReport`: KPI değerlendirme raporları (pre/post).
- **`views.py`**:
  - ViewSet’ler (Scenario, Customer, Program, Group, GroupUser, ProgramScenario, EvaluationReport).
  - `CustomAuthToken`: E-posta/şifre ile login, token üretimi, müşteri logosu.
  - `UserEntryListAPI`: Kullanıcının entry ve chat geçmişini listeler.
  - `ChatbotAPI`: Yeni sohbet oturumu (entry) açar.
  - `available_scenarios_api`: Yayın ve eğitim tarihine göre aktif/yaklaşan senaryoları hesaplar, deneme hakkı kontrolü yapar.
  - `TextToSpeechAPIView`: Senaryonun TTS ses profilini kullanarak OpenAI TTS API’sinden ses dosyası döndürür.
  - `get_csrf_token`: Safari özelinde cookie ayarlamaları.
- **`consumers.py`** (`ChatConsumer`):
  - Token doğrulamasıyla WebSocket bağlantısı açar (`ws/chat/<entry_id>/?token=...`).
  - Mesajları LangGraph chatbot’a aktarır, streaming yanıtları client’a gönderir.
  - Değerlendirme tamamlanınca `EvaluationReport` kaydeder, entry’yi kilitler (`is_locked`).
  - `UserChatHistory` kayıtlarını günceller, `created_at` zaman damgasını yeniler.
- **`serializers.py`**: DRF modeli serializer’ları; entry için scenario adı ve arka plan görseli URI’si üretir.
- **`signals.py`**:
  - `EvaluationReport` sonrası `GroupUser`/`TrainingGroup` progress hesapları ve ağırlıklı ortalama skor.
  - `ProgramScenario` güncellemelerinde ilgili tüm progress hesaplarını yeniden yapar.
  - `User` kayıtlarında e-posta normalizasyonu ve benzersizlik kontrolleri.
  - Yeni kullanıcılar için otomatik parola sıfırlama e-postası (`registration/welcome_email.html`).
- **`admin.py`**:
  - Gelişmiş admin arayüzleri, filtreler ve inline bileşenler.
  - Program senaryosu ağırlık toplamını doğrulayan formset.
  - Katılımcı ilerleme çubukları, pre/post rapor linkleri, gelişim yüzdesi hesapları.
  - Excel dışa aktarım, müşteri kullanıcıları için özel seçim widget’ları.
- **`routing.py`**: WebSocket endpoint’i (`ws/chat/<entry_id>/`).

### `ml_simulator/`
- `settings.py`: ortam değişkenleri, CORS/CSRF, Channels, Redis ve e-posta yapılandırması.
- `urls.py`: Kök URL’yi frontend’e yönlendirir, `/admin/`, `/api/`, parola sıfırlama yolları.
- `asgi.py`: Channels `ProtocolTypeRouter` yapılandırması (HTTP + WebSocket).

### Diğer dizinler
- `documents/`: Senaryo ve değerlendirme dokümanları + müşteri logoları ve arka plan görselleri.
- `templates/`: Admin ve e-posta şablonları (`registration/`).
- `static/`: Admin, rest_framework ve üçüncü parti paketlerin statik dosyaları.
- `requirements.txt`: Tam bağımlılık listesi (LangChain ekosistemi, celery vb.).

---

## Veri Modeli

| Model | Görev | Önemli Alanlar |
| --- | --- | --- |
| `Customer` | Kurumsal müşteri yönetimi | `users` ManyToMany, logo dosyası silme logikleri |
| `Program` | Eğitim programı | `scenarios` through `ProgramScenario` |
| `ProgramScenario` | Program-senaryo bağlantısı | `weight_percentage`, `release_date`, `training_date`, `close_date`, `max_attempts` |
| `Scenario` | Simülasyon senaryosu | `scenario_document`, `review_document`, `bg_image`, `ai_level`, `voice` |
| `TrainingGroup` | Müşteri bazlı eğitim grubu | `program`, `customer`, `users` (`GroupUser` üzerinden), `progress` |
| `GroupUser` | Katılımcı-grup ilişkisi | `progress`, `total_score` (ağırlıklı ortalama) |
| `UserEntry` | Chat oturumu | `entry_id`, `is_locked`, `training_group` |
| `UserChatHistory` | Mesaj geçmişi | `user_query`, `gpt_response`, kronolojik sıralama |
| `EvaluationReport` | KPI değerlendirmesi | `score`, `type` (pre/post), `attempt_count`, rapor texti |

**Sinyaller:**

- `update_progress`: Post-evaluation rapor sonrası ilerleme ve ortalama güncelleme.
- `handle_program_scenario_change`: Program senaryoları değişince tüm katılımcıları yeniden hesaplar.
- `normalize_user_email`: Case-insensitive benzersizlik, username/email eşitlemesi.
- `send_password_reset_email`: Yeni kullanıcıya, environment’a uygun domain ile parola sıfırlama e-postası.

---

## Chatbot Diyalog Akışı

1. **Entry Oluşturma:** `/api/chatbot/` endpoint’i kullanıcı token’ı ile çağrılır, `TrainingGroup` kontrolü sonrası yeni `UserEntry` oluşturulur (UUID).
2. **WebSocket Bağlantısı:** Frontend `ws://<host>/ws/chat/<entry_id>/?token=...` formatıyla bağlanır, token doğrulanır, kullanıcıya ait entry olup olmadığı kontrol edilir.
3. **Diyalog:**  
   - `rag_chain` node’u: Senaryo dokümanından alınan bağlamla rol yapar, her token stream edilir.  
   - Sohbet geçmişi (`UserChatHistory`) 20 mesaja kadar senkronize edilir.
4. **Değerlendirme (Farewell):** Kullanıcı “rapor ver”, “görüşürüz” vb. ifadeler kullanırsa `evaluation_node` tetiklenir.
   - Pydantic şeması ile JSON KPI listesi alınır, skor doğrulamaları yapılır.
   - Rapor metni oluşturulur, toplam puan hesaplanır.
   - `EvaluationReport` kaydı yapılır, `attempt_count` güncellenir.
   - Entry kilitlenir (`is_locked=True`), chat geçmişi kayıt altına alınır.
5. **Yanıt Tamamlama:** WebSocket üzerinden `status=completed` mesajı ve rapor metni gönderilir.

---

## REST API Uçları

| Method / Path | Açıklama | Not |
| --- | --- | --- |
| `POST /api/login/` | Token alma (email + şifre). `permissions` ve `customer_logo` döner. | `rest_framework.authtoken` |
| `GET /api/entries/` | Kullanıcının tüm girişleri, sayfalı (`page_size=50`). | `UserEntrySerializer` |
| `GET /api/entries/<entry_id>/` | Belirli entry + chat geçmişi. | |
| `POST /api/chatbot/` | Yeni entry ID üretir. | `scenario` adı ve `group` ID parametreleri gerekir. |
| `GET /api/user/scenarios/` | Aktif ve yaklaşan senaryolar. | Yayın/eğitim/kapanış tarihine göre alt segmentler, deneme takibi. |
| `POST /api/tts/` | Metni senaryonun TTS sesiyle ses dosyasına çevirir. | `scenario_name`, `text` zorunlu. `__preview__voice` ile preview. |
| `GET /api/auth/csrf/` | Safari uyumlu CSRF cookie üretir. | |
| `ViewSet` uçları | `/api/scenario/`, `/api/customer/`, `/api/program/`, `/api/group/`, `/api/groupuser/`, `/api/programscenario/`, `/api/evaluationreport/` | DRF router ile CRUD |

**Kimlik Doğrulama:** `Token` header veya Session auth. WebSocket’te token query paramı.

---

## Kurulum ve Çalıştırma

### Ön koşullar
- Python 3.10
- PostgreSQL & Redis (örn. Upstash)
- OpenAI API anahtarı
- Sanal ortam (`env/`)

### 1. Ortam Değişkenleri

`.env` içinde en az şu değerler bulunmalı:

```
SECRET_KEY=...
DEBUG=True
OPENAI_API_KEY=...
DB_NAME=...
DB_USER=...
DB_PASSWORD=...
DB_HOST=...
DB_PORT=...
UPSTASH_REDIS_URL=...
EMAIL_HOST_PASSWORD=...
```

Prod ortamında `DEBUG=False`, `MEDIA_ROOT`, `ALLOWED_HOSTS`, `CSRF_COOKIE_SECURE` gibi ayarlar otomatik uyarlanır.

### 2. Bağımlılıklar

```bash
python -m venv env
source env/bin/activate
pip install -r requirements.txt
```

### 3. Veritabanı ve Statikler

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

Gerekirse superuser oluştur:

```bash
python manage.py createsuperuser
```

### 4. Sunucu Çalıştırma

**Geliştirme (Channels gereksinimi yoksa):**

```bash
python manage.py runserver 0.0.0.0:8000
```

**ASGI + Channels (önerilen):**

```bash
uvicorn ml_simulator.asgi:application --host 127.0.0.1 --port 8000 --log-level debug --reload
```

Log seviyeleri: `debug`, `info`, `warning`, `error`, `critical`.

**Prod örneği (gunicorn + uvicorn worker):**

```bash
gunicorn ml_simulator.asgi:application -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --log-level warning
```

---

## Yönetim Paneli

- `/admin/` üzerinden erişim.
- **ScenarioAdmin**: Senaryo listeleri, filtreler.
- **CustomerAdmin**: Müşteri-kullanıcı eşleştirme, çakışma kontrolleri.
- **TrainingGroup**:
  - Inline `GroupUser` listeleri, ilerleme çubukları.
  - Senaryo bazında pre/post rapor linkleri ve gelişim yüzdesi.
  - Excel dışa aktarım düğmesi.
- **ProgramScenario** Inline:
  - Ağırlıkların toplamını 100 olacak şekilde doğrulayan formset.
- **User Admin**:
  - E-posta doğrulaması, case-insensitive benzersiz username/email.
  - Yeni kullanıcıya otomatik parola sıfırlama maili.

---

## Geliştirme / Test Notları

- **Veritabanı:** PostgreSQL bağlantısı zorunlu; `sqlite` desteği yok.
- **Redis:** Channels + Caches için gereklidir.
- **Senaryo Dokümanları:** `documents/` altındaki PDF/DOCX dosyaları LangChain ile okunur; prod ortamında dosyaların erişilebilir olup olmadığını doğrulayın.
- **TTS:** OpenAI TTS (gpt-4o-mini-tts) kullanır; dosyalar `NamedTemporaryFile` ile geçici olarak oluşturulur.
- **Deneme Takibi:** `EvaluationReport.attempt_count` ile pre/post denemeleri sınırlar (`ProgramScenario.max_attempts`).
- **Test Önerileri:**
  - Model ilişki testi (progress, total_score hesapları).
  - WebSocket auth ve entry sahipliği kontrolleri.
  - LangGraph akışının farewell tespiti (`check_farewell_node`).
  - `available_scenarios_api` için tarih senaryoları (gelecek, aktif, kapanmış).
  - Admin form validasyonları (program senaryo ağırlıkları, müşteri kullanıcı tahsisi).
- **Enerji tüketimi:** LangChain/Embeddings için OpenAI API creditial’ları ve maliyet metriklerini takip edin.

---

## Hızlı Başlangıç

```bash
# 1. Ortam kurulumu
python -m venv env
source env/bin/activate
pip install -r requirements.txt

# 2. .env ile yapılandırma
cp .env.example .env  # (varsa) içerikleri doldurun

# 3. DB + static
python manage.py migrate
python manage.py collectstatic --noinput

# 4. Geliştirme sunucusu
uvicorn ml_simulator.asgi:application --host 0.0.0.0 --port 8000 --reload

# 5. Admin paneli
open http://localhost:8000/admin/
```

---

Bu README, projenin tüm bileşenlerini ve mimarîsini kapsayacak şekilde düzenlendi.


