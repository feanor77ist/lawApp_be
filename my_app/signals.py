"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Scenario
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from django.conf import settings
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma
import os
from chatbot.llm_utils import embed_model
from langchain_core import documents
from ml_simulator.settings import BASE_DIR

def get_docs_vectorstore():
    embedding_model = OpenAIEmbeddings(model=embed_model, api_key=settings.OPENAI_API_KEY)
    persist_dir = os.path.join(BASE_DIR, "chroma_db", "embeddings")
    return Chroma(
        collection_name="embeddings_collection",
        embedding_function=embedding_model,
        persist_directory=persist_dir,
        collection_metadata={"hnsw:space": "cosine"}
    )

def load_and_split_file(file_field):
    # Verilen Django FileField üzerinden dosya yükler ve metni 
    # RecursiveCharacterTextSplitter ile parçalara böler. PDF ve DOCX desteklenir.
    if file_field.name.lower().endswith('.pdf'):
        loader = PyPDFLoader(file_field)
    elif file_field.name.lower().endswith('.docx'):
        loader = Docx2txtLoader(file_field)
    else:
        raise ValueError(f"Desteklenmeyen dosya türü: {file_field.name}")
    
    docs = loader.load()
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    splits = text_splitter.split_documents(docs)
    print(f"Doküman {file_field.name} {len(splits)} parçaya bölündü")
    return splits

@receiver(post_save, sender=Scenario)
def update_scenario_embedding(sender, instance, created, **kwargs):
    # Scenario nesnesi oluşturulduğunda veya güncellendiğinde,
    # ilgili scenario_document ve review_document dosyaları için
    # yeni embed işlemini gerçekleştirir. Eğer nesne güncelleniyorsa,
    # mevcut embed kayıtları silinir.
    vectorstore = get_docs_vectorstore()

    # Sadece güncelleme durumunda eski embed kayıtlarını sil
    if not created:
        try:
            vectorstore._collection.delete(where={"scenario_id": str(instance.id)})
            print(f"Eski embed kayıtları silindi (Scenario ID: {instance.id}).")
        except Exception as e:
            print(f"Eski embed kayıtları silinirken hata (Scenario ID: {instance.id}): {e}")
    
    # scenario_document alanı varsa embed işlemi
    if instance.scenario_document:
        try:
            splits = load_and_split_file(instance.scenario_document)
            for split in splits:
                split.metadata['scenario_id'] = str(instance.id)
                split.metadata['document_type'] = 'scenario_document'
            vectorstore.add_documents(splits)
            print(f"Scenario document embed edildi (Scenario ID: {instance.id}).")
        except Exception as e:
            print(f"Scenario document embedlenirken hata (Scenario ID: {instance.id}): {e}")

    # review_document alanı varsa embed işlemi
    if instance.review_document:
        try:
            splits = load_and_split_file(instance.review_document)
            for split in splits:
                split.metadata['scenario_id'] = str(instance.id)
                split.metadata['document_type'] = 'review_document'
            vectorstore.add_documents(splits)
            print(f"Review document embed edildi (Scenario ID: {instance.id}).")
        except Exception as e:
            print(f"Review document embedlenirken hata (Scenario ID: {instance.id}): {e}")

@receiver(post_delete, sender=Scenario)
def delete_scenario_embedding(sender, instance, **kwargs):
    # Scenario nesnesi silindiğinde,
    # ilgili tüm embed kayıtlarını Chroma vektör veri tabanından kaldırır.
    try:
        vectorstore = get_docs_vectorstore()
        vectorstore._collection.delete(where={"scenario_id": str(instance.id)})
        print(f"Scenario embed kayıtları silindi (Scenario ID: {instance.id}).")
    except Exception as e:
        print(f"Scenario embed kayıtları silinirken hata (Scenario ID: {instance.id}): {e}")
