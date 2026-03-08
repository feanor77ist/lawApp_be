from decimal import Decimal

from django.db.models import Sum
from django.utils.dateparse import parse_date
from rest_framework import viewsets, permissions
from rest_framework.authentication import SessionAuthentication, TokenAuthentication
from rest_framework.decorators import action
from rest_framework.response import Response

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

    @action(detail=True, methods=["get"], url_path="balance")
    def balance(self, request, pk=None):
        case = self.get_object()
        as_of_raw = request.query_params.get("as_of")
        as_of = None

        if as_of_raw:
            as_of = parse_date(as_of_raw)
            if as_of is None:
                return Response(
                    {"detail": "Geçersiz tarih formatı. as_of=YYYY-MM-DD kullanın."},
                    status=400,
                )

        expenses_qs = case.expenses.all()
        if as_of:
            expenses_qs = expenses_qs.filter(islem_tarihi__lte=as_of)

        def sum_by_type(islem_tipi: str) -> Decimal:
            total = expenses_qs.filter(islem_tipi=islem_tipi).aggregate(total=Sum("tutar"))["total"]
            return total if total is not None else Decimal("0")

        avans_alindi = sum_by_type(Expense.IslemTipi.AVANS_ALINDI)
        avans_iade = sum_by_type(Expense.IslemTipi.AVANS_IADE)
        masraf = sum_by_type(Expense.IslemTipi.MASRAF)
        bakiye = case.devreden_bakiye + avans_alindi - avans_iade - masraf

        return Response(
            {
                "case_id": case.id,
                "as_of": as_of.isoformat() if as_of else None,
                "para_birimi": case.para_birimi,
                "devreden_bakiye": case.devreden_bakiye,
                "avans_alindi_toplam": avans_alindi,
                "avans_iade_toplam": avans_iade,
                "masraf_toplam": masraf,
                "bakiye": bakiye,
            }
        )


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
