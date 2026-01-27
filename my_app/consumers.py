from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from channels.generic.websocket import AsyncWebsocketConsumer
from chatbot.chatbot import Chatbot
from chatbot.context_utils import get_chat_history
from my_app.models import UserEntry, UserChatHistory
import json, hashlib, asyncio, re
from rest_framework.authtoken.models import Token
from asgiref.sync import sync_to_async
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
from django.core.cache import cache
from lingua import Language, LanguageDetectorBuilder  # type: ignore

class ChatConsumer(AsyncWebsocketConsumer):
    # Lingua dil dedektörü (sadece gerekli diller)
    language_detector = LanguageDetectorBuilder.from_languages(
        Language.TURKISH, Language.ENGLISH, Language.DUTCH, Language.AZERBAIJANI
    ).with_minimum_relative_distance(0.15).build()

    def detect_language(self, text: str) -> str:
        """
        Lingua ile dil tespiti. Öncelik: tr, en, nl, az. Belirsizse 'tr'.
        """
        if not text or not text.strip():
            return "tr"
        try:
            confidences = self.language_detector.compute_language_confidence_values(text)
            if not confidences:
                return "tr"
            top = confidences[0]
            lang_map = {
                Language.TURKISH: "tr",
                Language.ENGLISH: "en",
                Language.DUTCH: "nl",
                Language.AZERBAIJANI: "az",
            }
            score = None
            if hasattr(top, "value"):
                val = top.value
                score = val() if callable(val) else val
            if score is None:
                score = 0.0
            if score < 0.20:
                return "tr"

            print(f"Detected language: {lang_map.get(top.language, 'tr')}, confidence: {score}")
            return lang_map.get(top.language, "tr")
        except Exception as e:
            print(f"⚠️ Lingua detect error: {e}")
            return "tr"
    async def connect(self):
        """WebSocket bağlantısı kurulduğunda çalışır."""
        self.entry_id = self.scope["url_route"]["kwargs"]["entry_id"]

        query_string = self.scope.get("query_string", b"").decode()
        token_key = dict(qc.split("=") for qc in query_string.split("&")).get("token", None)

        if not token_key:
            await self.close(code=403)
            return
        
        # Kullanıcı nesnesini asenkron olarak al
        self.user = await self.get_user_from_token(token_key)

        if not self.user or self.user.is_anonymous:
            await self.close(code=403)
            return

        self.entry = await self.get_entry()
        self.room_group_name = f"chat_{self.entry_id}"

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        print(f"✅ Kullanıcı {self.room_group_name} odasına katıldı.")

    @database_sync_to_async
    def get_user_from_token(self, token_key):
        """Token doğrulamasını yaparak kullanıcıyı döndür."""
        try:
            token = Token.objects.get(key=token_key)
            return token.user
        except Token.DoesNotExist:
            return AnonymousUser()

    async def get_entry(self):
        try:
            return await database_sync_to_async(UserEntry.objects.get)(entry_id=self.entry_id, user=self.user)
        except UserEntry.DoesNotExist:
            return None

    async def disconnect(self, close_code):
        """WebSocket bağlantısı kapatıldığında çalışır."""
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        print(f"❌ Kullanıcı {self.room_group_name} odasından ayrıldı.")

    async def receive(self, text_data):
        """WebSocket üzerinden gelen mesajları işler ve yanıtları akış (stream) olarak gönderir."""
        print("📩 Mesaj alındı, işleniyor...")
        
        data = json.loads(text_data)
        question = data.get("question", "")
        evaluation_phase = data.get("evaluation_phase", None)
        is_feedback = data.get("is_feedback", False)
        feedback_category = data.get("feedback_category", None)
        print("🔍 DEBUG - Gelen data:", data)
        language = self.detect_language(question)
        print(f"🌐 Detected language: {language}")

        if not question:
            await self.send(json.dumps({"error": "Mesaj içeriği boş!"}))
            return
        
        print(f"🔍 Kullanıcıdan gelen soru: {question}")

        if is_feedback:
            if not self.entry.is_locked:
                await self.send(json.dumps({"error": "Değerlendirme tamamlanmadan feedback gönderilemez."}))
                return
            if not feedback_category:
                await self.send(json.dumps({"error": "Feedback kategorisi eksik."}))
                return

        chatbot = Chatbot(self.scope["session"])
        chat_history, average_response_time = await get_chat_history(self.entry)
        scenario = await sync_to_async(lambda: self.entry.scenario)()

        full_answer = []
        last_node = None
        stream_total_score = None

        print("🤖 LLM Yanıt Üretme Başladı...")
        async for result in chatbot.generate_response(
            question,
            chat_history,
            scenario,
            is_feedback=is_feedback,
            feedback_category=feedback_category,
            language=language,
            average_response_time=average_response_time
        ):
            #print(f"📝 Token Alındı: {token}")
            token = result.get("token", None)
            node = result.get("node", None)
            if "total_score" in result:
                ts = result.get("total_score", None)
                if ts is not None:
                    stream_total_score = ts
            full_answer.append(token)    
            await self.send(json.dumps({"token": token, "node": node}))
            last_node = node

        print("last_node:", last_node)

        final_answer = "".join(full_answer)
        if last_node in ("evaluation_node", "feedback_evaluation_node"):
            print("✅ Değerlendirme tamamlandı. Rapor veritabanına kaydediliyor.")
            await self.save_evaluation_report(
                self.entry,
                self.user,
                final_answer,
                eval_type=evaluation_phase,
                is_feedback=is_feedback,
                total_score=stream_total_score
            )
            self.entry.is_locked = True
            await database_sync_to_async(self.entry.save)()

        await self.save_chat_history(question, final_answer)

        print("Senaryo:", self.entry.scenario.name)
        print("✅ Yanıt tamamlandı ve gönderiliyor.")
        await self.send(json.dumps({
            "status": "completed",
            "final_answer": final_answer,
            "entry_id": self.entry_id,
            "entry_name": str(self.entry.scenario).title(),
            "created_at": self.entry.created_at.isoformat(),
            "is_locked": self.entry.is_locked,
        }))

    @database_sync_to_async
    def save_evaluation_report(self, entry, user, report_text, eval_type=None, is_feedback: bool = False, total_score=None):
        if eval_type not in ["pre", "post"]:
            print("🔍 DEBUG - eval_type geçersiz, None döndürülüyor")
            return None
        
        score = None
        if total_score is not None:
            try:
                score = min(100, max(0, int(total_score)))
                print(f"✅ Score from stream: {score}")
            except Exception as e:
                print(f"⚠️ total_score parse error: {e}")

        if score is None:
            print("⚠️ Stream total_score gelmedi, rapor kaydedilmiyor.")
            return None
        from my_app.models import EvaluationReport

        existing_report = EvaluationReport.objects.filter(
            user=user,
            training_group=entry.training_group,
            scenario=entry.scenario,
            type=eval_type
        ).first()

        if is_feedback:
            if not existing_report:
                print("⚠️ Feedback isteğinde existing_report bulunamadı.")
                return None

            if eval_type == "pre":
                if existing_report.attempt_count == 1:
                    existing_report.report = report_text
                    existing_report.score = score
                    existing_report.average_score = Decimal(score)
                    existing_report.created_at = timezone.now()
                    existing_report.save()
                    print("🔁 Feedback (pre, first attempt) rapor güncellendi.")
                else:
                    old_attempt_count = existing_report.attempt_count
                    existing_report.attempt_count += 1
                    current_avg = existing_report.average_score if existing_report.average_score is not None else Decimal(existing_report.score)
                    existing_report.average_score = (
                        current_avg * Decimal(old_attempt_count) + Decimal(score)
                    ) / Decimal(existing_report.attempt_count)
                    existing_report.average_score = existing_report.average_score.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    existing_report.save()
                    print("🔁 Feedback (pre) attempt_count>1, average_score güncellendi.")
                return existing_report

            if eval_type == "post":
                if score > existing_report.score:
                    old_attempt_count = existing_report.attempt_count
                    existing_report.attempt_count += 1
                    current_avg = existing_report.average_score if existing_report.average_score is not None else Decimal(existing_report.score)
                    existing_report.average_score = (
                        current_avg * Decimal(old_attempt_count) + Decimal(score)
                    ) / Decimal(existing_report.attempt_count)
                    existing_report.average_score = existing_report.average_score.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    existing_report.report = report_text
                    existing_report.score = score
                    existing_report.created_at = timezone.now()
                    existing_report.save()
                    print("🔁 Feedback (post) skor yükseldi, rapor ve average_score güncellendi.")
                else:
                    old_attempt_count = existing_report.attempt_count
                    existing_report.attempt_count += 1
                    current_avg = existing_report.average_score if existing_report.average_score is not None else Decimal(existing_report.score)
                    existing_report.average_score = (
                        current_avg * Decimal(old_attempt_count) + Decimal(score)
                    ) / Decimal(existing_report.attempt_count)
                    existing_report.average_score = existing_report.average_score.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    existing_report.save()
                    print("🔁 Feedback (post) skor yükselmedi, sadece average_score güncellendi.")
                return existing_report

        # Pre-evaluation raporu var ise yeniden kaydetmeden sadece attempt_count'u artır
        if eval_type == "pre" and existing_report:
            print("⚠️ Pre-evaluation zaten var, yeniden kaydedilmeyecek.")
            # average_score hesapla: (mevcut_ortalama * mevcut_deneme_sayısı + yeni_skor) / (mevcut_deneme_sayısı + 1)
            # Eğer average_score None ise (edge case), model'in save() metodu score'a eşitleyecek
            # Ama hesaplama için mevcut değeri kullanıyoruz
            old_attempt_count = existing_report.attempt_count
            existing_report.attempt_count += 1
            current_avg = existing_report.average_score if existing_report.average_score is not None else Decimal(existing_report.score)
            existing_report.average_score = (
                current_avg * Decimal(old_attempt_count) + Decimal(score)
            ) / Decimal(existing_report.attempt_count)
            existing_report.average_score = existing_report.average_score.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            existing_report.save()
            return None

        # Post-evaluation raporu var ve yeni rapor daha yüksek puan ise güncelle
        elif eval_type == "post" and existing_report:
            old_attempt_count = existing_report.attempt_count
            existing_report.attempt_count += 1
            
            # average_score hesapla: (mevcut_ortalama * mevcut_deneme_sayısı + yeni_skor) / (mevcut_deneme_sayısı + 1)
            # Eğer average_score None ise (edge case), model'in save() metodu score'a eşitleyecek
            # Ama hesaplama için mevcut değeri kullanıyoruz
            current_avg = existing_report.average_score if existing_report.average_score is not None else Decimal(existing_report.score)
            existing_report.average_score = (
                current_avg * Decimal(old_attempt_count) + Decimal(score)
            ) / Decimal(existing_report.attempt_count)
            existing_report.average_score = existing_report.average_score.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            if score > existing_report.score:
                existing_report.report = report_text
                existing_report.score = score
                existing_report.created_at = timezone.now()
                existing_report.save()
                print(f"🔁 Post-evaluation güncellendi (yeni skor: {score}).")
                return existing_report
            else:
                existing_report.save()
                print("⏭️ Önceki post-evaluation skoru daha yüksek, güncellenmedi.")
                return existing_report
    
        else:
            # Yeni kayıt oluştur (ilk deneme)
            # average_score model'in save() metodu tarafından otomatik olarak score'a eşitlenecek
            return EvaluationReport.objects.create(
                user=user,
                customer=entry.training_group.customer,
                training_group=entry.training_group,
                scenario=entry.scenario,
                report=report_text,
                score=score,
                type=eval_type
            )

    async def save_chat_history(self, question, final_answer):
        """Kullanıcının sohbet geçmişine yanıtları kaydeder. Entry.created_at değerini günceller."""
        self.entry.created_at = timezone.now()
        await database_sync_to_async(self.entry.save)()

        await database_sync_to_async(UserChatHistory.objects.create)(entry=self.entry, user_query=question, gpt_response=final_answer)
        print(f"✅ Yanıt chat geçmişine kaydedildi.")

