# RAG / LangChain Hukuki Test Senaryoları

Bu doküman, **karar arama**, **chat asistan**, **sözleşme inceleme** ve **dilekçe üretimi** işlevlerine yönelik, hukuki kullanımı yansıtan test senaryosu içeriklerini içerir. RAG pipeline’ını ve hukuki çıktı kalitesini test ederken bu örnekleri doğrudan kullanabilirsiniz.

---

## 1. Karar Arama (İçtihat / Yargıtay)

Karar veritabanı üzerinde semantik arama ve metadata filtreleme testleri için örnek sorgular.

### 1.1 İş Hukuku


| #   | Sorgu metni                                                                                     | Beklenen kavram / sonuç notu                        |
| --- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| 1   | İşçinin haklı nedenle fesih hakkı kullanması sonrası kıdem ve ihbar tazminatına hak kazanır mı? | 4857 sayılı İş K. 24, 17; kıdem tazminatı koşulları |
| 2   | Toplu işçi çıkarma usulü ve geçerli sebep                                                       | İş K. 29, bildirim, BİDK süreleri                   |
| 3   | İşe iade davasında işverenin yerleşik işçi sayısına göre yükümlülüğü                            | İş K. 21, işe iade, tazminat sınırları              |
| 4   | Belirsiz süreli iş sözleşmesinde fesih bildirimi süreleri                                       | İş K. 17, ihbar süreleri, kıdem                     |
| 5   | Fazla mesai ve ulusal bayram çalışması ücreti hesaplama                                         | İş K. 41-42, ücret, zamlı ödeme                     |
| 6   | İş kazası ve meslek hastalığında işverenin kusur oranı                                          | BK 49, SGK, tazminat                                |


### 1.2 Borçlar / Sözleşmeler


| #   | Sorgu metni                                                | Beklenen kavram / sonuç notu        |
| --- | ---------------------------------------------------------- | ----------------------------------- |
| 7   | Sözleşmede cayma hakkı ve cezai şart                       | TBK 174, 182; cezai şartın indirimi |
| 8   | Haksız fiil tazminatında kusur oranları ve müterafık kusur | TBK 49, 51; BK 54                   |
| 9   | Alacaklı temerrüdü ve ifa yerinde teklif                   | TBK 95-96                           |
| 10  | Zamanaşımı süreleri borçlar hukukunda                      | TBK 146 vd., 10 yıl, 5 yıl          |
| 11  | Kira sözleşmesinde fesih ve tahliye davası                 | TBK 347, 352; tapu iptali           |


### 1.3 İcra ve İflas


| #   | Sorgu metni                                          | Beklenen kavram / sonuç notu     |
| --- | ---------------------------------------------------- | -------------------------------- |
| 12  | İlamlı icra takibinde itirazın kaldırılması şartları | İİK 68-69, itirazın kaldırılması |
| 13  | İtirazın kaldırılması davasında süre                 | İİK 68, 7 gün, tebligat          |
| 14  | Rehinin paraya çevrilmesi usulü                      | İİK 148 vd., rehin satışı        |
| 15  | İflasın ertelenmesi ve konkordato                    | İİK 296, 305 vd.                 |


### 1.4 Ceza Hukuku


| #   | Sorgu metni                                  | Beklenen kavram / sonuç notu |
| --- | -------------------------------------------- | ---------------------------- |
| 16  | Dolandırıcılık suçunda taksir ve kast ayrımı | TCK 157                      |
| 17  | Hakaret suçunda cezada indirim ve uzlaşma    | TCK 125, 134                 |
| 18  | Özel hayatın gizliliğinin ihlali             | TCK 134-136                  |


### 1.5 İdare / İdari Yargı


| #   | Sorgu metni                                         | Beklenen kavram / sonuç notu |
| --- | --------------------------------------------------- | ---------------------------- |
| 19  | İdari işlemin iptali davasında süre                 | 2577 sayılı K. 7, 60 gün     |
| 20  | Memur disiplin cezası ve kademe ilerlemesi durdurma | 657 DMK, AYİM içtihatları    |
| 21  | Kamu ihale sözleşmesinin feshi ve tazminat          | 4734 KİK, idari sözleşme     |


### 1.6 Aile / Miras


| #   | Sorgu metni                                 | Beklenen kavram / sonuç notu |
| --- | ------------------------------------------- | ---------------------------- |
| 22  | Boşanmada mal paylaşımı ve yasal mal rejimi | TMK 218-241                  |
| 23  | Velayet değişikliği koşulları               | TMK 182                      |
| 24  | Mirasçılık belgesi ve tenkis davası         | TMK 560 vd., saklı pay       |


