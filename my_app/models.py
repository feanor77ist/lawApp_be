from django.db import models
from django.contrib.auth.models import User

# Create your models here.
User.__str__ = lambda self: (
    f"{self.get_full_name()} ({self.username}) | "
    f"{(self.customer.filter(mixed_group=False).first() or self.customer.first()).name if self.customer.exists() else 'Müşteri Yok'}"
)

ai_levels = [("employee", "Çalışan"), ("manager", "Yönetici"), ("highLevel", "Üst Düzey Yönetici"), ("customer", "Müşteri")]
user_levels = [("employee", "Çalışan"), ("manager", "Yönetici"), ("highLevel", "Üst Düzey Yönetici")]
hardness_levels = [("veryEasy", "Çok Kolay"), ("easy", "Kolay"), ("medium", "Orta"), ("hard", "Zor"), ("veryHard", "Çok Zor")]
EVALUATION_CHOICES = [("pre", "Ön"), ("post", "Son")]
VOICE_CHOICES = [
    ("alloy", "Alloy"),
    ("ash", "Ash"),
    ("ballad", "Ballad"),
    ("coral", "Coral"),
    ("echo", "Echo"),
    ("fable", "Fable"),
    ("nova", "Nova"),
    ("onyx", "Onyx"),
    ("sage", "Sage"),
    ("shimmer", "Shimmer"),
]

class Customer(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Müşteri İsmi", db_index=True)
    email = models.EmailField(max_length=100, verbose_name="E-posta", blank=True, null=True)
    users = models.ManyToManyField(User, verbose_name="Kullanıcılar", related_name="customer", blank=True)
    mixed_group = models.BooleanField(default=False, verbose_name="Karma Grup", help_text="Farklı müşterilere kayıtlı kullanıcıları atamak için bu seçeneği etkinleştirin.")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Oluşturulma Tarihi")
    logo = models.ImageField(upload_to='logos/', verbose_name="Logo", blank=True, null=True, help_text="Müşteri logosu yükleyin. (PNG, JPG formatında)")

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        try:
            this = Customer.objects.get(id=self.id)
            if this.logo and self.logo != this.logo:
                this.logo.delete(save=False)
        except Customer.DoesNotExist:
            pass
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.logo:
            self.logo.delete(save=False)
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.name
    
class Scenario(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Eğitim Senaryosu İsmi", db_index=True)
    description = models.TextField(verbose_name="Eğitim Senaryosu Açıklaması", help_text="Eğitim senaryosu hakkında kısa bir açıklama yazın.")
    initial_message = models.TextField(verbose_name="İlk Kullanıcı Mesajı", blank=True, null=True, help_text="Simülasyon açılışında kullanıcının göndereceği ilk mesaj. Boş bırakılırsa varsayılan mesaj kullanılır.")
    scenario_document = models.FileField(upload_to='documents/', verbose_name="Eğitim Senaryosu Dokümanı", help_text="PDF veya DOCX formatında olmalıdır.")
    review_document = models.FileField(upload_to='documents/', verbose_name="Eğitim Senaryosu Değerlendirme Dokümanı", help_text="PDF veya DOCX formatında olmalıdır.")
    bg_image = models.ImageField(upload_to='backgrounds/', verbose_name="Arka Plan Resmi", blank=True, null=True, help_text="Eğitim senaryosu için arka plan resmi yükleyin. (PNG, JPG formatında)")
    ai_level = models.CharField(max_length=100, verbose_name="AI Seviyesi", choices=ai_levels)
    user_level = models.CharField(max_length=100, verbose_name="Kullanıcı Seviyesi", choices=user_levels)
    hardness = models.CharField(max_length=100, verbose_name="Zorluk Seviyesi", choices=hardness_levels)
    voice = models.CharField(max_length=20, verbose_name="TTS Ses Profili", choices=VOICE_CHOICES, default="nova", help_text="Bu senaryo için kullanılacak TTS sesi (OpenAI destekli)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Oluşturulma Tarihi")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="scenarios", verbose_name="Oluşturan")

    def save(self, *args, **kwargs):
        try:
            this = Scenario.objects.get(id=self.id)
            if this.scenario_document and self.scenario_document != this.scenario_document:
                this.scenario_document.delete(save=False)
            if this.review_document and self.review_document != this.review_document:
                this.review_document.delete(save=False)
            if this.bg_image and self.bg_image != this.bg_image:
                this.bg_image.delete(save=False)
        except Scenario.DoesNotExist:
            pass
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.scenario_document:
            self.scenario_document.delete(save=False)
        if self.review_document:
            self.review_document.delete(save=False)
        if self.bg_image:
            self.bg_image.delete(save=False)
        super().delete(*args, **kwargs)

    def __str__(self):
        return self.name
    
class Program(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Program İsmi", db_index=True)
    scenarios = models.ManyToManyField(Scenario, through="ProgramScenario", verbose_name="Eğitim Senaryoları")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Oluşturulma Tarihi")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="programs", verbose_name="Oluşturan")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

class ProgramScenario(models.Model):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, verbose_name="Program", db_index=True)
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, verbose_name="Eğitim Senaryosu", db_index=True, help_text="Programa eklenecek eğitim senaryolarını seçin.")
    weight_percentage = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Ağırlık Yüzdesi", help_text="Senaryonun program içindeki ağırlığını belirtin. (0-100)")
    release_date = models.DateField(verbose_name="Yayın Tarihi", blank=True, null=True, help_text="Senaryonun yayınlanacağı tarih")
    training_date = models.DateField(verbose_name="Eğitim Tarihi", blank=True, null=True, help_text="Senaryonun eğitim tarihi")
    close_date = models.DateField(verbose_name="Kapanış Tarihi", blank=True, null=True, help_text="Senaryonun kapanış tarihi")
    max_attempts = models.PositiveIntegerField(verbose_name="Maksimum Deneme Sayısı", default=200, help_text="Senaryonun maksimum deneme sayısını belirtin.")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="program_scenarios_created", verbose_name="Oluşturan")

    class Meta:
        unique_together = ('program', 'scenario')
        
    def __str__(self):
        return f"{self.program} | {self.scenario}"
    
