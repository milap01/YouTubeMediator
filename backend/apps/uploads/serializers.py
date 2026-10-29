from pathlib import Path

from rest_framework import serializers
from .models import Upload


class UploadSerializer(serializers.ModelSerializer):
    youtube_error = serializers.SerializerMethodField()

    class Meta:
        model = Upload
        fields = ["id", "title", "description", "youtube_privacy", "file", "status", "youtube_status", "youtube_video_id", "youtube_error", "created_at"]
        read_only_fields = ["id", "status", "created_at"]

    def get_youtube_error(self, obj):
        request = self.context.get("request")
        if request and obj.owner_id == request.user.id:
            return obj.youtube_error
        return ""

    def validate_title(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Enter a video title.")
        return value

    def validate_file(self, file):
        max_size = 500 * 1024 * 1024
        allowed_extensions = {".mp4", ".mov", ".webm", ".mkv"}

        if file.size > max_size:
            raise serializers.ValidationError("The file must be 500 MB or smaller.")

        extension = Path(file.name).suffix.lower()
        if extension not in allowed_extensions:
            raise serializers.ValidationError(
                "Supported formats are MP4, MOV, WebM, and MKV."
            )

        return file