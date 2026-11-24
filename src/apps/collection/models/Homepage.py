"""
Esup-Pod - Homepage model.
"""

from django.db import models
from src.apps.video.models import Video


class Homepage(models.Model):
    """Model to store configuration for frontend homepage."""

    video = models.ForeignKey(
        Video, on_delete=models.CASCADE, related_name="homepage_videos"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        """Homepage metadata."""

        verbose_name = "Homepage"
        verbose_name_plural = "Homepages"
        ordering = ["id"]
