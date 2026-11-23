"""
Esup-Pod - Serializers for the distinct collection models.
"""

from django.contrib.auth import get_user_model
from django.contrib.sites.shortcuts import get_current_site
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from src.apps.collection.models import (
    Channel,
    Favorite,
    FeaturedVideo,
    Playlist,
    PlaylistItem,
    Theme,
    ThemeItem,
)
from src.apps.video.serializers import VideoSerializer

User = get_user_model()


class ChannelSerializer(serializers.ModelSerializer):
    """Serializer for the Channel model."""

    owner_username = serializers.ReadOnlyField(source="owner.username")

    class Meta:
        """ChannelSerializer metadata."""

        model = Channel
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "owner",
            "owner_username",
            "is_public",
            "logo",
            "banner",
            "collaborators",
            "default_order",
            "old_v4_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["slug", "owner", "created_at", "updated_at"]
        extra_kwargs = {
            "is_public": {"required": False},
        }


class ThemeItemSerializer(serializers.ModelSerializer):
    """Serializer for videos within a Theme."""

    video = VideoSerializer(read_only=True)

    class Meta:
        """ThemeItemSerializer metadata."""

        model = ThemeItem
        fields = ["id", "video", "added_at"]


class ThemeSerializer(serializers.ModelSerializer):
    """Recursive serializer for the Theme model."""

    children = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()

    class Meta:
        """ThemeSerializer metadata."""

        model = Theme
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "parent",
            "channel",
            "banner",
            "default_order",
            "old_v4_id",
            "created_at",
            "updated_at",
            "children",
            "items",
        ]
        read_only_fields = ["slug", "created_at", "updated_at"]

    @extend_schema_field(serializers.ListSerializer(child=serializers.DictField()))
    def get_children(self, obj):
        """Recursively serialize children themes."""
        children = obj.children.all()
        if children:
            return ThemeSerializer(children, many=True, context=self.context).data
        return []

    @extend_schema_field(ThemeItemSerializer(many=True))
    def get_items(self, obj):
        """Return theme items, filtering out restricted videos."""
        request = self.context.get("request")
        user = request.user if request and request.user else None

        # We need a user object for visible_for, even if anonymous
        from django.contrib.auth.models import AnonymousUser

        search_user = user or AnonymousUser()
        from src.apps.video.models import Video

        visible_videos = Video.objects.visible_for(search_user)
        items = obj.themeitem_set.filter(video__in=visible_videos)

        # Apply ordering based on theme default_order field
        order_field = obj.default_order
        if order_field:
            if order_field.startswith("-"):
                django_order = f"-video__{order_field[1:]}"
            else:
                django_order = f"video__{order_field}"
            items = items.order_by(django_order)

        return ThemeItemSerializer(items, many=True, context=self.context).data


class PlaylistItemSerializer(serializers.ModelSerializer):
    """Serializer for videos within a Playlist."""

    video = VideoSerializer(read_only=True)

    class Meta:
        """PlaylistItemSerializer metadata."""

        model = PlaylistItem
        fields = ["id", "video", "position", "added_at"]


class PlaylistSerializer(serializers.ModelSerializer):
    """Serializer for the Playlist model."""

    owner_username = serializers.ReadOnlyField(source="owner.username")
    items = serializers.SerializerMethodField()
    is_protected = serializers.SerializerMethodField()

    class Meta:
        """PlaylistSerializer metadata."""

        model = Playlist
        fields = [
            "id",
            "title",
            "slug",
            "description",
            "owner",
            "owner_username",
            "is_public",
            "password",
            "is_protected",
            "default_order",
            "old_v4_id",
            "created_at",
            "updated_at",
            "items",
        ]
        read_only_fields = ["slug", "owner", "created_at", "updated_at"]
        extra_kwargs = {
            "password": {"write_only": True},
        }

    @extend_schema_field(serializers.BooleanField())
    def get_is_protected(self, obj):
        """Return True if the playlist has a password set."""
        return bool(obj.password)

    @extend_schema_field(serializers.ListSerializer(child=serializers.DictField()))
    def get_items(self, obj):
        """Return playlist items, hiding them if protected and not unlocked."""
        request = self.context.get("request")
        if obj.password:
            is_owner = (
                request and request.user.is_authenticated and request.user == obj.owner
            )
            is_verified = self.context.get("password_verified", False)
            if not (is_owner or is_verified):
                return []

        user = request.user if request and request.user else None
        from django.contrib.auth.models import AnonymousUser

        search_user = user or AnonymousUser()
        from src.apps.video.models import Video

        visible_videos = Video.objects.visible_for(search_user)
        items = obj.items.filter(video__in=visible_videos)

        # Apply ordering based on playlist default_order field
        order_field = obj.default_order
        if order_field:
            if order_field.startswith("-"):
                django_order = f"-video__{order_field[1:]}"
            else:
                django_order = f"video__{order_field}"
            items = items.order_by(django_order)

        return PlaylistItemSerializer(items, many=True, context=self.context).data


class FavoriteSerializer(serializers.ModelSerializer):
    """Serializer for the Favorite model."""

    user_username = serializers.ReadOnlyField(source="user.username")
    video_details = VideoSerializer(source="video", read_only=True)

    class Meta:
        """FavoriteSerializer metadata."""

        model = Favorite
        fields = ["id", "user", "user_username", "video", "video_details", "added_at"]
        read_only_fields = ["user", "added_at"]


class FeaturedVideoSerializer(serializers.ModelSerializer):
    """
    Serializer for the FeaturedVideo model (editorial "coup de coeur").

    The site is never provided by the client: it comes from the request and is
    set by the viewset (``perform_create``). The video cannot be changed once
    the entry is created.
    """

    video_details = VideoSerializer(source="video", read_only=True)
    featured_by_username = serializers.CharField(
        source="featured_by.username", read_only=True, allow_null=True
    )

    class Meta:
        """FeaturedVideoSerializer metadata."""

        model = FeaturedVideo
        fields = [
            "id",
            "video",
            "video_details",
            "position",
            "featured_by",
            "featured_by_username",
            "added_at",
        ]
        read_only_fields = ["featured_by", "added_at"]
        # The (site, video) uniqueness is checked in validate() because the
        # site is not a serializer field (it comes from the request).
        validators = []

    def validate(self, attrs):
        """Check that the video belongs to the current site and is not featured yet."""
        if self.instance is not None:
            return attrs

        video = attrs.get("video")
        if video is None:
            return attrs

        site = get_current_site(self.context.get("request"))
        if not video.sites.filter(pk=site.pk).exists():
            raise serializers.ValidationError(
                {"video": _("This video does not belong to the current site.")}
            )
        if FeaturedVideo.objects.filter(site=site, video=video).exists():
            raise serializers.ValidationError(
                {"video": _("This video is already featured on this site.")}
            )
        return attrs

    def update(self, instance, validated_data):
        """Update an entry without allowing it to be moved to another video."""
        validated_data.pop("video", None)
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        """Hide the editor identity from users who cannot manage the selection."""
        data = super().to_representation(instance)
        user = getattr(self.context.get("request"), "user", None)
        if not (user and user.has_perm("collection.change_featuredvideo")):
            data.pop("featured_by", None)
            data.pop("featured_by_username", None)
        return data
