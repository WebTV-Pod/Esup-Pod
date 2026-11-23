"""
Esup-Pod - Featured video model.
"""

# src/apps/collection/models/FeaturedVideo.py
from django.conf import settings
from django.contrib.sites.models import Site
from django.db import models
from django.db.models import Max
from django.utils.translation import gettext_lazy as _

from src.apps.video.models.Video import Video


class FeaturedVideo(models.Model):
    """Editorial selection ("coup de coeur") of a video on a given site."""

    site = models.ForeignKey(
        Site, on_delete=models.CASCADE, related_name="featured_videos"
    )
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="featured_in")
    position = models.PositiveIntegerField(_("Position"), default=0)
    featured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Define database metadata for featured videos."""

        verbose_name = _("Featured video")
        verbose_name_plural = _("Featured videos")
        unique_together = ("site", "video")
        ordering = ["position", "-added_at"]

    def save(self, *args, **kwargs):
        """Auto-calculate position if not provided (same logic as PlaylistItem)."""
        if not self.position:
            max_pos = FeaturedVideo.objects.filter(site=self.site).aggregate(
                Max("position")
            )["position__max"]
            self.position = (max_pos or 0) + 1
        super().save(*args, **kwargs)
