"""
Esup-Pod - VideoAccessToken tests.
"""

import sys
from datetime import timedelta
from importlib import reload

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.urls import clear_url_caches
from django.utils import timezone
from rest_framework.test import APITestCase

from src.apps.video.apps import sync_metadata
from src.apps.video.conf import video_settings
from src.apps.video.models import Video, VideoAccessToken


def reload_urlconf():
    """Reloads URL configurations after a settings change."""
    clear_url_caches()
    video_urls = "src.apps.video.urls"
    if video_urls in sys.modules:
        reload(sys.modules[video_urls])
    if settings.ROOT_URLCONF in sys.modules:
        reload(sys.modules[settings.ROOT_URLCONF])


User = get_user_model()


class VideoAccessTokenTests(APITestCase):
    """Tests for the VideoAccessToken API endpoints."""

    def setUp(self):
        """Sets up a video and users for token testing."""
        sync_metadata(sender=None)

        # Save original settings to restore in tearDown
        self.original_use_token = video_settings.use_video_access_token

        video_settings.use_video_access_token = True
        reload_urlconf()

        self.site = Site.objects.get_current()
        self.owner = User.objects.create_user(
            username="owner", password="password"
        )  # nosec
        self.other_user = User.objects.create_user(
            username="other", password="password"
        )  # nosec
        self.video = Video.objects.create(
            title="Token Test Video",
            owner=self.owner,
            status=Video.Status.RESTRICTED,
        )
        self.video.sites.add(self.site)

    def tearDown(self):
        """Restore original settings and reload URLs to prevent test leakage."""
        video_settings.use_video_access_token = self.original_use_token
        reload_urlconf()

    def test_owner_can_create_token(self):
        """Owner can create an access token for their own video."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/tokens/",
            {"video": self.video.id, "label": "Shared with John"},
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            VideoAccessToken.objects.filter(
                video=self.video, created_by=self.owner
            ).exists()
        )
        self.assertIn("token", response.data)

    def test_non_owner_cannot_create_token(self):
        """A user who is not owner/co-owner cannot create a token for the video."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.post(
            "/api/tokens/",
            {"video": self.video.id, "label": "Unauthorized"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(VideoAccessToken.objects.filter(video=self.video).exists())

    def test_resolve_valid_token(self):
        """Resolving a valid token returns video info."""
        token = VideoAccessToken.objects.create(video=self.video, created_by=self.owner)

        response = self.client.get(f"/api/tokens/resolve/{token.token}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["video_slug"], self.video.slug)

        token.refresh_from_db()
        self.assertEqual(token.use_count, 1)
        self.assertIsNotNone(token.last_used_at)

    def test_resolve_invalid_token(self):
        """Resolving a non-existent token returns 404."""
        response = self.client.get(
            "/api/tokens/resolve/00000000-0000-0000-0000-000000000000/"
        )
        self.assertEqual(response.status_code, 404)

    def test_resolve_valid_token_from_query_parameter(self):
        """Resolving a valid token is supported on the base resolve route."""
        token = VideoAccessToken.objects.create(video=self.video, created_by=self.owner)

        response = self.client.get("/api/tokens/resolve/", {"token": str(token.token)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["video_slug"], self.video.slug)

    def test_resolve_valid_token_from_request_body(self):
        """Resolving a valid token is supported via POST."""
        token = VideoAccessToken.objects.create(video=self.video, created_by=self.owner)

        response = self.client.post(
            "/api/tokens/resolve/",
            {"token": str(token.token)},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["video_slug"], self.video.slug)

    def test_resolve_requires_token_on_base_route(self):
        """The base resolve route rejects requests without a token."""
        response = self.client.get("/api/tokens/resolve/")

        self.assertEqual(response.status_code, 400)

    def test_resolve_revoked_token(self):
        """Resolving a revoked token returns 403."""
        token = VideoAccessToken.objects.create(
            video=self.video, created_by=self.owner, is_active=False
        )

        response = self.client.get(f"/api/tokens/resolve/{token.token}/")
        self.assertEqual(response.status_code, 403)

    def test_resolve_expired_token(self):
        """Resolving an expired token returns 403."""
        token = VideoAccessToken.objects.create(
            video=self.video,
            created_by=self.owner,
            expires_at=timezone.now() - timedelta(days=1),
        )

        response = self.client.get(f"/api/tokens/resolve/{token.token}/")
        self.assertEqual(response.status_code, 403)

    def test_revoke_token(self):
        """Owner can revoke their own token."""
        token = VideoAccessToken.objects.create(video=self.video, created_by=self.owner)

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(f"/api/tokens/{token.id}/revoke/")

        self.assertEqual(response.status_code, 200)
        token.refresh_from_db()
        self.assertFalse(token.is_active)

    def test_user_only_sees_own_tokens(self):
        """A user only sees tokens they created, not others'."""
        VideoAccessToken.objects.create(video=self.video, created_by=self.owner)
        VideoAccessToken.objects.create(video=self.video, created_by=self.other_user)

        self.client.force_authenticate(user=self.owner)
        response = self.client.get("/api/tokens/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)

    def test_expiry_in_the_past_rejected(self):
        """Creating a token with a past expiry date is rejected."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/tokens/",
            {
                "video": self.video.id,
                "expires_at": (timezone.now() - timedelta(days=1)).isoformat(),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_expiry_exceeding_max_validity_rejected(self):
        """Creating a token with expiry exceeding max validity is rejected."""
        self.client.force_authenticate(user=self.owner)
        far_future = timezone.now() + timedelta(days=400)
        response = self.client.post(
            "/api/tokens/",
            {"video": self.video.id, "expires_at": far_future.isoformat()},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_feature_disabled_blocks_creation(self):
        """When the feature is disabled, token creation is blocked."""
        video_settings.use_video_access_token = False

        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/tokens/",
            {"video": self.video.id},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        video_settings.use_video_access_token = True

    def test_unauthenticated_cannot_list_tokens(self):
        """Unauthenticated users cannot list tokens."""
        response = self.client.get("/api/tokens/")
        self.assertEqual(response.status_code, 401)


class VideoAccessTokenAccessTests(APITestCase):
    """Tests that a share token (X-Video-Token header) really unlocks its video."""

    def setUp(self):
        """Sets up a private draft video and a token."""
        sync_metadata(sender=None)
        self.original_use_token = video_settings.use_video_access_token
        video_settings.use_video_access_token = True
        reload_urlconf()

        self.site = Site.objects.get_current()
        self.owner = User.objects.create_user(
            username="owner2", password="password"  # nosec
        )
        self.video = Video.objects.create(
            title="Private Video", owner=self.owner, status=Video.Status.DRAFT
        )
        self.video.sites.add(self.site)
        self.other_video = Video.objects.create(
            title="Other Private Video", owner=self.owner, status=Video.Status.DRAFT
        )
        self.other_video.sites.add(self.site)
        self.token = VideoAccessToken.objects.create(
            video=self.video, created_by=self.owner
        )

    def tearDown(self):
        """Restore original settings and reload URLs."""
        video_settings.use_video_access_token = self.original_use_token
        reload_urlconf()

    def _get(self, video, token=None):
        headers = {"HTTP_X_VIDEO_TOKEN": str(token)} if token else {}
        return self.client.get(f"/api/videos/{video.slug}/", **headers)

    def test_anonymous_cannot_see_draft_without_token(self):
        """Without a token, an anonymous user cannot retrieve a draft video."""
        self.assertEqual(self._get(self.video).status_code, 404)

    def test_valid_token_unlocks_draft_video(self):
        """A valid token lets an anonymous user retrieve the draft video."""
        response = self._get(self.video, self.token.token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["slug"], self.video.slug)

    def test_token_does_not_expose_raw_video_url(self):
        """The raw media URL is never returned for a draft video."""
        response = self._get(self.video, self.token.token)
        self.assertIsNone(response.data["video_url"])

    def test_token_only_unlocks_its_own_video(self):
        """A token for video A does not unlock video B."""
        self.assertEqual(self._get(self.other_video, self.token.token).status_code, 404)

    def test_revoked_token_does_not_unlock(self):
        """A revoked token no longer grants access."""
        self.token.is_active = False
        self.token.save(update_fields=["is_active"])
        self.assertEqual(self._get(self.video, self.token.token).status_code, 404)

    def test_expired_token_does_not_unlock(self):
        """An expired token no longer grants access."""
        self.token.expires_at = timezone.now() - timedelta(minutes=1)
        self.token.save(update_fields=["expires_at"])
        self.assertEqual(self._get(self.video, self.token.token).status_code, 404)

    def test_malformed_token_is_ignored(self):
        """A malformed header value is ignored (no 500)."""
        self.assertEqual(self._get(self.video, "not-a-uuid").status_code, 404)

    def test_feature_disabled_ignores_token(self):
        """When the feature is disabled, tokens grant nothing."""
        video_settings.use_video_access_token = False
        self.assertEqual(self._get(self.video, self.token.token).status_code, 404)

    def test_valid_token_allows_stream_token_creation(self):
        """A valid share token allows creating the ephemeral stream token."""
        url = f"/api/videos/{self.video.slug}/create-stream-token/"
        self.assertEqual(self.client.post(url).status_code, 403)
        response = self.client.post(url, HTTP_X_VIDEO_TOKEN=str(self.token.token))
        self.assertEqual(response.status_code, 200)
        self.assertIn("stream_token", response.data)

    def test_token_url_points_to_frontend(self):
        """token_url is a frontend URL carrying the video slug and the token."""
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(f"/api/tokens/?video={self.video.id}")
        self.assertEqual(response.status_code, 200)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        expected = (
            f"{video_settings.front_url.rstrip('/')}"
            f"/video/{self.video.slug}/?token={self.token.token}"
        )
        self.assertEqual(results[0]["token_url"], expected)

    def test_list_filtered_by_video(self):
        """?video=<id> only returns tokens of that video."""
        VideoAccessToken.objects.create(video=self.other_video, created_by=self.owner)
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(f"/api/tokens/?video={self.other_video.id}")
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["video"], self.other_video.id)
