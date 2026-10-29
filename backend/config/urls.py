from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from rest_framework.authtoken.views import obtain_auth_token
from apps.accounts.views import (
    CreatorEditorAccessDetailView,
    CreatorEditorAccessView,
    CurrentProfileView,
    EditorCreatorListView,
    EditorInvitationDecisionView,
    EditorInvitationListView,
    UserRegistrationView,
    YouTubeConnectView,
    YouTubeOAuthCallbackView,
    YouTubeConnectionStatusView,
)


def health(request):
    return JsonResponse({"status": "ok", "service": "youtube-mediator-api"})


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/token/", obtain_auth_token),
    path("api/register/", UserRegistrationView.as_view()),
    path("api/youtube/connect/", YouTubeConnectView.as_view()),
    path("api/youtube/oauth/callback/", YouTubeOAuthCallbackView.as_view()),
    path("api/youtube/status/", YouTubeConnectionStatusView.as_view()),
    path("api/me/", CurrentProfileView.as_view()),
    path("api/editor-creators/", EditorCreatorListView.as_view()),
    path("api/uploads/", include("apps.uploads.urls")),
    path("api/collaborations/", CreatorEditorAccessView.as_view()),
    path("api/collaborations/<int:access_id>/", CreatorEditorAccessDetailView.as_view()),

    path("api/editor-invitations/", EditorInvitationListView.as_view()),
    path(
        "api/editor-invitations/<int:access_id>/decision/",
        EditorInvitationDecisionView.as_view(),
    ),
]