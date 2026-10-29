from django.urls import path
from .resumable import (
    CompleteUploadView,
    UploadChunkView,
    UploadSessionCreateView,
    UploadSessionStatusView,
    UploadSessionDecisionView,
)
from .views import UploadDownloadView, UploadListCreateView, UploadPublishView

urlpatterns = [
    path("sessions/<uuid:session_id>/approval/", UploadSessionDecisionView.as_view(), name="upload-session-approval"),

    path("<int:upload_id>/publish/", UploadPublishView.as_view(), name="upload-publish"),
    path("<int:upload_id>/download/", UploadDownloadView.as_view(), name="upload-download"),
    path("", UploadListCreateView.as_view(), name="upload-list-create"),
    path("sessions/", UploadSessionCreateView.as_view(), name="upload-session-create"),
    path("sessions/<uuid:session_id>/", UploadSessionStatusView.as_view(), name="upload-session-status"),
    path("sessions/<uuid:session_id>/complete/", CompleteUploadView.as_view(), name="upload-session-complete"),
    path("sessions/<uuid:session_id>/chunks/<int:index>/", UploadChunkView.as_view(), name="upload-chunk"),
]