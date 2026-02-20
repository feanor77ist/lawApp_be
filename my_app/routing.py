from django.urls import path
from .consumers import RAGStreamConsumer

websocket_urlpatterns = [
    path("ws/rag/<int:session_id>/", RAGStreamConsumer.as_asgi()),
]