---

## 2. Chat Asistan (RAG Sohbet)

Çok turlu sohbet testleri için örnek diyaloglar. Her turda kullanıcı sorusu ve sistemin cevaplaması beklenen konu başlıkları verilmiştir.

### 2.1 İş Hukuku Diyalog Örneği


| Tur | Kullanıcı sorusu                                       | Beklenen cevap odakları                         |
| --- | ------------------------------------------------------ | ----------------------------------------------- |
| 1   | İşe iade davası nedir, hangi koşullarda açılır?        | İş K. 21, 20+ işçi, fesih bildirimi, 1 ay süre  |
| 2   | İşe iade davası kazanılırsa işveren ne yapmak zorunda? | Seçim: işe alma veya tazminat (4-8 aylık ücret) |
| 3   | İşveren işe almazsa tazminat nasıl hesaplanır?         | Son brüt ücret, 4–8 ay arası, Yargıtay formülü  |


### 2.2 Borçlar / Kira Diyalog Örneği


| Tur | Kullanıcı sorusu                                                  | Beklenen cevap odakları                                                                             |
| --- | ----------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| 1   | Kira sözleşmesinde kiracı erken çıkarsa kira borcu devam eder mi? | TBK 347, kiracı temerrüdü, kiralayanın azami yükümlülüğü (boşaltma sonrası kiralanana kiraya verme) |
| 2   | Kiralayan kiracıyı tahliye etmek için hangi yolu kullanabilir?    | İlamlı icra, tahliye davası, süre (süreli sözleşmede süre sonu)                                     |
| 3   | Kira artış oranı nasıl belirlenir?                                | TÜFE, sözleşme serbestisi, 5 yıllık sınır (konut)                                                   |


### 2.3 İcra Diyalog Örneği


| Tur | Kullanıcı sorusu                                         | Beklenen cevap odakları                                             |
| --- | -------------------------------------------------------- | ------------------------------------------------------------------- |
| 1   | İlamlı icra takibinde borçlu itiraz ederse ne olur?      | İİK 68, takibin kesilmesi, itirazın kaldırılması davası             |
| 2   | İtirazın kaldırılması davası nerede açılır, süre var mı? | İcra dairesi, 7 gün (tebligat tarihinden), yetkili mahkeme          |
| 3   | Borçlu ödeme yaparsa itiraz kaldırılır mı?               | İtirazın kaldırılması davasına gerek kalmaz, takip ödenerek kapanır |


### 2.4 Genel Hukuki Kavram Diyalogları


| Tur | Kullanıcı sorusu                                | Beklenen cevap odakları                                                                             |
| --- | ----------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| 1   | Zamanaşımı ile hak düşürücü süre farkı nedir?   | Zamanaşımı: dava hakkı düşer, dava açılabilir; hak düşürücü: hak tamamen düşer; örnekler (TBK, HMK) |
| 2   | HMK’ya göre davada delil süresi ne zaman biter? | HMK 146, 147; ön inceleme, delil başvurusu süresi                                                   |
| 3   | Emsal karar nedir, mahkeme nasıl kullanır?      | Bağlayıcı değil; Yargıtay birleşik kararı, içtihadı birleştirme                                     |


---

## 3. Sözleşme İnceleme

Kullanıcı dokümanı (sözleşme metni) yüklendikten sonra RAG ile risk, eksik hüküm ve özet testleri. Aşağıdaki **örnek sözleşme metinleri** ve **test prompt’ları** kullanılabilir.

### 3.1 Örnek: Kira Sözleşmesi Parçası (Test Verisi)

**Yüklenecek metin (kısa örnek):**

```
KİRA SÖZLEŞMESİ
Taraflar: Kiraya veren X A.Ş., Kiracı Y Ltd. Şti.
Konu: İstanbul … adresindeki ticari gayrimenkulün kiralanması.
Süre: 2 (iki) yıl, 01.01.2025 – 31.12.2026.
Kira bedeli: Aylık 50.000 TL + KDV, her yıl Ocak ayında TÜFE oranında artacaktır.
Ödeme: Her ayın 5’ine kadar.
Kiralayan, kiracı aleyhine doğacak tüm hasar ve taleplerden kiracıyı sorumlu tutar.
Kiracı sözleşmeyi tek taraflı feshedemez; aksi halde kalan süre kirasının tamamı cezai şart olarak tahsil edilir.
```

**Test prompt’ları:**


