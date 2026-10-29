import logging
from django.core.validators import EmailValidator
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.authtoken.models import Token

from .models import CreatorEditorAccess, Profile

logger = logging.getLogger(__name__)


def access_data(access):
    return {
        "id": access.id,
        "creator": access.creator.username,
        "editor": access.editor.username,
        "status": access.status,
        "created_at": access.created_at,
    }


class CurrentProfileView(APIView):
    def get(self, request):
        profile = get_object_or_404(Profile, user=request.user)
        return Response({
            "id": request.user.id,
            "username": request.user.username,
            "role": profile.role,
        })


class EditorCreatorListView(APIView):
    def get(self, request):
        if not Profile.objects.filter(user=request.user, role="editor").exists():
            return Response({"detail": "Only editors can view accepted creators."}, status=403)

        accesses = CreatorEditorAccess.objects.filter(
            editor=request.user,
            status="accepted",
        ).select_related("creator").order_by("creator__username")

        return Response([
            {"id": access.creator_id, "username": access.creator.username}
            for access in accesses
        ])


class CreatorEditorAccessView(APIView):
    def get(self, request):
        if not Profile.objects.filter(user=request.user, role="creator").exists():
            return Response({"detail": "Only creators can view their editor access."}, status=403)

        accesses = CreatorEditorAccess.objects.filter(
            creator=request.user
        ).select_related("creator", "editor").order_by("-created_at")
        return Response([access_data(access) for access in accesses])

    def post(self, request):
        if not Profile.objects.filter(user=request.user, role="creator").exists():
            return Response({"detail": "Only creators can invite editors."}, status=403)

        username = str(request.data.get("editor_username", "")).strip()
        if not username:
            return Response({"detail": "Provide an editor username."}, status=400)

        User = get_user_model()
        editor = User.objects.filter(username=username).first()
        if editor is None:
            return Response({"detail": "That user does not exist."}, status=404)

        if editor == request.user:
            return Response({"detail": "You cannot invite yourself."}, status=400)

        if not Profile.objects.filter(user=editor, role="editor").exists():
            return Response({"detail": "That user is not assigned the editor role."}, status=400)

        access, created = CreatorEditorAccess.objects.get_or_create(
            creator=request.user,
            editor=editor,
            defaults={"status": "pending"},
        )

        if not created and access.status in ("rejected", "revoked"):
            access.status = "pending"
            access.save(update_fields=["status"])

        return Response(
            access_data(access),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class EditorInvitationListView(APIView):
    def get(self, request):
        if not Profile.objects.filter(user=request.user, role="editor").exists():
            return Response({"detail": "Only editors can view invitations."}, status=403)

        invitations = CreatorEditorAccess.objects.filter(
            editor=request.user,
            status="pending",
        ).select_related("creator", "editor").order_by("-created_at")
        return Response([access_data(invitation) for invitation in invitations])


class EditorInvitationDecisionView(APIView):
    def post(self, request, access_id):
        if not Profile.objects.filter(user=request.user, role="editor").exists():
            return Response({"detail": "Only editors can respond to invitations."}, status=403)

        invitation = get_object_or_404(
            CreatorEditorAccess,
            id=access_id,
            editor=request.user,
        )

        if invitation.status != "pending":
            return Response({"detail": "This invitation has already been answered."}, status=409)

        decision = request.data.get("decision")
        if decision not in ("accept", "reject"):
            return Response({"detail": "Decision must be accept or reject."}, status=400)

        invitation.status = "accepted" if decision == "accept" else "rejected"
        invitation.save(update_fields=["status"])
        return Response(access_data(invitation))

class CreatorEditorAccessDetailView(APIView):
    def delete(self, request, access_id):
        if not Profile.objects.filter(user=request.user, role="creator").exists():
            return Response({"detail": "Only creators can revoke editor access."}, status=403)

        access = get_object_or_404(
            CreatorEditorAccess,
            id=access_id,
            creator=request.user,
        )
        access.status = "revoked"
        access.save(update_fields=["status"])
        return Response(access_data(access))

class UserRegistrationView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        User = get_user_model()
        username = str(request.data.get("username", "")).strip()
        email = str(request.data.get("email", "")).strip().lower()
        password = str(request.data.get("password", ""))
        role = str(request.data.get("role", "")).strip().lower()

        if not username or not email or not password:
            return Response({"detail": "Username, email, and password are required."}, status=400)

        if role not in ("creator", "editor"):
            return Response({"detail": "Choose Creator or Editor as your role."}, status=400)

        if User.objects.filter(username__iexact=username).exists():
            return Response({"detail": "That username is already taken."}, status=400)

        if User.objects.filter(email__iexact=email).exists():
            return Response({"detail": "That email is already registered."}, status=400)

        try:
            User._meta.get_field("username").clean(username, None)
            EmailValidator()(email)
            validate_password(password, user=User(username=username, email=email))
        except ValidationError as error:
            return Response({"detail": error.messages}, status=400)

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
        )
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.role = role
        profile.save(update_fields=["role"])

        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "token": token.key,
                "username": user.username,
                "role": profile.role,
            },
            status=status.HTTP_201_CREATED,
        )


