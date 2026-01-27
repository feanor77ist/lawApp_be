from django.core.management.base import BaseCommand
from django.db.models import F
from my_app.models import EvaluationReport


class Command(BaseCommand):
    help = 'Eski EvaluationReport kayıtlarının average_score değerlerini score değerine eşitler'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Sadece kaç kayıt güncelleneceğini göster, gerçek güncelleme yapma',
        )

    def handle(self, *args, **options):
        # average_score değeri NULL olan ve score değeri olan kayıtları bul
        reports_to_update = EvaluationReport.objects.filter(
            average_score__isnull=True,
            score__isnull=False
        )
        
        count = reports_to_update.count()
        
        if count == 0:
            self.stdout.write(
                self.style.SUCCESS('ℹ️ Güncellenecek kayıt bulunamadı.')
            )
            return
        
        self.stdout.write(f'📊 Güncellenecek kayıt sayısı: {count}')
        
        if options['dry_run']:
            self.stdout.write(
                self.style.WARNING('🔍 DRY RUN modu: Gerçek güncelleme yapılmayacak.')
            )
            return
        
        # Bulk update ile hızlı güncelleme
        updated_count = reports_to_update.update(average_score=F('score'))
        
        if updated_count > 0:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Toplam {updated_count} kayıt başarıyla güncellendi!')
            )
        else:
            self.stdout.write(
                self.style.WARNING('⚠️ Hiçbir kayıt güncellenemedi.')
            )
