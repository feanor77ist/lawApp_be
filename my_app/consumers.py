from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from channels.generic.websocket import AsyncWebsocketConsumer
from my_app.models import ChatSession, ChatMessage
from rest_framework.authtoken.models import Token
import json
import asyncio


class RAGStreamConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for RAG streaming.
    Connect: ws://host/ws/rag/<session_id>/?token=<auth_token>
    Send: {"question": "..."}
    Receive: stream of {"token": "..."} then {"status": "completed", "final_answer": "...", ...}
    """

    async def connect(self):
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]

        query_string = self.scope.get("query_string", b"").decode()
        token_key = (
            dict(qc.split("=", 1) for qc in query_string.split("&") if "=" in qc).get("token")
            if query_string
            else None
        )

        if not token_key:
            await self.close(code=403)
            return

        self.user = await self.get_user_from_token(token_key)
        if not self.user or self.user.is_anonymous:
            await self.close(code=403)
            return

        self.session = await self.get_session()
        if not self.session:
            await self.close(code=404)
            return

        self.room_group_name = f"rag_session_{self.session_id}"
        try:
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        except Exception:
            pass  # InMemoryChannelLayer may not be configured; streaming still works via self.send()
        await self.accept()

    @database_sync_to_async
    def get_user_from_token(self, token_key):
        try:
            token = Token.objects.get(key=token_key)
            return token.user
        except Token.DoesNotExist:
            return AnonymousUser()

    @database_sync_to_async
    def get_session(self):
        try:
            return ChatSession.objects.get(id=self.session_id, user=self.user)
        except ChatSession.DoesNotExist:
            return None

    async def disconnect(self, close_code):
        try:
            await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        except Exception:
            pass

    @database_sync_to_async
    def get_session_chat_history(self, limit=20):
        """Son mesajları (user_query, ai_response) listesi olarak döndürür."""
        messages = (
            self.session.messages.select_related("session")
            .order_by("-created_at")[:limit]
        )
        out = []
        for m in reversed(list(messages)):
            out.append({"role": "user", "content": m.user_query})
            if m.ai_response:
                out.append({"role": "assistant", "content": m.ai_response})
        return out

    async def stream_rag_response(self, question: str, chat_history: list):
        """
        RAG stream placeholder. Gerçek RAG pipeline eklendiğinde burada
        vektör arama + LLM stream yapılacak; her chunk için yield edin.
        """
        # Placeholder: tek cümle parça parça gönder (test için)
        placeholder = "RAG yanıtı burada akışlı olarak gelecek. Sorunuz: " + (question[:50] + "..." if len(question) > 50 else question)
        for i in range(0, len(placeholder), 8):
            chunk = placeholder[i : i + 8]
            yield {"token": chunk}

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send(json.dumps({"error": "Geçersiz JSON."}))
            return

        question = (data.get("question") or "").strip()
        if not question:
            await self.send(json.dumps({"error": "Soru boş olamaz."}))
            return

        chat_history = await self.get_session_chat_history()

        full_answer = []
        async for result in self.stream_rag_response(question, chat_history):
            token = result.get("token", "")
            full_answer.append(token)
            await self.send(json.dumps({"token": token}))

        final_answer = "".join(full_answer)
        await self.save_chat_message(question, final_answer, sources=None)

        await self.send(
            json.dumps(
                {
                    "status": "completed",
                    "final_answer": final_answer,
                    "session_id": self.session_id,
                }
            )
        )

    @database_sync_to_async
    def save_chat_message(self, user_query: str, ai_response: str, sources=None):
        ChatMessage.objects.create(
            session=self.session,
            user_query=user_query,
            ai_response=ai_response,
            sources=sources,
        )