class YouTubeConnectView(APIView):
    def post(self, request):
        from django.conf import settings
        from rest_framework.permissions import IsAuthenticated
        from google_auth_oauthlib.flow import Flow
        from cryptography.fernet import Fernet
        from .models import YouTubeOAuthState

        if not Profile.objects.filter(user=request.user, role="creator").exists():
            return Response({"detail": "Only creators can connect a YouTube channel."}, status=403)

        if not settings.YOUTUBE_CLIENT_ID or not settings.YOUTUBE_CLIENT_SECRET:
            return Response({"detail": "YouTube OAuth credentials are not configured."}, status=503)
        if not settings.YOUTUBE_TOKEN_ENCRYPTION_KEY:
            return Response({"detail": "YouTube token encryption is not configured."}, status=503)

        oauth_state = YouTubeOAuthState.objects.create(user=request.user)
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.YOUTUBE_CLIENT_ID,
                    "client_secret": settings.YOUTUBE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [settings.YOUTUBE_REDIRECT_URI],
                }
            },
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.readonly",
            ],
            redirect_uri=settings.YOUTUBE_REDIRECT_URI,
        )
        authorization_url, _ = flow.authorization_url(
            state=str(oauth_state.pk),
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        oauth_state.code_verifier_encrypted = Fernet(
            settings.YOUTUBE_TOKEN_ENCRYPTION_KEY.encode()
        ).encrypt(flow.code_verifier.encode()).decode()
        oauth_state.save(update_fields=["code_verifier_encrypted"])
        return Response({"authorization_url": authorization_url})


class YouTubeOAuthCallbackView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        from datetime import timedelta
        from django.conf import settings
        from django.shortcuts import get_object_or_404, redirect
        from django.utils import timezone
        from google_auth_oauthlib.flow import Flow
        from googleapiclient.discovery import build
        from cryptography.fernet import Fernet
        from .models import YouTubeConnection, YouTubeOAuthState

        if request.query_params.get("error"):
            return Response({"detail": "YouTube authorization was cancelled or denied."}, status=400)

        state_id = request.query_params.get("state", "")
        oauth_state = get_object_or_404(
            YouTubeOAuthState,
            state=state_id,
            created_at__gte=timezone.now() - timedelta(minutes=10),
        )
        user = oauth_state.user

        if not Profile.objects.filter(user=user, role="creator").exists():
            oauth_state.delete()
            return Response({"detail": "Only creator accounts can connect YouTube."}, status=403)

        if not settings.YOUTUBE_TOKEN_ENCRYPTION_KEY:
            oauth_state.delete()
            return Response({"detail": "YouTube token encryption is not configured."}, status=503)

        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.YOUTUBE_CLIENT_ID,
                    "client_secret": settings.YOUTUBE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [settings.YOUTUBE_REDIRECT_URI],
                }
            },
            scopes=[
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.readonly",
            ],
            state=state_id,
            code_verifier=Fernet(settings.YOUTUBE_TOKEN_ENCRYPTION_KEY.encode())
            .decrypt(oauth_state.code_verifier_encrypted.encode()).decode(),
            autogenerate_code_verifier=False,
            redirect_uri=settings.YOUTUBE_REDIRECT_URI,
        )

        try:
            flow.fetch_token(authorization_response=request.build_absolute_uri())
            credentials = flow.credentials
            youtube = build("youtube", "v3", credentials=credentials, cache_discovery=False)
            channels = youtube.channels().list(part="snippet", mine=True).execute().get("items", [])

            if not channels:
                oauth_state.delete()
                return Response({"detail": "No YouTube channel was found for this Google account."}, status=400)

            channel = channels[0]
            existing = YouTubeConnection.objects.filter(creator=user).first()
            refresh_token = credentials.refresh_token or (
                Fernet(settings.YOUTUBE_TOKEN_ENCRYPTION_KEY.encode())
                .decrypt(existing.refresh_token_encrypted.encode())
                .decode()
                if existing else None
            )

            if not refresh_token:
                oauth_state.delete()
                return Response({"detail": "Google did not return a refresh token. Try connecting again."}, status=400)

            encrypted_token = Fernet(
                settings.YOUTUBE_TOKEN_ENCRYPTION_KEY.encode()
            ).encrypt(refresh_token.encode()).decode()

            YouTubeConnection.objects.update_or_create(
                creator=user,
                defaults={
                    "channel_id": channel["id"],
                    "channel_title": channel["snippet"]["title"],
                    "refresh_token_encrypted": encrypted_token,
                },
            )
            oauth_state.delete()
            return redirect("http://localhost:5173/?youtube=connected")
        except Exception:
            logger.exception("YouTube OAuth callback failed")
            oauth_state.delete()
            return Response(
                {"detail": "YouTube connection failed. Check the Django terminal for the error."},
                status=400,
            )


class YouTubeConnectionStatusView(APIView):
    def get(self, request):
        from .models import YouTubeConnection

        connection = YouTubeConnection.objects.filter(creator=request.user).first()
        if not connection:
            return Response({"connected": False})

        return Response({
            "connected": True,
            "channel_id": connection.channel_id,
            "channel_title": connection.channel_title,
        })
