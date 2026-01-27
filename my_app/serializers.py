from rest_framework import serializers
from django.db import models
from .models import Scenario, UserEntry, UserChatHistory, Customer, Program, TrainingGroup, GroupUser, ProgramScenario, EvaluationReport
from django.contrib.auth.models import User
from decimal import Decimal

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

class UserManageSerializer(serializers.ModelSerializer):
    username = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'username']

    def validate_email(self, value):
        if not value:
            raise serializers.ValidationError("E-posta zorunludur.")
        return value.lower().strip()

    def validate(self, attrs):
        email = attrs.get('email') or (self.instance.email if self.instance else None)
        if not email:
            raise serializers.ValidationError({"email": "E-posta zorunludur."})
        email = email.lower().strip()
        # Case-insensitive benzersizlik
        qs = User.objects.filter(username__iexact=email)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError({"email": "Bu e-posta zaten kullanılıyor."})
        attrs['email'] = email
        attrs['username'] = email
        return attrs

    def create(self, validated_data):
        user = User(
            email=validated_data['email'],
            username=validated_data['username'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
        )
        # Kullanıcı reset akışına girebilsin diye rastgele kullanabilir parola set et
        import secrets
        user.set_password(secrets.token_urlsafe(16))
        user.save()
        return user

class ScenarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Scenario
        fields = '__all__'

class UserChatHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = UserChatHistory
        fields = '__all__'
 
class UserEntrySerializer(serializers.ModelSerializer):
    chats = UserChatHistorySerializer(many=True, read_only=True)
    entry_name = serializers.SerializerMethodField()
    bg_image = serializers.SerializerMethodField()
    initial_message = serializers.SerializerMethodField()
    group_name = serializers.SerializerMethodField()
    class Meta:
        model = UserEntry
        fields = ['id', 'user', 'entry_id', 'scenario', "entry_name", 'created_at', 'is_locked', 'chats', 'bg_image', 'initial_message', 'group_name', 'training_group']

    def get_entry_name(self, obj):
        return obj.scenario.name if obj.scenario else "Yeni Senaryo"

    def get_bg_image(self, obj):   
        request = self.context.get("request")
        if obj.scenario and obj.scenario.bg_image:
            return request.build_absolute_uri(obj.scenario.bg_image.url) if request else obj.scenario.bg_image.url
        return None

    def get_initial_message(self, obj):
        return obj.scenario.initial_message if obj.scenario and obj.scenario.initial_message else None

    def get_group_name(self, obj):
        return obj.training_group.name if obj.training_group else None

class CustomerSerializer(serializers.ModelSerializer):
    users = UserSerializer(many=True, read_only=True)
    user_ids = serializers.PrimaryKeyRelatedField(
        many=True, write_only=True, source='users', queryset=User.objects.all()
    )

    class Meta:
        model = Customer
        fields = ['id', 'name', 'email', 'logo', 'created_at', 'users', 'user_ids']

class ProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = Program
        fields = '__all__'

class GroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingGroup
        fields = '__all__'
        read_only_fields = ['trainers']

class GroupUserSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        training_group = attrs.get('training_group') or getattr(self.instance, 'training_group', None)
        user = attrs.get('user') or getattr(self.instance, 'user', None)
        if training_group and user:
            customer = training_group.customer
            if not user.customer.filter(id=customer.id).exists():
                raise serializers.ValidationError("Kullanıcı bu müşteriye bağlı değil.")
        return attrs

    class Meta:
        model = GroupUser
        fields = '__all__'

class ProgramScenarioSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        program = attrs.get('program') or (self.instance.program if self.instance else None)
        weight = attrs.get('weight_percentage') or (self.instance.weight_percentage if self.instance else None)
        if program and weight is not None:
            # Programdaki mevcut kayıtların toplamı (kendisi hariç)
            existing_total = (
                ProgramScenario.objects
                .filter(program=program)
                .exclude(pk=self.instance.pk if self.instance else None)
                .aggregate(total=models.Sum('weight_percentage'))
                .get('total') or Decimal('0')
            )
            total = existing_total + Decimal(weight)
            if total > Decimal("100.00"):
                raise serializers.ValidationError(
                    f"⚠️ Hatalı Ağırlık: Senaryo ağırlıklarının toplamı {total}. Lütfen toplamı 100 olacak şekilde ayarlayın."
                )
        return attrs

    class Meta:
        model = ProgramScenario
        fields = '__all__'

class EvaluationReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvaluationReport
        fields = '__all__'
        