| #   | Prompt                                                               | Beklenen çıktı odakları                                                                    |
| --- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 1   | Bu sözleşmedeki riskli maddeleri listele ve kısaca açıkla.           | Cezai şart (tüm kalan süre), tek taraflı fesih yasağı, kiralayan lehine sorumluluk kayması |
| 2   | Sözleşmede eksik olabilecek hükümler nelerdir?                       | Depozito, vergi/ aidat payı, bakım-onarım, sigorta, alt kiralama, erken fesih hali         |
| 3   | Bu kira sözleşmesini 5 cümleyle özetle.                              | Taraflar, konu, süre, kira bedeli, artış, ödeme, cezai şart                                |
| 4   | Kiracı açısından en riskli madde hangisidir, nasıl değiştirilebilir? | Cezai şart; sınırlı cezai şart veya makul tazminat önerisi                                 |


### 3.2 Örnek: İş Sözleşmesi / Ek Protokol Parçası

**Yüklenecek metin (kısa örnek):**

```
EK PROTOKOL – GİZLİLİK VE REFAKATSIZ ÇALIŞMA
İşçi, iş ilişkisi devam ederken ve sona erdikten sonra 3 yıl süreyle işverenin ticari sırlarını açıklamayacaktır.
İşçi, iş ilişkisi sona erdikten sonra 2 yıl süreyle aynı sektörde rakip işveren nezdinde çalışmayacaktır.
Bu yasağa uyulmaması halinde 24 aylık brüt ücret tutarında cezai şart ödenecektir.
```

**Test prompt’ları:**


| #   | Prompt                                           | Beklenen çıktı odakları                                                          |
| --- | ------------------------------------------------ | -------------------------------------------------------------------------------- |
| 1   | Bu metindeki risk maddelerini tespit et.         | Rekabet yasağı süresi/maddi koşullar, cezai şart oranı, gizlilik süresi          |
| 2   | Türk iş hukukuna göre rekabet yasağı geçerli mi? | TTK 447/4, makul süre ve coğrafi/konu sınırı, tazminat karşılığı                 |
| 3   | Özet ve öneri ver.                               | Gizlilik + rekabet yasağı + cezai şart; süre/coğrafya sınırı ve tazminat önerisi |


### 3.3 Örnek: Hizmet / Danışmanlık Sözleşmesi Parçası

**Yüklenecek metin (kısa örnek):**

```
HİZMET SÖZLEŞMESİ
İş: … projesi kapsamında danışmanlık hizmeti.
Süre: 6 ay.
Bedel: Toplam 200.000 TL + KDV, 2 taksitte ödenecektir.
Fikri mülkiyet: Proje çıktıları müşteriye aittir.
Taraflardan biri sözleşmeyi önceden feshedemez; fesih halinde kalan bedel tahsil edilir.
```

**Test prompt’ları:**


| #   | Prompt                           | Beklenen çıktı odakları                                                 |
| --- | -------------------------------- | ----------------------------------------------------------------------- |
| 1   | Risk maddeleri nelerdir?         | Fesih yasağı, kalan bedelin tamamının tahsili (cezai şart niteliği)     |
| 2   | Eksik hüküm öner.                | Teslim kabul, garanti süresi, gizlilik, mücbir sebep, uyuşmazlık çözümü |
| 3   | Bu sözleşmeyi 3 cümleyle özetle. | Hizmet, süre, bedel, fikri mülkiyet, fesih kısıtı                       |


---

## 4. Dilekçe Üretimi

RAG + şablon ile dilekçe taslağı üretimi testleri. Her senaryoda **bağlam (dava türü, taraflar, talep)** ve **beklenen dilekçe bölümleri** verilmiştir.

### 4.1 İşe İade Talebi (İş Mahkemesi)

**Senaryo girişi (bağlam):**

- **Dava türü:** İşe iade (İş K. 21)
- **Davacı:** Ad Soyad, eski işçi
- **Davalı:** … Ltd. Şti. (işveren)
- **Kısa olay:** İşveren, davacıyı 20’den fazla işçi çalışan işyerinde belirsiz süreli iş sözleşmesiyle çalışırken, geçerli sebep göstermeden feshetmiş; fesih bildirimi yazılı yapılmamış.
- **Talep:** İşe iade; işe alınmazsa 4–8 aylık tazminat.

**Beklenen dilekçe bölümleri / anahtar ifadeler:**

