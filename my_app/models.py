from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email must be set")
        email = self.normalize_email(email)
        username = email  # username fiilen kullanılmaz; email'e eşitlenir
        user = self.model(email=email, username=username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Özel kullanıcı modeli.
    - Giriş ve kayıt e-posta ile yapılır.
    - username alanı fiilen kullanılmaz; e-posta ile aynı değere ayarlanır.
    """

    username = models.CharField(max_length=150, unique=True, blank=True, help_text="Otomatik olarak e-posta ile aynı değere set edilir.")
    email = models.EmailField(unique=True, verbose_name="E-posta")
    phone_number = models.CharField(max_length=20, blank=True, null=True, verbose_name="Telefon", help_text="İsteğe bağlı, Google veya klasik kayıtta tutulabilir.")
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    objects = UserManager()

    class Meta:
        verbose_name = "Kullanıcı"
        verbose_name_plural = "Kullanıcılar"

    def save(self, *args, **kwargs):
        # username fiilen kullanılmıyor; e-postayı kopyala
        if self.email and not self.username:
            self.username = self.email
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_full_name() or self.email


class CaseFile(models.Model):
    """Dava dosyası kaydı."""

    class Status(models.TextChoices):
        OPEN = "ACIK", "Açık"
        CLOSED = "KAPALI", "Kapalı"
        PENDING = "ASKIDA", "Askıda"

    dosya_kodu = models.CharField(max_length=100, blank=True, null=True, verbose_name="Dosya Kodu")
    dosya_adi = models.CharField(max_length=200, verbose_name="Dosya Adı")
    dosya_turu = models.CharField(max_length=50, verbose_name="Dosya Türü", default="DAVA")
    yargi_mercii = models.CharField(max_length=200, verbose_name="Yargı Mercii / Birim")
    esas_no = models.CharField(max_length=100, verbose_name="Esas No")
    karar_no = models.CharField(max_length=100, verbose_name="Karar No", blank=True, null=True)
    konu_ozeti = models.TextField(verbose_name="Konu Özeti", blank=True, null=True)
    durum = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, verbose_name="Durum")
    acilis_tarihi = models.DateField(verbose_name="Açılış Tarihi")
    kapanis_tarihi = models.DateField(verbose_name="Kapanış Tarihi", blank=True, null=True)
    muvekkil_ad_unvan = models.CharField(max_length=200, verbose_name="Müvekkil Ad/Unvan")
    karsi_taraf_ad_unvan = models.CharField(max_length=200, verbose_name="Karşı Taraf Ad/Unvan")
    para_birimi = models.CharField(max_length=10, default="TRY", verbose_name="Para Birimi")
    devreden_bakiye = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name="Devreden Bakiye")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="case_files",
        verbose_name="Oluşturan",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.dosya_adi} ({self.esas_no})"


class ExpenseCategory(models.Model):
    """Masraf kategorisi sözlüğü."""

    name = models.CharField(max_length=100, unique=True, verbose_name="Kategori")
    is_active = models.BooleanField(default=True, verbose_name="Aktif mi?")

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Expense Categories"

    def __str__(self):
        return self.name


class Expense(models.Model):
    """Masraf / Avans kayıtları."""

    class IslemTipi(models.TextChoices):
        MASRAF = "MASRAF", "Masraf"
        AVANS_ALINDI = "AVANS_ALINDI", "Avans Alındı"
        AVANS_IADE = "AVANS_IADE", "Avans İade"

    class ReceiptType(models.TextChoices):
        BELGELI = "BELGELI", "Belgeli"
        BELGESIZ = "BELGESIZ", "Belgesiz"

    class OdemeYapan(models.TextChoices):
        OFIS = "OFIS", "Ofis"
        MUVEKKIL = "MUVEKKIL", "Müvekkil"

    case = models.ForeignKey(CaseFile, on_delete=models.CASCADE, related_name="expenses", verbose_name="Dava Dosyası")
    islem_tarihi = models.DateField(verbose_name="İşlem Tarihi")
    islem_tipi = models.CharField(max_length=20, choices=IslemTipi.choices, verbose_name="İşlem Tipi")
    kategori = models.ForeignKey(ExpenseCategory, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Kategori")
    aciklama = models.TextField(verbose_name="Açıklama", blank=True, null=True)
    receipt_type = models.CharField(max_length=10, choices=ReceiptType.choices, blank=True, null=True, verbose_name="Belge Tipi")
    tutar = models.DecimalField(max_digits=14, decimal_places=2, verbose_name="Tutar")
    para_birimi = models.CharField(max_length=10, default="TRY", verbose_name="Para Birimi")
    odeme_yapan = models.CharField(max_length=10, choices=OdemeYapan.choices, blank=True, null=True, verbose_name="Ödeyen")
    muvekkile_yansit = models.BooleanField(default=False, verbose_name="Müvekkile Yansıt")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="expenses_created", verbose_name="Oluşturan")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-islem_tarihi", "-created_at"]

    def __str__(self):
        return f"{self.case.dosya_adi} | {self.get_islem_tipi_display()} | {self.tutar} {self.para_birimi}"


class Document(models.Model):
    """Kullanıcı dokümanları (metadata + R2 depolama yolu)."""

    class FileType(models.TextChoices):
        PDF = "pdf", "PDF"
        DOCX = "docx", "DOCX"
        TXT = "txt", "TXT"

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents", verbose_name="Oluşturan")
    case = models.ForeignKey(CaseFile, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents", verbose_name="Dava Dosyası")
    title = models.CharField(max_length=200, verbose_name="Başlık")
    file_url = models.CharField(max_length=500, verbose_name="Dosya Yolu (R2)", help_text="Cloud storage path")
    file_type = models.CharField(max_length=10, choices=FileType.choices, verbose_name="Dosya Türü")
    text_extracted = models.BooleanField(default=False, verbose_name="Metin Çıkarıldı mı?")
    indexed = models.BooleanField(default=False, verbose_name="Vektör Indexlendi mi?")
    metadata = models.JSONField(blank=True, null=True, verbose_name="Metadata")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class ChatSession(models.Model):
    """
    Sohbet oturumu.
    Kullanıcının başlattığı bir RAG sohbet akışını temsil eder.
    """

    class ChatMode(models.TextChoices):
        DECISIONS = "decisions", "Kararlar"
        USER_DOCS = "user_docs", "Kullanıcı Dokümanları"
        HYBRID = "hybrid", "Hibrit"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_sessions", verbose_name="Kullanıcı")
    mode = models.CharField(max_length=20, choices=ChatMode.choices, default=ChatMode.DECISIONS, verbose_name="Sohbet Modu")
    case = models.ForeignKey(CaseFile, on_delete=models.SET_NULL, null=True, blank=True, related_name="chat_sessions", verbose_name="İlişkili Dava", help_text="Opsiyonel: Sohbet belirli bir dava dosyasıyla ilişkilendirilebilir")
    title = models.CharField(max_length=200, blank=True, null=True, verbose_name="Başlık")
    filters = models.JSONField(blank=True, null=True, verbose_name="Filtreler", help_text="Arama filtreleri (daire, tarih vb.)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user.username} - {self.get_mode_display()} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class ChatMessage(models.Model):
    """
    Sohbet mesajı.
    Kullanıcı sorgusu ve AI yanıtını saklar.
    """

    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name="messages", verbose_name="Oturum")
    user_query = models.TextField(verbose_name="Kullanıcı Sorgusu")
    ai_response = models.TextField(blank=True, null=True, verbose_name="AI Yanıtı")
    sources = models.JSONField(blank=True, null=True, verbose_name="Kaynaklar", help_text="RAG tarafından kullanılan kaynak chunk bilgileri")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.session.id} - {self.created_at.strftime('%H:%M:%S')}"
