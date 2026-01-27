from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'scenario', views.ScenarioViewSet)
router.register(r'customer', views.CustomerViewSet)
router.register(r'program', views.ProgramViewSet)
router.register(r'group', views.GroupViewSet)
router.register(r'groupuser', views.GroupUserViewSet)
router.register(r'programscenario', views.ProgramScenarioViewSet)
router.register(r'evaluationreport', views.EvaluationReportViewSet)
router.register(r'users', views.UserManageViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('entries/', views.UserEntryListAPI.as_view(), name='user-entry-list'),
    path('entries/<str:entry_id>/', views.UserEntryListAPI.as_view(), name='user-entry-detail'),
    path('login/', views.CustomAuthToken.as_view(), name='login'),
    path('chatbot/', views.ChatbotAPI.as_view(), name='chatbot-api'),
    path('user/scenarios/', views.available_scenarios_api, name='available-scenarios'),
    path('trainer/group-reports/', views.trainer_group_reports_api, name='trainer-group-reports'),
    path('user-reports/', views.user_reports_api, name='user-reports'),
    path("auth/csrf/", views.get_csrf_token, name="get-csrf-token"),
    path('tts/', views.TextToSpeechAPIView.as_view(), name='tts-api'),
    path('admin/online-users/', views.online_users_api, name='online-users-api'),
    path('presence/heartbeat/', views.presence_heartbeat_api, name='presence-heartbeat'),
]