- Mahkeme: … İş Mahkemesi
- Konu: İşe iade talebi
- Taraflar, vekiller
- Olay özeti: İş ilişkisi, fesih, işçi sayısı (20+), fesih şekli
- Hukuki sebepler: İş K. 18, 20, 21; fesih usulü, geçerli sebep
- Sonuç ve talep: İşe iade; aksi halde 4–8 aylık tazminat; yargılama giderleri ve vekalet ücreti davalıya

**Test prompt’u örneği:**

- “Bu dava dosyası için işe iade talepli dilekçe taslağı oluştur. Davacı [Ad Soyad], davalı [Şirket], fesih tarihi [tarih], işçi sayısı 20’den fazla.”

### 4.2 Alacak Davası (İlamlı İcra Sonrası)

**Senaryo girişi:**

- **Dava türü:** İtirazın kaldırılması (İİK 68) veya alacak davası
- **Davacı:** Alacaklı
- **Davalı:** Borçlu
- **Kısa olay:** İlamlı icra takibi başlatıldı, borçlu itiraz etti; alacak ilama dayanıyor.
- **Talep:** İtirazın kaldırılması veya alacağın tahsili

**Beklenen dilekçe bölümleri:**

- İcra dairesi / mahkeme
- Takip tarihi, itiraz tarihi
- İlama dayalı alacak özeti
- İİK 68–69; süre (7 gün)
- Sonuç ve talep

**Test prompt’u örneği:**

- “Borçlu itiraz etti. İlama dayalı icra takibinde itirazın kaldırılması talepli dilekçe taslağı yaz. Takip no: …, borçlu: …, alacak tutarı: …”

### 4.3 Kira Tahliye Davası

**Senaryo girişi:**

- **Dava türü:** Tahliye (kira süresi dolmuş veya fesih)
- **Davacı:** Kiralayan
- **Davalı:** Kiracı
- **Kısa olay:** Kira süresi bitmiş / fesih bildirimi yapılmış; kiracı tahliye etmiyor.
- **Talep:** Tahliye, kira alacağı (opsiyonel)

**Beklenen dilekçe bölümleri:**

- Mahkeme (genel yetkili veya taşınmaz yeri)
- Sözleşme özeti, süre, kira bedeli
- Süre sonu veya fesih bildirimi
- TBK 347, 352; tahliye sebebi
- Sonuç ve talep: Tahliye, gecikme tazminatı / kira alacağı

**Test prompt’u örneği:**

- “Kiralayan olarak kiracıyı tahliye davası açacağım. Kira süresi [tarih]’de bitti, kiracı çıkmıyor. Tahliye ve kira alacağı talepli dilekçe taslağı oluştur.”

### 4.4 Tazminat (Haksız Fesih / Haksız Fiil)

**Senaryo girişi:**

- **Dava türü:** Maddi / manevi tazminat
- **Davacı:** İşçi / mağdur
- **Davalı:** İşveren / fail
- **Kısa olay:** Haksız fesih veya haksız fiil (örn. iş kazası); zarar özeti.
- **Talep:** Maddi ve manevi tazminat

**Beklenen dilekçe bölümleri:**

- Olay, hukuki nitelendirme (haksız fesih / haksız fiil)
- TBK 49, 50–51; BK 49 (iş kazası); İş K. (fesih)
- Zarar kalemleri (gelir kaybı, tedavi, manevi)
- Deliller (belge, tanık, bilirkişi)
- Sonuç ve talep

**Test prompt’u örneği:**

- “İşçi haksız fesih nedeniyle tazminat davası açacak. Son ücret …, kıdem … yıl. Maddi ve manevi tazminat talepli dilekçe taslağı oluştur.”

---

## 5. Test Kontrol Listesi (RAG Kalitesi)

RAG çıktılarını değerlendirirken aşağıdaki kriterlere göre işaretleyebilirsiniz.

- **Kaynak eşleşmesi:** Cevaptaki iddialar, karar/doküman parçalarıyla destekleniyor mu?
- **Hukuki doğruluk:** Madde numaraları ve temel kavramlar (İş K., TBK, İİK vb.) doğru mu?
- **Dil:** Hukuki Türkçe, resmi dilekçe üslubuna uygun mu?
- **Veri izolasyonu:** Kullanıcı dokümanı modunda sadece ilgili kullanıcının dokümanları mı kullanıldı?
- **Dilekçe yapısı:** Başlık, taraflar, olay, hukuki sebepler, talep bölümleri mevcut mu?
- **Sözleşme inceleme:** Risk / eksik hüküm / özet ayrımı net mi, öneriler makul mü?

Bu senaryoları manuel testlerde veya otomatik testlerde (sabit prompt + beklenen anahtar kelime / madde kontrolü) kullanabilirsiniz.