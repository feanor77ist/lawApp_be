# FE (Next.js) entegrasyon rehberi — Feedback düğmesi

Bu rehber, backend tarafında eklediğimiz feedback akışına Next.js (WS) istemcisinin uyum sağlaması için gerekli değişiklikleri özetler.

## Mesaj şeması (WS → backend)
- `question`: string — kullanıcı feedback metni (butona tıklayınca önceden tanımlı kısa metin / opsiyonel serbest açıklama).
- `evaluation_phase`: `"pre"` | `"post"` — mevcutta kullandığınız değer.
- `is_feedback`: boolean — feedback akışı için **true**.
- `feedback_category`: `"content_error" | "score_error" | "system_error" | "misunderstanding"` (veya backend ile senkron enum).

Örnek payload:
```json
{
  "question": "Rapor içeriğinde hatalar var",
  "evaluation_phase": "post",
  "is_feedback": true,
  "feedback_category": "content_error"
}
```

## UI akışı
1) `evaluation_node` tamamlandığında (backend’den `status: "completed"` ve `node: "evaluation_node"` gördüğünüz an) feedback butonlarını gösterin.
2) Entry `is_locked === true` bilgisi backend `completed` mesajında geliyor; feedback butonlarını sadece bu durumda aktif edin.
3) Kullanıcı butona basınca yukarıdaki payload ile WS’e gönderin; streaming yanıtı mevcut akışla aynı şekilde alın (token token).
4) Feedback yanıtı bittiğinde `node` alanı `feedback_evaluation_node` olarak gelecek; nihai raporu önceki raporun yerine UI’da gösterin.

## Next.js (ChatArea) için uygulanacaklar

### Mesaj gönderimi
- Normal mesaj: mevcut `sendMessage` flow (WS open → `{ question, entry_id, evaluation_phase }`).
- Feedback mesajı: `handleEvaluationFeedback` içinde WS’e `{ question, entry_id, evaluation_phase, is_feedback: true, feedback_category }` gönderin.

Örnek uyarlama:
```ts
const handleEvaluationFeedback = (categoryText: string) => {
  if (!currentChatId) return;
  const wsBaseURL = process.env.NEXT_PUBLIC_WS_BASE_URL;
  const token = localStorage.getItem("token");
  const payload = {
    question: categoryText,                  // buton metni
    entry_id: currentChatId,
    evaluation_phase: selectedEvaluationPhase, // "post" veya "pre"
    is_feedback: true,
    feedback_category: mapCategory(categoryText),
  };

  const sendPayload = (ws: WebSocket) => ws.send(JSON.stringify(payload));

  if (socket && socket.readyState === WebSocket.OPEN) {
    sendPayload(socket);
    return;
  }

  const ws = new WebSocket(`${wsBaseURL}/ws/chat/${currentChatId}/?token=${token}`);
  ws.onopen = () => sendPayload(ws);
  ws.onmessage = (event) => onMessageHandler(JSON.parse(event.data)); // mevcut onmessage logic’inizi bağlayın
  ws.onclose = () => {};
  setSocket(ws);
};

const mapCategory = (text: string) => {
  if (text.includes("içeriğinde")) return "content_error";
  if (text.includes("puan")) return "score_error";
  if (text.includes("Sistem")) return "system_error";
  return "misunderstanding";
};
```

### Streaming ayrımı (onMessage)
- `node === "rag_chain"` → diyaloğa ekle.
- `node === "evaluation_node"` veya `node === "feedback_evaluation_node"` → rapor metnini (token token) topla.
- `status === "completed"` geldiğinde:
  - Son mesajın `gpt_response`’ını `final_answer` ile güncelle.
  - `is_locked` bilgisini `onEntryLockUpdate` ile sakla (feedback sonrası da kilitli kalır).
  - `evaluationFeedbackEntryId` ve `showEvaluationFeedbackButtons` akışı: mevcut ref tabanlı kontrol (yalnızca ilgili entry’de buton göster).

## UI/UX notları
- Feedback butonları sadece kilitli entry ve değerlendirme tamamlandıktan sonra gösterilmeli.
- Her buton sabit bir `feedback_category` gönderiyor olmalı; metni backend ile senkron tutun (gerekirse config dosyasında saklayın).
- Aynı anda ikinci bir feedback gönderimini engellemek için “busy” durumu ekleyin.

## Test checklist
- `is_feedback=false` normal diyalog + farewell → rapor akışı değişmeden çalışıyor mu?
- `is_feedback=true`, `feedback_category` set, entry locked: feedback yanıtı geliyor ve `node` değeri `feedback_evaluation_node` olarak stream ediliyor mu?
- Post feedback: skor artmıyorsa rapor değişmiyor, artıyorsa güncelleniyor mu?
- Pre feedback: sadece ilk attempt’te (attempt_count==1) rapor güncelleniyor, sonrası değişmeden kalıyor mu?
