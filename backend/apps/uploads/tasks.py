import shutil
import tempfile

from config.celery import app as celery_app
from django.core.files import File
from django.db import transaction

from .models import Upload, UploadChunk, UploadSession


@celery_app.task(acks_late=True)
def assemble_upload(session_id):
    from apps.accounts.models import YouTubeConnection
    with transaction.atomic():
        session = UploadSession.objects.select_for_update().get(pk=session_id)

        if session.status == "completed":
            return

        if session.status not in ("queued", "assembling"):
            return

        session.status = "assembling"
        session.save(update_fields=["status", "updated_at"])

        chunks = list(session.chunks.order_by("index"))
        received = {chunk.index for chunk in chunks}
        missing = [
            index for index in range(session.total_chunks)
            if index not in received
        ]

        if missing:
            session.status = "pending"
            session.save(update_fields=["status", "updated_at"])
            return

    try:
        with tempfile.TemporaryFile(mode="w+b") as merged_file:
            for chunk in chunks:
                with chunk.file.open("rb") as part:
                    shutil.copyfileobj(part, merged_file)

            merged_file.seek(0)
            upload = Upload(
                owner=session.owner,
                uploaded_by=session.created_by,
                title=session.title,
                description=session.description,
                youtube_privacy=session.youtube_privacy,
                status="uploaded",
            )
            upload.file.save(
                session.file_name,
                File(merged_file, name=session.file_name),
                save=False,
            )
            upload.save()

        with transaction.atomic():
            session = UploadSession.objects.select_for_update().get(pk=session_id)
            if session.status == "completed":
                return

            session.completed_upload = upload
            session.status = "completed"
            session.save(
                update_fields=["completed_upload", "status", "updated_at"]
            )

            if YouTubeConnection.objects.filter(creator=upload.owner).exists():
                upload.youtube_status = "queued"
                upload.save(update_fields=["youtube_status"])
                transaction.on_commit(
                    lambda upload_id=upload.pk: publish_to_youtube.delay(upload_id)
                )

        for chunk in chunks:
            chunk.file.delete(save=False)
            chunk.delete()

    except Exception:
        UploadSession.objects.filter(pk=session_id).update(status="failed")
        raise

@celery_app.task
def cleanup_inactive_uploads():
    from django.core.management import call_command

    call_command("cleanup_upload_sessions", hours=24)

@celery_app.task(acks_late=True)
def publish_to_youtube(upload_id):
    import mimetypes

    from cryptography.fernet import Fernet
    from django.conf import settings
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    from apps.accounts.models import YouTubeConnection

    upload = Upload.objects.select_related("owner").get(pk=upload_id)

    if upload.youtube_status == "published":
        return upload.youtube_video_id

    connection = YouTubeConnection.objects.filter(creator=upload.owner).first()
    if connection is None:
        Upload.objects.filter(pk=upload_id).update(
            youtube_status="failed",
            youtube_error="Connect a YouTube channel before publishing.",
        )
        return

    Upload.objects.filter(pk=upload_id).update(
        youtube_status="publishing",
        youtube_error="",
    )

    try:
        refresh_token = Fernet(
            settings.YOUTUBE_TOKEN_ENCRYPTION_KEY.encode()
        ).decrypt(connection.refresh_token_encrypted.encode()).decode()

        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.YOUTUBE_CLIENT_ID,
            client_secret=settings.YOUTUBE_CLIENT_SECRET,
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.readonly",
            ],
        )
        credentials.refresh(Request())

        youtube = build(
            "youtube",
            "v3",
            credentials=credentials,
            cache_discovery=False,
        )
        mime_type, _ = mimetypes.guess_type(upload.file.name)
        media = MediaFileUpload(
            upload.file.path,
            mimetype=mime_type or "application/octet-stream",
            chunksize=8 * 1024 * 1024,
            resumable=True,
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": upload.title[:100],
                    "description": upload.description,
                },
                "status": {"privacyStatus": upload.youtube_privacy},
            },
            media_body=media,
        )

        result = None
        while result is None:
            _, result = request.next_chunk()

        Upload.objects.filter(pk=upload_id).update(
            youtube_status="published",
            youtube_video_id=result["id"],
            youtube_error="",
        )
        return result["id"]

    except Exception as error:
        Upload.objects.filter(pk=upload_id).update(
            youtube_status="failed",
            youtube_error=str(error)[:2000],
        )
        raise
