import uuid
from django.conf import settings
from django.db import models


class Profile(models.Model):
    ROLE_CHOICES = [
        ("creator", "Creator"),
        ("editor", "Editor"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default="creator",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} ({self.role})"

class CreatorEditorAccess(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("revoked", "Revoked"),
        ("rejected", "Rejected"),
    ]

    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="editor_accesses",
    )
    editor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="creator_accesses",
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="pending",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["creator", "editor"],
                name="unique_creator_editor_access",
            )
        ]

    def __str__(self):
        return f"{self.creator.username} → {self.editor.username} ({self.status})"

class YouTubeOAuthState(models.Model):
    state = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="youtube_oauth_states",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    code_verifier_encrypted = models.TextField(blank=True)


class YouTubeConnection(models.Model):
    creator = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="youtube_connection",
    )
    channel_id = models.CharField(max_length=100)
    channel_title = models.CharField(max_length=255)
    refresh_token_encrypted = models.TextField()
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.creator.username}: {self.channel_title}"