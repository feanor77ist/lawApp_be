from django import forms
from .models import Customer, TrainingGroup, Scenario
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.auth.models import User
from django.forms.models import BaseInlineFormSet
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.contrib.auth.forms import UserCreationForm, UserChangeForm


class ScenarioAdminForm(forms.ModelForm):
    class Meta:
        model = Scenario
        fields = '__all__'
        widgets = {
            'initial_message': forms.Textarea(attrs={'rows': 2, 'cols': 60}),
        }

class CustomerAdminForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        users = cleaned_data.get('users')
        mixed_group = cleaned_data.get('mixed_group')

        # mixed_group form verisinde yoksa (örn. sadece kullanıcı ekleme denemesi) instance değerini kullan
        if mixed_group is None and self.instance and self.instance.pk:
            mixed_group = self.instance.mixed_group

        # Karma grup ise veya kullanıcı yoksa kontrolü atla
        if mixed_group or not users:
            return cleaned_data

        conflicting_users = []
        existing_customers = Customer.objects.filter(mixed_group=False).exclude(
            pk=self.instance.pk if self.instance.pk else None
        )

        for user in users:
            if existing_customers.filter(users=user).exists():
                conflicting_users.append(user.username)

        if conflicting_users:
            self.add_error(
                'users',
                f"⚠️ Aşağıdaki kullanıcılar zaten başka müşterilere atanmış: {', '.join(conflicting_users)}"
            )

        return cleaned_data

class TrainingGroupAdminForm(forms.ModelForm):
    users = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),  # Başlangıçta boş
        required=True,
        widget=FilteredSelectMultiple("Kullanıcılar", is_stacked=False),
        label="Katılımcı Kullanıcılar"
    )
    trainers = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),  # Başlangıçta boş
        required=False,
        widget=FilteredSelectMultiple("Eğitmenler", is_stacked=False),
        label="Eğitmenler"
    )

    class Meta:
        model = TrainingGroup
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Mevcut kayıt düzenleniyorsa müşteri bilgisine göre kullanıcıları filtrele
        if self.instance and self.instance.pk and self.instance.customer:
            self.fields['users'].queryset = self.instance.customer.users.all().order_by('-id')
        else:
            self.fields['users'].queryset = User.objects.none()
        
        # Eğitmenler için "Dale Carnegie Akademi" customer'ının kullanıcıları
        try:
            dale_carnegie = Customer.objects.get(name="Dale Carnegie Akademi")
            self.fields['trainers'].queryset = dale_carnegie.users.all().order_by('-id')
        except Customer.DoesNotExist:
            self.fields['trainers'].queryset = User.objects.none()

class ProgramScenarioInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()

        total = Decimal(0)

        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                weight = form.cleaned_data.get('weight_percentage')
                if weight:
                    total += Decimal(weight)

        if round(total, 2) != Decimal("100.00"):
            raise forms.ValidationError(
                f"⚠️ Hatalı Ağırlık: Senaryo ağırlıklarının toplamı {total}. Lütfen toplamı 100 olacak şekilde ayarlayın."
            )


class CustomUserCreationForm(UserCreationForm):
    def clean_username(self):
        username = self.cleaned_data.get("username")
        if username:
            username = username.lower().strip()
            
            try:
                validate_email(username)
            except ValidationError:
                raise ValidationError("⚠️ Username alanı geçerli bir e-posta olmalıdır.")
            
            # Case-insensitive uniqueness kontrolü
            if User.objects.filter(username__iexact=username).exists():
                raise ValidationError(f"⚠️ Bu email adresi ({username}) zaten kayıtlı.")
                
        return username
    
    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name")


class CustomUserChangeForm(UserChangeForm):
    def clean_email(self):
        email = self.cleaned_data.get("email")
        if not email:
            raise ValidationError("⚠️ E-mail alanı boş bırakılamaz.")
        return email

    def clean_username(self):
        username = self.cleaned_data.get("username")
        if username:
            username = username.lower().strip()
            
            try:
                validate_email(username)
            except ValidationError:
                raise ValidationError("⚠️ Username geçerli bir e-posta olmalıdır.")
            
            # Case-insensitive uniqueness kontrolü (mevcut kullanıcı hariç)
            existing = User.objects.filter(username__iexact=username)
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                raise ValidationError(f"⚠️ Bu email adresi ({username}) zaten kayıtlı.")
                
        return username

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get("username")
        email = cleaned_data.get("email")

        if username and email and username != email:
            raise ValidationError("⚠️ Username ve e-mail alanları aynı olmalıdır.")

        return cleaned_data

    class Meta:
        model = User
        fields = "__all__"
