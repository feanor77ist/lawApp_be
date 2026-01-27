from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS, BasePermission
from rest_framework.exceptions import PermissionDenied
from django.db.models import Avg
from .models import Scenario, UserEntry, Customer, Program, TrainingGroup, GroupUser, ProgramScenario, EvaluationReport
from .serializers import (
    ScenarioSerializer, UserEntrySerializer, CustomerSerializer, 
    ProgramSerializer, GroupSerializer, GroupUserSerializer, ProgramScenarioSerializer, EvaluationReportSerializer,
    UserManageSerializer
)

from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.authtoken.models import Token
import uuid, tempfile
from datetime import date
from rest_framework.decorators import api_view, permission_classes
from django.contrib.auth import get_user_model, authenticate
from django.views.decorators.csrf import ensure_csrf_cookie
from django.http import JsonResponse, FileResponse
from django.conf import settings
from django.utils import timezone
from openai import OpenAI
from pathlib import Path
from django.middleware.csrf import get_token
from django.core.cache import cache
from django.contrib.auth import get_user_model
import json


class CustomPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100

def get_primary_customer(user):
    if not user or not user.is_authenticated:
        return None
    return user.customer.filter(mixed_group=False).first() or user.customer.first()

class ModelActionPermission(BasePermission):
    """
    Yazma işlemleri için model izinlerini kontrol eder; GET akışına dokunmaz.
    """
    perms_map = {
        'POST': 'add',
        'PUT': 'change',
        'PATCH': 'change',
        'DELETE': 'delete',
    }

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True

        action = self.perms_map.get(request.method)
        if not action:
            return True

        model = None
        if hasattr(view, 'queryset') and getattr(view.queryset, 'model', None):
            model = view.queryset.model
        else:
            try:
                serializer_class = view.get_serializer_class()
                model = getattr(getattr(serializer_class, 'Meta', None), 'model', None)
            except Exception:
                model = None

        if not model:
            return True

        perm_code = f"{model._meta.app_label}.{action}_{model._meta.model_name}"
        return request.user.has_perm(perm_code)

class CustomAuthToken(ObtainAuthToken):
    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        password = request.data.get('password')
        
        User = get_user_model()
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({"error": "Geçersiz e-posta veya şifre."}, status=400)
        
        user = authenticate(username=user.username, password=password)
        if not user:
            return Response({"error": "Geçersiz e-posta veya şifre."}, status=400)
        
        token, created = Token.objects.get_or_create(user=user)
        permissions = list(user.get_all_permissions())

        customer_logo_url = None
        if user.customer.exists():
            customer = user.customer.filter(mixed_group=False).first() or user.customer.first()
            if customer and customer.logo:
                customer_logo_url = request.build_absolute_uri(customer.logo.url)

        return Response({
            "token": token.key,
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "permissions": permissions,
            "is_superuser": user.is_superuser,
            "customer_logo": customer_logo_url,
            "customer_id": customer.id,
        })

