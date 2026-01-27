document.addEventListener("DOMContentLoaded", function () {
  const voiceSelect = document.querySelector("#id_voice");
  if (!voiceSelect || !voiceSelect.parentElement) return;

  const playButton = document.createElement("button");
  playButton.type = "button";
  playButton.innerText = "🎧 Ses Önizle";
  playButton.title = "Bu sesi dinlemek için tıklayın";

  // ✅ Stil uygulamaları
  playButton.className = "button";  // admin stil
  playButton.style.marginLeft = "6px";
  playButton.style.verticalAlign = "middle";
  playButton.style.padding = "4px 8px";
  playButton.style.fontSize = "12px";

  try {
    voiceSelect.parentElement.appendChild(playButton);
  } catch (error) {
    console.error("Ses önizleme butonu eklenemedi:", error);
  }

  async function getCSRFToken() {
    try {
      const res = await fetch("/api/auth/csrf/", { credentials: "include" });
      const data = await res.json();
      return data.csrfToken || null;
    } catch (err) {
      console.error("CSRF token alınamadı:", err);
      return null;
    }
  }

  playButton.addEventListener("click", async () => {
    const voice = voiceSelect.value;
    const csrfToken = await getCSRFToken();
    if (!csrfToken) {
      alert("CSRF token alınamadı, işlem iptal edildi.");
      return;
    }
    const apiUrl = new URL("/api/tts/", window.location.origin).toString();
    playButton.disabled = true;
    playButton.innerText = "🔄 Yükleniyor...";

    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        credentials: "include",
        body: JSON.stringify({
          scenario_name: "__preview__" + voice,
          text: "Merhaba, bu bir ses önizlemesidir.",
        }),
      });

      if (!response.ok) {
        throw new Error("Ses önizleme isteği başarısız.");
      }

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.play();
    } catch (error) {
      console.error("Önizleme hatası:", error);
      alert("Ses alınamadı.");
    } finally {
        playButton.disabled = false;
        playButton.innerText = "🎧 Ses Önizle";
    }
  });
});
