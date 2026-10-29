from django.db.models import Q
from django.shortcuts import get_object_or_404

from .models import Upload, UploadSession


def sessions_visible_to(user):
    return UploadSession.objects.filter(
        Q(owner=user)
        | Q(
            created_by=user,
            owner__editor_accesses__editor=user,
            owner__editor_accesses__status="accepted",
        )
    ).distinct()


def uploads_visible_to(user):
    # Completed videos and their downloads are creator-only. Editors can still
    # access their resumable sessions through sessions_visible_to().
    return Upload.objects.filter(owner=user)


def get_accessible_session(user, session_id, lock=False):
    if lock:
        # Lock the single session row first. PostgreSQL does not allow
        # SELECT FOR UPDATE on the DISTINCT access query.
        session = get_object_or_404(
            UploadSession.objects.select_for_update(),
            id=session_id,
        )
        return get_object_or_404(
            sessions_visible_to(user),
            id=session.id,
        )

    return get_object_or_404(
        sessions_visible_to(user),
        id=session_id,
    )