class TrainingGroup(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Grup İsmi", db_index=True)
    program = models.ForeignKey(Program, on_delete=models.CASCADE, verbose_name="Program", db_index=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, verbose_name="Müşteri", db_index=True)
    users = models.ManyToManyField(
        User,
        verbose_name="Kullanıcılar",
        related_name="training_groups",
        through="GroupUser",
        through_fields=("training_group", "user"),
    )
    trainers = models.ManyToManyField(User, verbose_name="Eğitmenler", related_name="trainer_groups", blank=True, help_text="Bu eğitim grubunun eğitmen(ler)ini seçin.")
    group_date = models.DateField(verbose_name="Eğitim Tarihi", blank=True, null=True)
    progress = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="İlerleme Yüzdesi (Ortalama)", default=0.00)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="training_groups_created", verbose_name="Oluşturan")

    def __str__(self):
        return f"{self.name} | {self.program}"
    
class GroupUser(models.Model):
    training_group = models.ForeignKey(TrainingGroup, on_delete=models.CASCADE, verbose_name="Grup", db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Katılımcı", db_index=True)
    progress = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="İlerleme Yüzdesi", default=0.00)
    total_score = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Ortalama Değerlendirme Puanı", help_text="Katılımcının Eğitim Programındaki Senaryolardan Aldığı Ağırlıklı Ortalama Puanı", blank=True, null=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="group_users_created", verbose_name="Oluşturan")
    
    class Meta:
        unique_together = ('training_group', 'user')
        ordering = ['user__username']
        
    def __str__(self):
        return f"{self.training_group} | {self.user.username}"
    
class EvaluationReport(models.Model):
    type = models.CharField(max_length=10, choices=EVALUATION_CHOICES, verbose_name="Değerlendirme Türü", blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Kullanıcı", db_index=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, verbose_name="Müşteri", db_index=True, null=True, blank=True)
    training_group = models.ForeignKey(TrainingGroup, on_delete=models.CASCADE, verbose_name="Grup", db_index=True)
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, verbose_name="Eğitim Senaryosu", db_index=True)
    report = models.TextField(verbose_name="Değerlendirme Raporu")
    score = models.IntegerField(verbose_name="Değerlendirme Puanı")
    average_score = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Ortalama Puan", help_text="Kullanıcının bu senaryo için tüm denemelerinin ortalaması", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Oluşturulma Tarihi")
    attempt_count = models.PositiveIntegerField(default=1, verbose_name="Deneme Sayısı", help_text="Bu raporun kaçıncı deneme olduğunu gösterir.")

    def save(self, *args, **kwargs):
        """Eğer average_score None ise (eski kayıt veya yeni kayıt), score değerine eşitle"""
        if self.average_score is None and self.score is not None:
            from decimal import Decimal
            self.average_score = Decimal(self.score)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.user.username} - {self.training_group} - {self.scenario}'

class UserEntry(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="Kullanıcı", db_index=True)
    entry_id = models.CharField(max_length=100, unique=True, db_index=True)
    training_group = models.ForeignKey(TrainingGroup, on_delete=models.CASCADE, verbose_name="Grup", db_index=True)
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, verbose_name="Eğitim Senaryosu", db_index=True, related_name="entries")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Oluşturulma Tarihi")
    is_locked = models.BooleanField(default=False, verbose_name="Kilitli mi")

    def __str__(self):
        return f"{self.user.username} - {self.scenario}"

class UserChatHistory(models.Model):
    entry = models.ForeignKey(UserEntry, on_delete=models.CASCADE, related_name="chats", db_index=True)
    user_query = models.TextField()
    gpt_response = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    def __str__(self):
        return f"{self.entry.scenario} - {self.timestamp}"
    
    class Meta: 
        ordering = ["timestamp"]