class ScenarioViewSet(viewsets.ModelViewSet):
    queryset = Scenario.objects.all().order_by('id')
    serializer_class = ScenarioSerializer
    permission_classes = [IsAuthenticated, ModelActionPermission]
    pagination_class = CustomPagination

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        return qs.filter(created_by=user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

class UserEntryListAPI(APIView):
    """
    Kullanıcının tüm entry'lerini ve chat geçmişini listeleyen API.
    - Belirli bir entry_id verilirse, sadece o entry'yi döndürür.
    - Aksi halde kullanıcının tüm entry'lerini döndürür.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, entry_id=None, *args, **kwargs):
        if entry_id:
            # Belirli bir entry_id için filtrele
            try:
                entry = UserEntry.objects.get(entry_id=entry_id, user=request.user)
                serializer = UserEntrySerializer(entry, context={"request": request})
                return Response(serializer.data, status=status.HTTP_200_OK)
            except UserEntry.DoesNotExist:
                return Response({'error': 'Entry bulunamadı.'}, status=status.HTTP_404_NOT_FOUND)
        else:
            # Kullanıcının tüm entry'lerini al
            entries = UserEntry.objects.filter(user=request.user).order_by('-created_at')
            paginator = CustomPagination()
            result_page = paginator.paginate_queryset(entries, request)
            serializer = UserEntrySerializer(result_page, many=True, context={"request": request})
            return paginator.get_paginated_response(serializer.data)

class ChatbotAPI(APIView):
    """
    Chatbot entry'lerinin yönetildiği API endpoint
    """
    permission_classes = [IsAuthenticated] 
    
    def get(self, request, *args, **kwargs):
        # GET isteği için basit bir yanıt döndürüyoruz
        return Response({'message': 'Bu endpoint POST isteği bekler.'}, status=200)
    
    def post(self, request, *args, **kwargs):
        user = request.user
        entry_id = str(uuid.uuid4())
        scenario_name = request.data.get("scenario")
        group_id = request.data.get("group")

        if not group_id:
            return Response({"error": "Grup bilgisi eksik."}, status=400)
        
        try:
            training_group = TrainingGroup.objects.get(id=group_id)
        except TrainingGroup.DoesNotExist:
            return Response({"error": "Grup bulunamadı."}, status=404)
        
        # Kullanıcının bu grubun users veya trainers listesinde olup olmadığını kontrol et
        if user not in training_group.users.all() and user not in training_group.trainers.all():
            return Response({"error": "Bu kullanıcı bu gruba ait değil."}, status=403)

        if not scenario_name:
            return Response({"error": "Senaryo adı belirtilmedi."}, status=400)

        try:
            scenario = Scenario.objects.get(name=scenario_name)
        except Scenario.DoesNotExist:
            return Response({"error": "Senaryo bulunamadı."}, status=404)
        
        UserEntry.objects.create(user=user, entry_id=entry_id, scenario=scenario, training_group=training_group)
        return Response({"entry_id": entry_id}, status=201)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def available_scenarios_api(request):
    user = request.user
    today = date.today()
    active_scenarios = []
    upcoming_scenarios = []
    
    # Katılımcı ve eğitmen gruplarını topla
    participant_groups = TrainingGroup.objects.filter(users=user).select_related("program")
    trainer_groups = TrainingGroup.objects.filter(trainers=user).select_related("program")
    
    # Tüm grupları işle (katılımcı ve eğitmen)
    for group in list(participant_groups) + list(trainer_groups):
        is_trainer = group in trainer_groups
        
        program_scenarios = ProgramScenario.objects.filter(
            program=group.program,
            release_date__isnull=False,
        ).select_related("scenario").order_by("release_date")

        for ps in program_scenarios:
            scenario_data = {
                "scenario_id": ps.scenario.id,
                "scenario_name": ps.scenario.name,
                "description": ps.scenario.description,
                "initial_message": ps.scenario.initial_message,
                "group_id": group.id,
                "group_name": group.name,
                "program": group.program.name,
                "release_date": ps.release_date,
                "bg_image": request.build_absolute_uri(ps.scenario.bg_image.url) if ps.scenario.bg_image else None,
            }
            
            if is_trainer:
                scenario_data["role"] = "trainer"

            # Yakında başlayacaklar
            if ps.release_date > today:
                upcoming_scenarios.append(scenario_data)
                continue

            # Aktif olanlar (pre/post)
            evaluation_phase = None
            report = None

            if ps.training_date and ps.release_date <= today <= ps.training_date:
                evaluation_phase = "pre"
            elif ps.training_date and ps.close_date and ps.training_date < today <= ps.close_date:
                evaluation_phase = "post"
            elif not ps.training_date and ps.close_date and ps.release_date <= today < ps.close_date:
                # Asenkron eğitim: önce pre, pre raporu varsa post
                pre_report = EvaluationReport.objects.filter(
                    user=user,
                    training_group=group,
                    scenario=ps.scenario,
                    type="pre"
                ).first()
                evaluation_phase = "post" if pre_report else "pre"
                if evaluation_phase == "pre":
                    report = pre_report
            else:
                continue  # Aktif değil, atla

            scenario_data["evaluation_phase"] = evaluation_phase

            # Attempt sınırı kontrolü (sadece katılımcılar için)
            if not is_trainer:
                if report is None:
                    report = EvaluationReport.objects.filter(
                        user=user,
                        training_group=group,
                        scenario=ps.scenario,
                        type=evaluation_phase
                    ).first()

                used_attempts = report.attempt_count if report else 0
                max_attempts = ps.max_attempts
                remaining_attempts = max(0, max_attempts - used_attempts)

                if used_attempts >= max_attempts:
                    continue  # Deneme hakkı dolmuş → senaryo gönderilmez

                scenario_data.update({
                    "used_attempts": used_attempts,
                    "remaining_attempts": remaining_attempts,
                    "max_attempts": max_attempts,
                })

            active_scenarios.append(scenario_data)

    return Response({"active_scenarios": active_scenarios, "upcoming_scenarios": upcoming_scenarios})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def trainer_group_reports_api(request):
    """
    Eğitmenlerin eğitim grubundaki kullanıcıların raporlarını görüntülemesi için endpoint.
    Sadece trainers field'ında olan kullanıcılar erişebilir.
    release_date <= today <= close_date olan senaryoları döndürür.
    """
    user = request.user
    today = date.today()
    
    # Eğitmenin trainer olduğu grupları al (reverse relation kullanarak)
    trainer_groups = user.trainer_groups.all().select_related("program", "customer").prefetch_related("groupuser_set__user")
    
    if not trainer_groups.exists():
        # Trainer olmayan kullanıcılar için boş liste döndür
        return Response({"groups": []}, status=200)
    
    groups_data = []
    
    for group in trainer_groups:
        # Customer bilgisi
        customer_data = {
            "id": group.customer.id,
            "name": group.customer.name,
        }
        
        # Grup içindeki tüm kullanıcıları al (GroupUser üzerinden)
        group_users = GroupUser.objects.filter(
            training_group=group
        ).select_related("user").order_by("user__username")
        
        users_data = []
        
        for group_user in group_users:
            user_obj = group_user.user
            
            # Program senaryolarını al ve filtrele (release_date <= today <= close_date)
            program_scenarios = ProgramScenario.objects.filter(
                program=group.program,
                release_date__isnull=False,
                close_date__isnull=False,
            ).filter(
                release_date__lte=today,
                close_date__gte=today
            ).select_related("scenario").order_by("release_date")
            
            scenarios_data = []
            
            for ps in program_scenarios:
                # En güncel raporları al
                pre_report = (
                    EvaluationReport.objects
                    .filter(
                        user=user_obj,
                        training_group=group,
                        scenario=ps.scenario,
                        type="pre"
                    )
                    .order_by('-created_at')
                    .first()
                )
                
                post_report = (
                    EvaluationReport.objects
                    .filter(
                        user=user_obj,
                        training_group=group,
                        scenario=ps.scenario,
                        type="post"
                    )
                    .order_by('-created_at')
                    .first()
                )
                
                # Pre rapor bilgileri
                pre_report_data = None
                if pre_report:
                    pre_report_data = {
                        "score": pre_report.score,
                        "date": pre_report.created_at.date().isoformat(),
                        "attempt_count": pre_report.attempt_count,
                        "report_id": pre_report.id,
                        "report": pre_report.report,
                    }
                
                # Post rapor bilgileri
                post_report_data = None
                if post_report:
                    post_report_data = {
                        "score": post_report.score,
                        "date": post_report.created_at.date().isoformat(),
                        "attempt_count": post_report.attempt_count,
                        "report_id": post_report.id,
                        "report": post_report.report,
                    }
                
                # Gelişim yüzdesi hesapla
                improvement_percentage = None
                if pre_report and post_report:
                    pre_score_val = pre_report.score or 0
                    post_score_val = post_report.score or 0
                    if pre_score_val > 0:
                        improvement_percentage = round(((post_score_val - pre_score_val) / pre_score_val) * 100, 2)
                    else:
                        improvement_percentage = 0
                
                scenario_data = {
                    "scenario_id": ps.scenario.id,
                    "scenario_name": ps.scenario.name,
                    "release_date": ps.release_date.isoformat() if ps.release_date else None,
                    "pre_report": pre_report_data,
                    "post_report": post_report_data,
                    "improvement_percentage": improvement_percentage,
                }
                
                scenarios_data.append(scenario_data)
            
            # Eğer scenarios_data boşsa, bu kullanıcıyı ekleme
            if not scenarios_data:
                continue
            
            # Kullanıcı bilgileri
            # total_score_display: progress == 100 ise total_score, değilse None
            total_score_display = None
            if group_user.progress == 100 and group_user.total_score:
                total_score_display = float(group_user.total_score)
            
            user_data = {
                "user_id": user_obj.id,
                "username": user_obj.username,
                "first_name": user_obj.first_name,
                "last_name": user_obj.last_name,
                "email": user_obj.email,
                "progress": float(group_user.progress),
                "total_score": total_score_display,
                "scenarios": scenarios_data,
            }
            
            users_data.append(user_data)
        
        # Eğer users_data boşsa, bu grubu ekleme
        if not users_data:
            continue
        
        # Grup istatistikleri
        participant_count = group.groupuser_set.count()
        progress = float(group.progress or 0)
        avg_total_score = GroupUser.objects.filter(training_group=group).aggregate(avg=Avg('total_score'))['avg']
        avg_total_score = float(avg_total_score) if avg_total_score else 0.0
        
        group_data = {
            "group_id": group.id,
            "group_name": group.name,
            "program_name": group.program.name,
            "customer": customer_data,
            "participant_count": participant_count,
            "progress": progress,
            "avg_total_score": avg_total_score,
            "users": users_data,
        }
        
        groups_data.append(group_data)
    
    return Response({"groups": groups_data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def user_reports_api(request):
    """
    Katılımcının dahil olduğu gruplardaki senaryolar için kendi raporlarını döndürür.
    release_date <= today olan tüm senaryolar gelir; close_date dikkate alınmaz.
    """
    user = request.user
    today = date.today()

    # Kullanıcının grup üyeliklerini al
    group_users = (
        GroupUser.objects
        .filter(user=user)
        .select_related("training_group__program", "training_group__customer")
    )

    if not group_users.exists():
        return Response({"groups": []}, status=200)

    groups_data = []

    for group_user in group_users:
        group = group_user.training_group

        # Program senaryoları: release_date <= today, close_date serbest
        program_scenarios = (
            ProgramScenario.objects
            .filter(
                program=group.program,
                release_date__isnull=False,
                release_date__lte=today,
            )
            .select_related("scenario")
            .order_by("release_date")
        )

        scenarios_data = []

        for ps in program_scenarios:
            pre_report = (
                EvaluationReport.objects
                .filter(
                    user=user,
                    training_group=group,
                    scenario=ps.scenario,
                    type="pre",
                )
                .order_by("-created_at")
                .first()
            )

            post_report = (
                EvaluationReport.objects
                .filter(
                    user=user,
                    training_group=group,
                    scenario=ps.scenario,
                    type="post",
                )
                .order_by("-created_at")
                .first()
            )

            pre_report_data = None
            if pre_report:
                pre_report_data = {
                    "score": pre_report.score,
                    "date": pre_report.created_at.date().isoformat(),
                    "attempt_count": pre_report.attempt_count,
                    "report_id": pre_report.id,
                    "report": pre_report.report,
                }

            post_report_data = None
            if post_report:
                post_report_data = {
                    "score": post_report.score,
                    "date": post_report.created_at.date().isoformat(),
                    "attempt_count": post_report.attempt_count,
                    "report_id": post_report.id,
                    "report": post_report.report,
                }

            improvement_percentage = None
            if pre_report and post_report:
                pre_score_val = pre_report.score or 0
                post_score_val = post_report.score or 0
                if pre_score_val > 0:
                    improvement_percentage = round(((post_score_val - pre_score_val) / pre_score_val) * 100, 2)
                else:
                    improvement_percentage = 0

            scenario_data = {
                "scenario_id": ps.scenario.id,
                "scenario_name": ps.scenario.name,
                "release_date": ps.release_date.isoformat() if ps.release_date else None,
                "pre_report": pre_report_data,
                "post_report": post_report_data,
                "improvement_percentage": improvement_percentage,
            }

            scenarios_data.append(scenario_data)

        # Grup için senaryo yoksa atla
        if not scenarios_data:
            continue

        total_score_display = None
        if group_user.progress == 100 and group_user.total_score:
            total_score_display = float(group_user.total_score)

        group_data = {
            "group_id": group.id,
            "group_name": group.name,
            "program_name": group.program.name,
            "user": {
                "user_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "email": user.email,
                "progress": float(group_user.progress),
                "total_score": total_score_display,
            },
            "scenarios": scenarios_data,
        }

        groups_data.append(group_data)

    return Response({"groups": groups_data})

class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all().order_by('id')
    serializer_class = CustomerSerializer
    permission_classes = [IsAuthenticated, ModelActionPermission]
    pagination_class = CustomPagination

class UserManageViewSet(viewsets.ModelViewSet):
    queryset = get_user_model().objects.all().order_by('-id')
    serializer_class = UserManageSerializer
    permission_classes = [IsAuthenticated, ModelActionPermission]
    pagination_class = CustomPagination

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not user.is_authenticated:
            return qs.none()
        if user.is_superuser:
            return qs
        customer = get_primary_customer(user)
        if not customer:
            return qs.none()
        return qs.filter(customer=customer)

    def _require_perm(self, request, perm_codename):
        if not request.user.has_perm(f"auth.{perm_codename}_user"):
            raise PermissionDenied("Bu işlem için izniniz yok.")

    def create(self, request, *args, **kwargs):
        self._require_perm(request, "add")
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        self._require_perm(request, "change")
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        self._require_perm(request, "change")
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        self._require_perm(request, "delete")
        return super().destroy(request, *args, **kwargs)

    def perform_create(self, serializer):
        customer = get_primary_customer(self.request.user)
        if not customer:
            raise PermissionDenied("Müşteri bulunamadı.")
        user = serializer.save()
        customer.users.add(user)

class ProgramViewSet(viewsets.ModelViewSet):
    queryset = Program.objects.all().order_by('id')
    serializer_class = ProgramSerializer
    permission_classes = [IsAuthenticated, ModelActionPermission]
    pagination_class = CustomPagination

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        return qs.filter(created_by=user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

class GroupViewSet(viewsets.ModelViewSet):
    queryset = TrainingGroup.objects.all().order_by('-group_date')
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated, ModelActionPermission]
    pagination_class = CustomPagination

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        return qs.filter(created_by=user)

    def perform_create(self, serializer):
        user = self.request.user
        primary_customer = get_primary_customer(user)
        desired_customer = serializer.validated_data.get('customer') or primary_customer
        if not desired_customer:
            raise PermissionDenied("Müşteri bulunamadı.")
        if primary_customer and desired_customer != primary_customer and not user.is_superuser:
            raise PermissionDenied("Başka müşteriye grup oluşturamazsınız.")
        serializer.save(customer=desired_customer, created_by=user)

    def perform_update(self, serializer):
        # customer değişikliğine izin verme
        serializer.save(customer=serializer.instance.customer)

class GroupUserViewSet(viewsets.ModelViewSet):
    queryset = GroupUser.objects.all().order_by('id')
    serializer_class = GroupUserSerializer
    permission_classes = [IsAuthenticated, ModelActionPermission]
    pagination_class = CustomPagination

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        return qs.filter(created_by=user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

class ProgramScenarioViewSet(viewsets.ModelViewSet):
    queryset = ProgramScenario.objects.all().order_by('id')
    serializer_class = ProgramScenarioSerializer
    permission_classes = [IsAuthenticated, ModelActionPermission]
    pagination_class = CustomPagination

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.is_superuser:
            return qs
        return qs.filter(created_by=user)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

class EvaluationReportViewSet(viewsets.ModelViewSet):
    queryset = EvaluationReport.objects.all().order_by('-created_at')
    serializer_class = EvaluationReportSerializer
    permission_classes = [IsAuthenticated, ModelActionPermission]
    pagination_class = CustomPagination

@ensure_csrf_cookie
def get_csrf_token(request):
    # CSRF token'ı al
    csrf_token = get_token(request)
    
    response = JsonResponse({"csrfToken": csrf_token})
    
    # User-Agent'a göre cookie ayarlarını belirle
    user_agent = request.META.get('HTTP_USER_AGENT', '').lower()
    
    if 'safari' in user_agent and 'chrome' not in user_agent:
        # Safari için minimal ayarlar
        response.set_cookie('csrftoken', csrf_token, 
                          secure=True,  # HTTPS için gerekli
                          httponly=False)  # Safari için gerekli
    else:
        # Chrome ve diğer tarayıcılar için
        response.set_cookie('csrftoken', csrf_token, secure=True)
    
    return response

#TTS API
class TextToSpeechAPIView(APIView):
    def post(self, request, *args, **kwargs):
        scenario_name = request.data.get("scenario_name")
        text = request.data.get("text")
        # text = f"(in a cheerful and positive tone) {text}"

        if not scenario_name or not text:
            return Response({"error": "scenario_name ve text zorunludur."}, status=400)

        if scenario_name.startswith("__preview__"): # voice preview mode
            voice = scenario_name.replace("__preview__", "")
        else:
            try:
                scenario = Scenario.objects.get(name=scenario_name)
                voice = scenario.voice or "nova"
            except Scenario.DoesNotExist:
                return Response({"error": "Senaryo bulunamadı."}, status=404)

        print("Senaryo: ", scenario_name)
        print("Ses: ", voice)

        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        speech_file_path = Path(tempfile.NamedTemporaryFile(delete=False, suffix=".wav").name)

        try:
            with client.audio.speech.with_streaming_response.create(
                model="gpt-4o-mini-tts",
                voice=voice,
                input=text,
                response_format="wav",
            ) as response:
                response.stream_to_file(speech_file_path)

            return FileResponse(open(speech_file_path, "rb"), content_type="audio/wav")

        except Exception as e:
            return Response({"error": str(e)}, status=500)


# Online kullanıcı listesi cache key'i ve TTL
ONLINE_USERS_CACHE_KEY = "online_users_list_cache"
ONLINE_USERS_CACHE_TTL = 120  # 2 dakika - Redis sorgularını minimize eder
# HTTP heartbeat üzerinden presence TTL
PRESENCE_HEARTBEAT_TTL = 480  # 8 dakika (5 dk heartbeat + güvenlik marjı)


def _fetch_online_users_from_redis():
    """
    Redis'ten online kullanıcıları getirir (internal fonksiyon).
    
    Optimize edilmiş versiyon:
    - Tek SCAN işlemi (pattern bulma için ekstra SCAN yok)
    - MGET ile tüm değerleri tek seferde al (N GET yerine 1 MGET)
    """
    online_users = []
    
    # Django-redis connection'ını al. LocMem gibi backend'lerde desteklenmez.
    try:
        from django_redis import get_redis_connection
        redis_conn = get_redis_connection("default")
    except NotImplementedError:
        print("ℹ️ presence scan skipped: cache backend is not Redis (LocMem in DEBUG).")
        return online_users
    except Exception as e:
        print(f"⚠️ presence scan: get_redis_connection failed: {e}")
        return online_users
    
    # Django cache key formatı: ":1:online_user:*" (version prefix ile)
    # Tüm olası pattern'leri tek SCAN'de dene
    pattern = "*online_user:*"
    
    # SCAN ile tüm key'leri topla (tek geçiş)
    keys = []
    cursor = 0
    while True:
        cursor, batch = redis_conn.scan(cursor, match=pattern, count=200)
        keys.extend(batch)
        if cursor == 0:
            break
    
    if not keys:
        print("ℹ️ presence scan: no keys found")
        return online_users
    
    # Key'leri base key'e (online_user:xxx) indir ve cache.get_many kullan (serializer'lı)
    base_keys = []
    for raw_key in keys:
        try:
            key_str = raw_key.decode() if isinstance(raw_key, bytes) else str(raw_key)
            pos = key_str.find("online_user:")
            base_key = key_str[pos:] if pos != -1 else key_str
            base_keys.append(base_key)
        except Exception as e:
            print(f"⚠️ presence key decode error: {e}, raw={raw_key}")
            continue

    try:
        values_map = cache.get_many(base_keys)
        print(f"ℹ️ presence scan: {len(keys)} redis keys, {len(values_map)} cache hits")
        for bk, val in values_map.items():
            if not val:
                continue
            # Eğer değer string ise JSON parse etmeyi dene
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except Exception:
                    print(f"⚠️ presence value not parsed (string) key={bk}")
                    continue
            if isinstance(val, dict):
                online_users.append(val)
            else:
                print(f"⚠️ presence value not dict key={bk} type={type(val)}")
    except Exception as e:
        print(f"⚠️ presence cache get_many error: {e}")
    
    return online_users


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def presence_heartbeat_api(request):
    """
    WebSocket olmadan presence takibi için HTTP heartbeat.
    - status=offline gönderilirse key silinir.
    - aksi halde TTL yenilenir.
    """
    user = request.user
    status_flag = (request.data or {}).get("status", "online")

    cache_key = f"online_user:{user.id}"
    cache_backend = settings.CACHES.get("default", {}).get("BACKEND", "")
    is_redis_backend = "django_redis" in cache_backend

    if status_flag == "offline":
        cache.delete(cache_key)
        if is_redis_backend:
            # invalidate aggregated cache so admin sees latest state
            cache.delete(ONLINE_USERS_CACHE_KEY)
        else:
            # LocMem: aggregate listten kaldır
            lst = cache.get(ONLINE_USERS_CACHE_KEY) or []
            lst = [u for u in lst if isinstance(u, dict) and u.get("user_id") != user.id]
            cache.set(ONLINE_USERS_CACHE_KEY, lst, timeout=ONLINE_USERS_CACHE_TTL)
        print(f"❌ Presence HTTP: {user.username} offline oldu.")
        return Response({"status": "offline"})

    user_data = {
        "user_id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "last_seen": timezone.now().isoformat(),
    }

    # Cache'e dict olarak yaz (pickle serializer kullanıyor); stringe çevirme
    cache.set(cache_key, user_data, timeout=PRESENCE_HEARTBEAT_TTL)

    if is_redis_backend:
        # invalidate aggregated cache so admin sees latest state
        cache.delete(ONLINE_USERS_CACHE_KEY)
    else:
        # LocMem: aggregate listeyi güncelle
        lst = cache.get(ONLINE_USERS_CACHE_KEY) or []
        lst = [u for u in lst if isinstance(u, dict) and u.get("user_id") != user.id]
        lst.append(user_data)
        cache.set(ONLINE_USERS_CACHE_KEY, lst, timeout=ONLINE_USERS_CACHE_TTL)

    print(f"✅ Presence HTTP: {user.username} online, TTL yenilendi ({PRESENCE_HEARTBEAT_TTL}s)")
    return Response({"status": "online", "ttl": PRESENCE_HEARTBEAT_TTL})


def get_online_users():
    """
    Online kullanıcıları getirir (cache'li versiyon).
    
    2dk boyunca cache'ten okur, böylece admin sayfası 
    her yüklendiğinde Redis'e saldırmaz.
    """
    # Önce cache'e bak
    cached_result = cache.get(ONLINE_USERS_CACHE_KEY)
    if cached_result is not None:
        return cached_result
    
    # Cache'te yoksa Redis'ten çek
    online_users = _fetch_online_users_from_redis()
    print(f"ℹ️ presence fetch: {len(online_users)} users")

    # Sonucu cache'le (30 saniye)
    cache.set(ONLINE_USERS_CACHE_KEY, online_users, timeout=ONLINE_USERS_CACHE_TTL)
    
    return online_users


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def online_users_api(request):
    """
    Online kullanıcı sayısı ve listesini döner.
    
    Not: UI tarafında presence takibi için polling ile kullanılabilir (ileride).
    Real-time güncelleme için WebSocket broadcast gerekir (şu an yok).
    """
    online_users = get_online_users()
    
    return Response({
        "count": len(online_users),
        "users": online_users
    })
        