"""
from django.conf import settings
from django.db.models.signals import post_save, pre_save, m2m_changed, post_delete
from django.db.models import Q
from django.dispatch import receiver
from .models import EvaluationReport, GroupUser, ProgramScenario, TrainingGroup
from decimal import Decimal, ROUND_HALF_UP
from django.contrib.auth.models import User
from django.contrib.auth.forms import PasswordResetForm
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from datetime import date

@receiver(post_save, sender=EvaluationReport)
def update_progress(sender, instance, created, **kwargs):
    group = instance.training_group
    user = instance.user

    # Eğer kullanıcı sadece trainer ise (users içinde değil), progress hesaplaması yapma
    # Progress hesaplaması sadece katılımcılar (users) için yapılır
    if user not in group.users.all():
        return

    total_scenarios = group.program.scenarios.count()
    completed = EvaluationReport.objects.filter(
        training_group=group,
        user=user,
        type="post"  # Sadece post-evaluation raporları sayılır
    ).count()

    progress = round((completed / total_scenarios) * 100, 2) if total_scenarios else 0.0

    # GroupUser progress kaydını güncelle
    GroupUser.objects.filter(training_group=group, user=user).update(progress=progress)

    # Grup genel progress güncelle
    all_progress = GroupUser.objects.filter(training_group=group).values_list('progress', flat=True)
    group.progress = round(sum(all_progress) / len(all_progress), 2) if all_progress else 0.0
    group.save()

    # Kullanıcı ilerlemesi %100 ise ağırlıklı ortalama puan hesapla
    try:
        group_user = GroupUser.objects.get(training_group=group, user=user)
    except GroupUser.DoesNotExist:
        return

    if group_user.progress < 100:
        return

    total = Decimal(0)
    total_weight = Decimal(0)

    for ps in ProgramScenario.objects.filter(program=group.program):
        report = EvaluationReport.objects.filter(
            user=user,
            training_group=group,
            scenario=ps.scenario,
            type="post"  # Sadece post-evaluation raporu alınır
        ).first()

        if report:
            weight = ps.weight_percentage
            total += Decimal(report.score) * Decimal(weight)
            total_weight += Decimal(weight)

    if total_weight > 0:
        average = (total / total_weight).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        group_user.total_score = average
        group_user.save()


# Update group average progress when GroupUser is created or deleted
@receiver(m2m_changed, sender=TrainingGroup.users.through)
def update_training_group_progress(sender, instance, action, **kwargs):
    if action in ["post_add", "post_remove", "post_clear"]:
        progresses = instance.groupuser_set.values_list("progress", flat=True)
        average = round(sum(progresses) / len(progresses), 2) if progresses else 0.0
        instance.progress = average
        instance.save()
        print(f"✅ TrainingGroup progress güncellendi: {average}% (action={action})")

# ProgramScenario değiştirildiğinde veya silindiğinde tüm TrainingGroup'ların progress ve total_score alanlarını günceller
@receiver([post_save, post_delete], sender=ProgramScenario)
def handle_program_scenario_change(sender, instance, **kwargs):
    program = instance.program
    groups = TrainingGroup.objects.filter(program=program)

    for group in groups:
        group_users = GroupUser.objects.filter(training_group=group)

        for gu in group_users:
            user = gu.user
            total_scenarios = program.scenarios.count()
            completed = EvaluationReport.objects.filter(user=user, training_group=group, type="post").count() # Sadece post-evaluation raporlar sayılır

            progress = round((completed / total_scenarios) * 100, 2) if total_scenarios else 0.0
            gu.progress = progress

            # total_score sadece %100 olunca hesaplanır
            if progress == 100:
                total = Decimal(0)
                total_weight = Decimal(0)

                for ps in ProgramScenario.objects.filter(program=program):
                    report = EvaluationReport.objects.filter(
                        user=user, training_group=group, scenario=ps.scenario, type="post"
                    ).first()

                    if report:
                        total += Decimal(report.score) * Decimal(ps.weight_percentage)
                        total_weight += Decimal(ps.weight_percentage)

                if total_weight > 0:
                    average = (total / total_weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    gu.total_score = average

            gu.save()

        # Grup ortalama progress güncelle
        progresses = group.groupuser_set.values_list("progress", flat=True)
        group.progress = round(sum(progresses) / len(progresses), 2) if progresses else 0.0
        group.save()


# Email adresi normalizasyonu ve case-insensitive uniqueness kontrolü
@receiver(pre_save, sender=User)
def normalize_user_email(sender, instance, **kwargs):
    # Email normalizasyonu - küçük harfe çevir
    if instance.email:
        instance.email = instance.email.lower().strip()
    if instance.username:
        instance.username = instance.username.lower().strip()
        
    # Username alanını email olarak kullanıyoruz, eşitleyelim
    if instance.username and not instance.email:
        instance.email = instance.username
    elif instance.email and not instance.username:
        instance.username = instance.email
        
    # Case-insensitive uniqueness kontrolü
    if instance.username:
        existing = User.objects.filter(username__iexact=instance.username)
        if instance.pk:
            existing = existing.exclude(pk=instance.pk)
        
        if existing.exists():
            raise ValidationError(f"Bu email adresi ({instance.username}) zaten kayıtlı. Büyük/küçük harf farkı gözetilmez.")

# # Kullanıcı eklendiğinde parola sıfırlama e-postası gönderilir
# @receiver(post_save, sender=User)
# def send_password_reset_email(sender, instance, created, **kwargs):
#     if getattr(instance, "_skip_post_save_email", False):
#         print(f"Sinyal bastırma flag'i: Kullanıcı e-postası gönderilmesinden çıkartıldı.")
#         return
    
#     if not created:
#         return

#     email = instance.username  # çünkü username=email olmalı

#     if not email or not instance.is_active:
#         return

#     if not instance.email:
#         instance.email = instance.username
#         instance.save(update_fields=["email"])  # email alanını doldur

#     form = PasswordResetForm({'email': email})
#     if form.is_valid():
#         form.save(
#             request=None,
#             use_https=not settings.DEBUG,
#             domain_override="127.0.0.1:8000" if settings.DEBUG else "ml-simulator.onrender.com",
#             email_template_name='registration/welcome_email.html',
#             subject_template_name='registration/welcome_subject.txt',
#         )
#         print('✅ Password reset email sent to:', email)
#     else:
#         print('❌ Form geçersiz:', form.errors)

def send_new_user_assignment_email(user, training_group, scenarios):
    """Yeni kullanıcı eğitim grubuna eklendiğinde e-posta gönderir."""
    if not user.email or not user.is_active:
        return False
    
    try:
        scenario_list = []
        for ps in scenarios:
            scenario_list.append({
                'scenario_name': ps.scenario.name,
                'release_date': ps.release_date,
                'training_date': ps.training_date,
                'close_date': ps.close_date,
            })
        
        context = {
            'user': user,
            'training_group': training_group,
            'program_name': training_group.program.name,
            'scenarios': scenario_list,
        }
        
        subject = render_to_string(
            'registration/new_user_assigned_subject.txt',
            {'training_group_name': training_group.name}
        ).strip()
        
        text_message = render_to_string(
            'registration/new_user_assigned_email.txt',
            context
        )
        
        html_message = render_to_string(
            'registration/new_user_assigned_email.html',
            context
        )
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach_alternative(html_message, "text/html")
        email.send(fail_silently=False)
        
        print(f'✅ Yeni kullanıcı atama e-postası gönderildi: {user.email}')
        return True
    except Exception as e:
        print(f'❌ Yeni kullanıcı atama e-postası gönderilirken hata: {e}')
        return False

def send_new_scenario_assignment_email(user, training_group, program_scenario):
    """Yeni senaryo eklendiğinde kullanıcılara e-posta gönderir."""
    if not user.email or not user.is_active:
        return False
    
    try:
        context = {
            'user': user,
            'training_group_name': training_group.name,
            'program_name': training_group.program.name,
            'scenario_name': program_scenario.scenario.name,
            'release_date': program_scenario.release_date,
            'training_date': program_scenario.training_date,
            'close_date': program_scenario.close_date,
        }
        
        subject = render_to_string(
            'registration/new_scenario_assigned_subject.txt',
            {'training_group_name': training_group.name}
        ).strip()
        
        text_message = render_to_string(
            'registration/new_scenario_assigned_email.txt',
            context
        )
        
        html_message = render_to_string(
            'registration/new_scenario_assigned_email.html',
            context
        )
        
        email = EmailMultiAlternatives(
            subject=subject,
            body=text_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach_alternative(html_message, "text/html")
        email.send(fail_silently=False)
        
        print(f'✅ Yeni senaryo atama e-postası gönderildi: {user.email}')
        return True
    except Exception as e:
        print(f'❌ Yeni senaryo atama e-postası gönderilirken hata: {e}')
        return False

@receiver(m2m_changed, sender=TrainingGroup.users.through)
def send_new_user_assignment_email_signal(sender, instance, action, pk_set, **kwargs):
    """TrainingGroup'a yeni kullanıcı eklendiğinde e-posta gönderir."""
    if action != "post_add" or not pk_set:
        return
    
    training_group = instance
    program = training_group.program
    
    # Close date geçmemiş senaryoları al
    today = date.today()
    active_scenarios = ProgramScenario.objects.filter(
        program=program,
    ).filter(
        Q(close_date__gte=today) | Q(close_date__isnull=True)
    ).select_related('scenario')
    
    if not active_scenarios.exists():
        return
    
    # Eklenen kullanıcıları al
    added_users = User.objects.filter(pk__in=pk_set, is_active=True)
    
    for user in added_users:
        send_new_user_assignment_email(user, training_group, active_scenarios)

@receiver(post_save, sender=ProgramScenario)
def send_new_scenario_assignment_email_signal(sender, instance, created, **kwargs):
    """ProgramScenario eklendiğinde ilgili TrainingGroup kullanıcılarına e-posta gönderir."""
    if not created:
        return
    
    program_scenario = instance
    
    # Close date kontrolü: Eğer close_date geçmişse e-posta gönderme
    if program_scenario.close_date and program_scenario.close_date < date.today():
        return
    
    program = program_scenario.program
    training_groups = TrainingGroup.objects.filter(program=program)
    
    for training_group in training_groups:
        users = training_group.users.filter(is_active=True)
        
        for user in users:
            send_new_scenario_assignment_email(user, training_group, program_scenario)
        