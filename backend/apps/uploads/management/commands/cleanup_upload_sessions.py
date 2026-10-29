from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.uploads.models import UploadSession


class Command(BaseCommand):
    help = "Delete pending or failed upload sessions inactive for a while."

    def add_arguments(self, parser):
        parser.add_argument(
            "--hours",
            type=int,
            default=24,
            help="Inactive age in hours before a session is removed (default: 24).",
        )

    def handle(self, *args, **options):
        hours = options["hours"]
        if hours < 1:
            self.stderr.write("Hours must be at least 1.")
            return

        cutoff = timezone.now() - timedelta(hours=hours)
        sessions = UploadSession.objects.filter(
            status__in=["pending", "failed", "rejected"],
            updated_at__lt=cutoff,
        )

        deleted = 0
        for session in sessions.iterator():
            for chunk in session.chunks.all():
                if chunk.file:
                    chunk.file.delete(save=False)
            session.delete()
            deleted += 1

        self.stdout.write(self.style.SUCCESS(f"Removed {deleted} inactive upload session(s)."))