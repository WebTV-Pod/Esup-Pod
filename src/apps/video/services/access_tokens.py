"""
Esup-Pod - Video share token helpers.

The frontend sends the share token in the `X-Video-Token` header. These helpers
validate it server-side so a valid token grants access to *its* video only.
"""

import uuid

from src.apps.video.conf import video_settings
from src.apps.video.models import VideoAccessToken

SHARE_TOKEN_HEADER = "X-Video-Token"


def extract_share_token(request) -> uuid.UUID | None:
    """Returns the share token sent with the request, or None if absent/malformed."""
    if not video_settings.use_video_access_token:
        return None
    raw = request.headers.get(SHARE_TOKEN_HEADER)
    if not raw:
        return None
    try:
        return uuid.UUID(raw.strip())
    except ValueError:
        return None


def share_token_video_ids(request):
    """
    Returns a queryset of video ids unlocked by the request's share token,
    or None when the request carries no usable token.
    """
    token = extract_share_token(request)
    if token is None:
        return None
    return VideoAccessToken.objects.valid().filter(token=token).values("video_id")


def has_valid_share_token(request, video) -> bool:
    """True if the request carries an active, non-expired token for this video."""
    video_ids = share_token_video_ids(request)
    return video_ids is not None and video_ids.filter(video_id=video.pk).exists()
