from math import ceil
from pathlib import Path

import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import BaseParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import CreatorEditorAccess, Profile
from .access import get_accessible_session, sessions_visible_to
from .models import Upload, UploadChunk, UploadSession
from .tasks import assemble_upload


CHUNK_SIZE = 5 * 1024 * 1024
MAX_FILE_SIZE = 500 * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
MAX_ACTIVE_UPLOAD_SESSIONS = 3


class BinaryChunkParser(BaseParser):
    media_type = "application/octet-stream"

    def parse(self, stream, media_type=None, parser_context=None):
        return stream.read()


def session_data(upload_session):
    return {
        "id": str(upload_session.id),
        "title": upload_session.title,
        "description": upload_session.description,
        "youtube_privacy": upload_session.youtube_privacy,
        "creator_id": upload_session.owner_id,
        "creator_username": upload_session.owner.username,
        "file_name": upload_session.file_name,
        "file_size": upload_session.file_size,
        "total_chunks": upload_session.total_chunks,
        "received_chunks": list(
            upload_session.chunks.order_by("index").values_list("index", flat=True)
        ),
        "status": upload_session.status,
    }


class UploadSessionCreateView(APIView):
    parser_classes = [JSONParser]

    def get(self, request):
        sessions = (
            sessions_visible_to(request.user)
            .exclude(status="completed")
            .order_by("-updated_at")[:20]
        )
        return Response([session_data(session) for session in sessions])

    def post(self, request):
        data = request.data
        title = str(data.get("title", "")).strip()
        description = str(data.get("description", "")).strip()
        youtube_privacy = str(data.get("youtube_privacy", "private")).strip().lower()
        file_name = Path(str(data.get("file_name", ""))).name
        raw_client_key = str(data.get("client_key", "")).strip()

        try:
            file_size = int(data.get("file_size", 0))
            total_chunks = int(data.get("total_chunks", 0))
        except (TypeError, ValueError):
            return Response({"detail": "Invalid file size or chunk count."}, status=400)

        if not title or not raw_client_key or not file_name or file_size <= 0:
            return Response({"detail": "Title and valid file details are required."}, status=400)
        if len(title) > 100:
            return Response({"detail": "YouTube titles must be 100 characters or fewer."}, status=400)
        if len(description.encode("utf-8")) > 5000:
            return Response({"detail": "YouTube descriptions must be 5,000 bytes or fewer."}, status=400)
        if youtube_privacy not in {"private", "unlisted", "public"}:
            return Response({"detail": "Choose Private, Unlisted, or Public privacy."}, status=400)

        if file_size > MAX_FILE_SIZE:
            return Response({"detail": "Maximum file size is 500 MB."}, status=400)

        if Path(file_name).suffix.lower() not in ALLOWED_EXTENSIONS:
            return Response({"detail": "Unsupported video format."}, status=400)

        profile = Profile.objects.filter(user=request.user).first()
        if profile is None:
            return Response({"detail": "Your account has no role assigned."}, status=403)

        target_creator_id = data.get("creator_id")
        if profile.role == "creator":
            if target_creator_id not in (None, "", request.user.pk, str(request.user.pk)):
                return Response({"detail": "Creators can only upload to their own account."}, status=403)
            creator = request.user
        elif profile.role == "editor":
            if not target_creator_id:
                return Response({"detail": "Choose a creator account."}, status=400)
            creator = get_user_model().objects.filter(pk=target_creator_id).first()
            if creator is None:
                return Response({"detail": "Creator account not found."}, status=404)
            if not CreatorEditorAccess.objects.filter(
                creator=creator,
                editor=request.user,
                status="accepted",
            ).exists():
                return Response({"detail": "You do not have accepted access to this creator."}, status=403)
        else:
            return Response({"detail": "Your account role cannot upload videos."}, status=403)

        client_key = f"{request.user.pk}:{raw_client_key}"
        expected_chunks = ceil(file_size / CHUNK_SIZE)
        if total_chunks != expected_chunks:
            return Response({"detail": "Chunk count does not match file size."}, status=400)

        existing_session = UploadSession.objects.filter(
            owner=creator,
            client_key=client_key,
        ).exists()

        if not existing_session:
            active_sessions = UploadSession.objects.filter(
                created_by=request.user,
                status__in=["pending", "queued", "assembling", "awaiting_approval"],
            ).count()
            if active_sessions >= MAX_ACTIVE_UPLOAD_SESSIONS:
                return Response(
                    {"detail": "You already have 3 active uploads. Finish or discard one before starting another."},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )

        upload_session, created = UploadSession.objects.get_or_create(
            owner=creator,
            client_key=client_key,
            defaults={
                "created_by": request.user,
                "title": title,
                "description": description,
                "youtube_privacy": youtube_privacy,
                "file_name": file_name,
                "file_size": file_size,
                "total_chunks": total_chunks,
            },
        )

        if not created and (
            upload_session.title != title
            or upload_session.description != description
            or upload_session.youtube_privacy != youtube_privacy
            or upload_session.file_name != file_name
            or upload_session.file_size != file_size
            or upload_session.total_chunks != total_chunks
            or upload_session.created_by_id != request.user.pk
        ):
            return Response(
                {"detail": "This upload key belongs to a different file."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            session_data(upload_session),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class UploadSessionStatusView(APIView):
    def get(self, request, session_id):
        upload_session = get_accessible_session(request.user, session_id)
        return Response(session_data(upload_session))

    @transaction.atomic
    def delete(self, request, session_id):
        upload_session = get_accessible_session(request.user, session_id, lock=True)

        if upload_session.status != "failed" or upload_session.completed_upload_id:
            return Response(
                {"detail": "Only unlinked failed sessions can be discarded."},
                status=409,
            )

        if request.user.id not in (
            upload_session.owner_id,
            upload_session.created_by_id,
        ):
            return Response({"detail": "You cannot discard this session."}, status=403)

        for chunk in upload_session.chunks.all():
            if chunk.file:
                chunk.file.delete(save=False)
            chunk.delete()

        upload_session.delete()
        return Response(status=204)


class UploadChunkView(APIView):
    parser_classes = [BinaryChunkParser]

    def put(self, request, session_id, index):
        upload_session = get_accessible_session(request.user, session_id)

        if upload_session.status != "pending":
            return Response({"detail": "This upload is not accepting chunks."}, status=409)

        if index < 0 or index >= upload_session.total_chunks:
            return Response({"detail": "Invalid chunk index."}, status=400)

        chunk_data = request.data
        if not isinstance(chunk_data, bytes):
            return Response({"detail": "Expected binary chunk data."}, status=400)

        expected_size = min(
            CHUNK_SIZE,
            upload_session.file_size - index * CHUNK_SIZE,
        )
        if len(chunk_data) != expected_size:
            return Response({"detail": "Chunk size is incorrect."}, status=400)

        existing = UploadChunk.objects.filter(session=upload_session, index=index).first()
        if existing:
            upload_session.save(update_fields=["updated_at"])
            return Response({"received": True, "index": index})

        chunk = UploadChunk(session=upload_session, index=index)
        chunk.file.save(f"chunk-{index}.part", ContentFile(chunk_data), save=True)
        upload_session.save(update_fields=["updated_at"])

        return Response({"received": True, "index": index}, status=status.HTTP_201_CREATED)

class CompleteUploadView(APIView):
    @transaction.atomic
    def post(self, request, session_id):
        upload_session = get_accessible_session(request.user, session_id, lock=True)

        if upload_session.status == "completed" and upload_session.completed_upload:
            upload = upload_session.completed_upload
            return Response({
                "id": upload.id,
                "title": upload.title,
                "status": "completed",
            })

        if upload_session.status == "awaiting_approval":
            return Response(
                {"id": str(upload_session.id), "status": "awaiting_approval"},
                status=202,
            )

        if upload_session.status in ("queued", "assembling"):
            return Response(
                {"id": str(upload_session.id), "status": upload_session.status},
                status=202,
            )

        if upload_session.status == "rejected":
            return Response({"detail": "This upload was rejected."}, status=409)

        chunks = set(upload_session.chunks.values_list("index", flat=True))
        missing = [
            index for index in range(upload_session.total_chunks)
            if index not in chunks
        ]

        if missing:
            return Response(
                {"detail": "Some chunks are missing.", "missing_chunks": missing},
                status=400,
            )

        if upload_session.created_by_id != upload_session.owner_id:
            upload_session.status = "awaiting_approval"
            upload_session.save(update_fields=["status", "updated_at"])
            return Response(
                {"id": str(upload_session.id), "status": "awaiting_approval"},
                status=202,
            )

        upload_session.status = "queued"
        upload_session.save(update_fields=["status", "updated_at"])
        session_id_text = str(upload_session.id)
        transaction.on_commit(lambda: assemble_upload.delay(session_id_text))

        return Response(
            {"id": session_id_text, "status": "queued"},
            status=202,
        )


class UploadSessionDecisionView(APIView):
    @transaction.atomic
    def post(self, request, session_id):
        if not Profile.objects.filter(user=request.user, role="creator").exists():
            return Response({"detail": "Only creators can approve uploads."}, status=403)

        upload_session = get_accessible_session(request.user, session_id, lock=True)
        if upload_session.owner_id != request.user.id:
            return Response({"detail": "Only the creator can decide on this upload."}, status=403)

        if upload_session.status != "awaiting_approval":
            return Response({"detail": "This upload is not awaiting approval."}, status=409)

        decision = request.data.get("decision")
        if decision == "reject":
            upload_session.status = "rejected"
            upload_session.save(update_fields=["status", "updated_at"])
            for chunk in upload_session.chunks.all():
                if chunk.file:
                    chunk.file.delete(save=False)
                chunk.delete()
            return Response({"id": str(upload_session.id), "status": "rejected"})

        if decision != "approve":
            return Response({"detail": "Decision must be approve or reject."}, status=400)

        upload_session.status = "queued"
        upload_session.save(update_fields=["status", "updated_at"])
        session_id_text = str(upload_session.id)
        transaction.on_commit(lambda: assemble_upload.delay(session_id_text))
        return Response(
            {"id": session_id_text, "status": "queued"},
            status=202,
        )
