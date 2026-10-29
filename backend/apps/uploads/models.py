from django.conf import settings
from django.db import models

YOUTUBE_PRIVACY_CHOICES = [
    ("private", "Private"),
    ("unlisted", "Unlisted"),
    ("public", "Public"),
]


class Upload(models.Model):
    YOUTUBE_STATUS_CHOICES = [
        ("not_started", "Not started"),
        ("queued", "Queued"),
        ("publishing", "Publishing"),
        ("published", "Published"),
        ("failed", "Failed"),
    ]

    STATUS_CHOICES = [
        ("uploaded", "Uploaded"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="uploads",
        null=True,
        blank=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_videos",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    youtube_privacy = models.CharField(
        max_length=10,
        choices=YOUTUBE_PRIVACY_CHOICES,
        default="private",
    )
    file = models.FileField(upload_to="uploads/%Y/%m/")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="uploaded",
    )
    youtube_status = models.CharField(
        max_length=20,
        choices=YOUTUBE_STATUS_CHOICES,
        default="not_started",
    )
    youtube_video_id = models.CharField(max_length=64, blank=True)
    youtube_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["owner", "-created_at"], name="upl_owner_created_idx"),
        ]

    def __str__(self):
        return self.title


class UploadSession(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("queued", "Queued"),
        ("assembling", "Assembling"),
        ("awaiting_approval", "Awaiting approval"),
        ("rejected", "Rejected"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=__import__("uuid").uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="upload_sessions",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_upload_sessions",
    )
    client_key = models.CharField(max_length=100)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    youtube_privacy = models.CharField(
        max_length=10,
        choices=YOUTUBE_PRIVACY_CHOICES,
        default="private",
    )
    file_name = models.CharField(max_length=255)
    file_size = models.PositiveBigIntegerField()
    total_chunks = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    completed_upload = models.OneToOneField(
        "Upload", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="upload_session",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "client_key"],
                name="unique_upload_session_per_owner",
            )
        ]


class UploadChunk(models.Model):
    session = models.ForeignKey(
        UploadSession,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    index = models.PositiveIntegerField()
    file = models.FileField(upload_to="upload_chunks/%Y/%m/")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "index"],
                name="unique_chunk_index_per_session",
            )
        ]
