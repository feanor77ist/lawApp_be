from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    UserViewSet,
    CaseFileViewSet,
    ExpenseCategoryViewSet,
    ExpenseViewSet,
    DocumentViewSet,
    ChatSessionViewSet,
    ChatMessageViewSet,
)

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='users')
router.register(r'cases', CaseFileViewSet, basename='cases')
router.register(r'expense-categories', ExpenseCategoryViewSet, basename='expense-categories')
router.register(r'expenses', ExpenseViewSet, basename='expenses')
router.register(r'documents', DocumentViewSet, basename='documents')
router.register(r'chat-sessions', ChatSessionViewSet, basename='chat-sessions')
router.register(r'chat-messages', ChatMessageViewSet, basename='chat-messages')

urlpatterns = [
    path('', include(router.urls)),
]
