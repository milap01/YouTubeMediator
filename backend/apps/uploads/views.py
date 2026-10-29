from pathlib import Path

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.views import APIView

from .access import uploads_visible_to
from .models import Upload
from .serializers import UploadSerializer


class UploadPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class UploadListCreateView(ListAPIView):
    pagination_class = UploadPagination
    serializer_class = UploadSerializer

    def get_queryset(self):
        uploads = uploads_visible_to(self.request.user)
        search = self.request.query_params.get("search", "").strip()
        if search:
            uploads = uploads.filter(title__icontains=search)

        youtube_status = self.request.query_params.get("youtube_status", "").strip()
        valid_statuses = {value for value, _label in Upload.YOUTUBE_STATUS_CHOICES}
        if youtube_status in valid_statuses:
            uploads = uploads.filter(youtube_status=youtube_status)

        return uploads.order_by("-created_at")


class UploadDownloadView(APIView):
    def get(self, request, upload_id):
        upload = get_object_or_404(
            uploads_visible_to(request.user),
            id=upload_id,
        )
        return FileResponse(
            upload.file.open("rb"),
            as_attachment=True,
            filename=Path(upload.file.name).name,
        )

class UploadPublishView(APIView):
    def post(self, request, upload_id):
        from django.db import transaction
        from django.shortcuts import get_object_or_404
        from rest_framework import status
        from rest_framework.response import Response
        from apps.accounts.models import Profile, YouTubeConnection
        from .tasks import publish_to_youtube

        if not Profile.objects.filter(user=request.user, role="creator").exists():
            return Response({"detail": "Only creators can publish uploads."}, status=403)

        with transaction.atomic():
            upload = get_object_or_404(
                Upload.objects.select_for_update(),
                pk=upload_id,
                owner=request.user,
            )

            if not YouTubeConnection.objects.filter(creator=request.user).exists():
                return Response({"detail": "Connect a YouTube channel first."}, status=400)

            if upload.youtube_status in ("queued", "publishing"):
                return Response({"detail": "This upload is already being published."}, status=409)

            if upload.youtube_status == "published":
                return Response({
                    "youtube_status": "published",
                    "youtube_video_id": upload.youtube_video_id,
                })

            upload.youtube_status = "queued"
            upload.youtube_error = ""
            upload.save(update_fields=["youtube_status", "youtube_error"])

            transaction.on_commit(
                lambda upload_id=upload.pk: publish_to_youtube.delay(upload_id)
            )

        return Response(
            {"youtube_status": "queued"},
            status=status.HTTP_202_ACCEPTED,
        )
