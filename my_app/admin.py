from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import User, CaseFile, ExpenseCategory, Expense, Document, ChatSession, ChatMessage
from .forms import CustomUserCreationForm, CustomUserChangeForm


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    add_form = CustomUserCreationForm
    form = CustomUserChangeForm
    model = User

    list_display = ("email", "first_name", "last_name", "phone_number", "is_staff", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active")
    ordering = ("-date_joined",)
    search_fields = ("email", "first_name", "last_name", "phone_number")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "phone_number")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "first_name", "last_name", "phone_number", "password1", "password2", "is_staff", "is_superuser", "is_active"),
            },
        ),
    )


@admin.register(CaseFile)
class CaseFileAdmin(admin.ModelAdmin):
    list_display = ("dosya_adi", "esas_no", "durum", "acilis_tarihi", "kapanis_tarihi", "created_by")
    list_filter = ("durum", "acilis_tarihi", "kapanis_tarihi")
    search_fields = ("dosya_adi", "esas_no", "karar_no", "muvekkil_ad_unvan", "karsi_taraf_ad_unvan")
    autocomplete_fields = ("created_by",)


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("case", "islem_tarihi", "islem_tipi", "tutar", "para_birimi", "created_by")
    list_filter = ("islem_tipi", "receipt_type", "odeme_yapan", "para_birimi", "islem_tarihi")
    search_fields = ("case__dosya_adi", "case__esas_no", "aciklama")
    autocomplete_fields = ("case", "kategori", "created_by")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "file_type", "created_by", "case", "indexed", "text_extracted", "created_at")
    list_filter = ("file_type", "indexed", "text_extracted", "created_at")
    search_fields = ("title", "file_url")
    autocomplete_fields = ("created_by", "case")


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "mode", "case", "created_at", "updated_at")
    list_filter = ("mode", "created_at", "updated_at")
    search_fields = ("user__email", "case__dosya_adi", "title")
    autocomplete_fields = ("user", "case")


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "created_at")
    list_filter = ("created_at",)
    search_fields = ("user_query", "ai_response")
    autocomplete_fields = ("session",)
