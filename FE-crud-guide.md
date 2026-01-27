# FE CRUD Geliştirme Rehberi (Next.js)

Bu rehber, UI’de user/senaryo/program/training group CRUD bileşenlerini geliştirirken ihtiyaç duyacağın API bilgilerini ve validasyon kurallarını özetler. Customer/user eşlemesini API’dan yapmayacağız.

## Auth
- Login: `POST /api/login/` body `{ email, password }` → cevapta `token` ve `permissions` gelir.
- Tüm isteklerde `Authorization: Token <token>` header’ı gönder.
- Login cevabında ayrıca `is_superuser` gelir; FE’de tam yetki için bunu kullan.

## Endpoint’ler
- Users: `/api/users/`
- Scenario: `/api/scenario/`
- Program: `/api/program/`
- ProgramScenario: `/api/programscenario/`
- TrainingGroup: `/api/group/`
- GroupUser: `/api/groupuser/`

## User CRUD ( `/api/users/` )
- Liste (GET): Non-superuser için sadece kendi primary customer’ındaki kullanıcılar gelir (backend filtreliyor).
- Oluştur (POST): body `{ email, first_name?, last_name? }`
  - email lower-case’e çekilir, case-insensitive unique kontrolü var; çakışırsa 400, detail mesajı gelir.
  - username=email; rastgele geçici parola set edilir (reset akışı çalışır).
  - Yeni kullanıcı otomatik çağıran kullanıcının primary customer’ına eklenir.
- Güncelle (PATCH/PUT): email değiştirirsen aynı unique kontrol; izin yoksa 403.
- Sil (DELETE): Model perm yoksa 403; başka müşteri kullanıcısı non-superuser için listede görünmez zaten.

## Scenario CRUD ( `/api/scenario/` )
- Full CRUD; yazma işlemleri için model perm gerekir. Özel validasyon yok.

## Program + ProgramScenario
- Program CRUD: `/api/program/`
- ProgramScenario CRUD: `/api/programscenario/`
  - Create/Update body örn: `{ program, scenario, weight_percentage, release_date?, training_date?, close_date?, max_attempts? }`
  - Ağırlık kuralı: Aynı programdaki tüm weight toplamı **tam 100** olmalı. Toplam ≠ 100 ise 400 döner. FE’de de toplamı kontrol et.
  - Silme: `DELETE /api/programscenario/{id}/`; kalan toplam 100 olmayacaksa sonraki ekleme/güncellemelerde 400 alırsın → FE’de toplamı dengele.

## TrainingGroup
- CRUD: `/api/group/`
- Create: `{ name, program, customer?, group_date?, users? }`
  - `customer` gönderilmezse backend çağıranın primary customer’ını kullanır.
  - Non-superuser, başka customer ile grup açamaz (403).
  - `trainers` alanı API’da read-only (UI’da göstermene gerek yok).
- Update: `customer` değişmez (backend sabit tutar).
- GroupUser: `/api/groupuser/`
  - Create: `{ training_group, user, ... }`
  - User, grup.customer’a bağlı değilse 400 döner (“Kullanıcı bu müşteriye bağlı değil.”).

## Hata yönetimi
- 400: Validasyon (ör. “Bu e-posta zaten kullanılıyor.”, ağırlık toplamı 100 değil, müşteri uyuşmazlığı). `detail` alanı string veya alan bazlı dict olarak gelir.
- 403: İzin/ müşteri kısıtı (“Bu işlem için izniniz yok.”, “Müşteri bulunamadı.”).
- FE’de status code’a göre mesajı göster; 400 için detail’i, 403 için detail string’ini kullan.

## İzinler (permissions)
- Login cevabındaki `permissions` listesini UI’da buton/görünürlük kontrolünde kullan.
- Yazma işlemleri (POST/PUT/PATCH/DELETE) ilgili modelin add/change/delete perm’ine tabi; GET için ek perm aranmaz.
- Perm kodları:
  - Scenario: `my_app.add_scenario`, `my_app.change_scenario`, `my_app.delete_scenario`
  - Program: `my_app.add_program`, `my_app.change_program`, `my_app.delete_program`
  - ProgramScenario: `my_app.add_programscenario`, `my_app.change_programscenario`, `my_app.delete_programscenario`
  - TrainingGroup: `my_app.add_traininggroup`, `my_app.change_traininggroup`, `my_app.delete_traininggroup`
  - GroupUser: `my_app.add_groupuser`, `my_app.change_groupuser`, `my_app.delete_groupuser`
  - User: `auth.add_user`, `auth.change_user`, `auth.delete_user`

## Örnek fetch (Next.js, fetch API)
```ts
async function createUser(token: string, payload: { email: string; first_name?: string; last_name?: string }) {
  const res = await fetch('/api/users/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Token ${token}`,
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || JSON.stringify(data));
  }
  return res.json();
}
```
