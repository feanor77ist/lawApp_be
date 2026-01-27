# GPT-4.1-mini Token Kullanım Analizi

## Model Teknik Özellikleri
- **Context Window (Input + Context):** 1,047,576 token
- **Maximum Output:** 32,768 token
- **Model:** gpt-4.1-mini

## Mevcut Prompt Yapısı Analizi

### 1. RAG Chain (`rag_chain` node)

#### Prompt Bileşenleri:
- **System Prompt (sabit):** ~600 karakter ≈ **150 token**
  - Rol tanımı, etkileşim kuralları, dil talimatları
  
- **Scenario Context (değişken):** 5-6 Word sayfası
  - 1 Word sayfası ≈ 500 kelime ≈ 2,500 karakter ≈ 625 token
  - 5-6 sayfa ≈ **3,125 - 3,750 token**

- **Chat History (değişken):** En fazla 20 mesaj çifti
  - Her user_query: ortalama 200-500 karakter ≈ 50-125 token
  - Her gpt_response: ortalama 300-800 karakter ≈ 75-200 token
  - 20 mesaj çifti (40 mesaj): **2,500 - 6,500 token**
  - Not: `get_chat_history` fonksiyonu 20 chat kaydı alıyor, bu da 20 user_query + 20 gpt_response = 40 mesaj demek

- **User Input (değişken):** ~100-500 karakter ≈ **25-125 token**

#### Toplam Token Kullanımı (RAG Chain):
- **Minimum:** 150 + 3,125 + 2,500 + 25 = **5,800 token**
- **Maksimum:** 150 + 3,750 + 6,500 + 125 = **10,525 token**
- **Ortalama:** ~**8,000 token**

#### Limit Karşılaştırması:
- Kullanım: ~8,000 token / 1,047,576 token = **%0.76**
- ✅ **Çok güvenli aralıkta**

---

### 2. Evaluation Node (`_run_evaluation`)

#### Prompt Bileşenleri:
- **JSON System Prompt (sabit):** ~3,500 karakter ≈ **875 token**
  - Rol tanımı, değerlendirme talimatları, KPI format bilgisi
  - Ortalama yanıt süresi bilgisi (varsa): +100 karakter ≈ +25 token

- **Evaluation Criteria (değişken):** 5-6 Word sayfası
  - **3,125 - 3,750 token**

- **Chat History Text (değişken):** Sadece user_query'ler
  - 20 user_query × ortalama 300 karakter = 6,000 karakter
  - Format: "Kullanıcı Mesajı {i+1}: {content}"
  - Format overhead: ~500 karakter
  - Toplam: **1,625 token**

- **Feedback Note (opsiyonel):** ~500 karakter ≈ **125 token**

- **User Input (değişken):** ~100 karakter ≈ **25 token**

#### Toplam Token Kullanımı (Evaluation):
- **Minimum:** 875 + 3,125 + 1,625 + 25 = **5,650 token**
- **Maksimum:** 900 + 3,750 + 1,625 + 125 + 25 = **6,425 token**
- **Ortalama:** ~**6,000 token**

#### Limit Karşılaştırması:
- Kullanım: ~6,000 token / 1,047,576 token = **%0.57**
- ✅ **Çok güvenli aralıkta**

---

## Sonuç ve Öneriler

### ✅ Güvenlik Durumu
Her iki node için de token kullanımı model limitinin **%1'inin altında**. Sisteminiz şu anki yapısıyla **tamamen güvenli** aralıkta çalışıyor.

### 📊 Büyüme Potansiyeli
- Senaryo dokümanları **10-15 sayfaya** çıksa bile (~6,250-9,375 token) hala güvenli
- Chat history **50-100 mesaja** çıksa bile (~6,250-12,500 token) hala güvenli
- Her iki durum birlikte olsa bile toplam ~20,000 token civarında kalır, hala **%2'nin altında**

### ⚠️ Dikkat Edilmesi Gerekenler
1. **Chat history limiti:** Şu anda 20 mesaj ile sınırlı (`context_utils.py:11`). Bu limit artırılırsa token kullanımı doğrusal olarak artar.
2. **Doküman boyutu:** Senaryo ve evaluation dokümanları çok büyürse (20+ sayfa) dikkatli olunmalı.
3. **Mesaj uzunluğu:** Kullanıcılar çok uzun mesajlar gönderirse (1000+ karakter) token kullanımı artar.

### 💡 Optimizasyon Önerileri (Gerekirse)
Eğer gelecekte token kullanımı artarsa:
1. **Chat history truncation:** En eski mesajları kısaltmak veya özetlemek
2. **Doküman chunking:** Büyük dokümanları parçalara bölüp sadece ilgili kısımları göndermek
3. **Compression:** Önemli bilgileri özetleyerek göndermek

### 🎯 Mevcut Durum
**Sonuç:** Sisteminiz şu anki yapısıyla GPT-4.1-mini'nin input kapasitesi için **hiçbir sorun yaratmıyor**. Güvenle kullanmaya devam edebilirsiniz.
