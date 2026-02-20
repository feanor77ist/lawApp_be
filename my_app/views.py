from rest_framework import viewsets, permissions
from rest_framework.authentication import SessionAuthentication, TokenAuthentication

from .models import (
    User,
    CaseFile,
    ExpenseCategory,
    Expense,
    Document,
    ChatSession,
    ChatMessage,
)
from .serializers import (
    UserSerializer,
    CaseFileSerializer,
    ExpenseCategorySerializer,
    ExpenseSerializer,
    DocumentSerializer,
    ChatSessionSerializer,
    ChatMessageSerializer,
)


class DefaultAuthMixin:
    authentication_classes = [SessionAuthentication, TokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]


class UserViewSet(DefaultAuthMixin, viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("-date_joined")
    serializer_class = UserSerializer

    def get_permissions(self):
        # Kayıt (create) için anonim erişime izin ver; diğerleri auth ister.
        if self.action in ["create"]:
            return [permissions.AllowAny()]
        return super().get_permissions()


class CaseFileViewSet(DefaultAuthMixin, viewsets.ModelViewSet):
    serializer_class = CaseFileSerializer

    def get_queryset(self):
        return CaseFile.objects.filter(created_by=self.request.user).order_by("-created_at")


class ExpenseCategoryViewSet(DefaultAuthMixin, viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all().order_by("name")
    serializer_class = ExpenseCategorySerializer


class ExpenseViewSet(DefaultAuthMixin, viewsets.ModelViewSet):
    serializer_class = ExpenseSerializer

    def get_queryset(self):
        return Expense.objects.filter(created_by=self.request.user).select_related("case").order_by("-islem_tarihi")


class DocumentViewSet(DefaultAuthMixin, viewsets.ModelViewSet):
    serializer_class = DocumentSerializer

    def get_queryset(self):
        return Document.objects.filter(created_by=self.request.user).order_by("-created_at")


class ChatSessionViewSet(DefaultAuthMixin, viewsets.ModelViewSet):
    serializer_class = ChatSessionSerializer

    def get_queryset(self):
        return ChatSession.objects.filter(user=self.request.user).order_by("-updated_at")


class ChatMessageViewSet(DefaultAuthMixin, viewsets.ModelViewSet):
    serializer_class = ChatMessageSerializer

    def get_queryset(self):
        qs = ChatMessage.objects.filter(session__user=self.request.user).select_related("session").order_by("created_at")
        session_id = self.request.query_params.get("session")
        if session_id:
            qs = qs.filter(session_id=session_id)
        return qs
