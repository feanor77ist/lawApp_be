from django import forms
from django.core.exceptions import ValidationError

from .models import User


class CustomUserCreationForm(forms.ModelForm):
    """User creation form for admin (email as username)."""

    password1 = forms.CharField(label="Password", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Password confirmation", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "phone_number")

    def clean_password2(self):
        p1 = self.cleaned_data.get("password1")
        p2 = self.cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            raise ValidationError("Passwords don't match")
        return p2

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if user.email and not user.username:
            user.username = user.email
        if commit:
            user.save()
        return user


class CustomUserChangeForm(forms.ModelForm):
    """User change form for admin."""

    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "phone_number", "is_active", "is_staff", "is_superuser")

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get("email")
        username = cleaned_data.get("username")
        if email and not username:
            cleaned_data["username"] = email
        return cleaned_data
