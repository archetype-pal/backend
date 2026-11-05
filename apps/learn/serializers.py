from typing import Any

from django.conf import settings
from django.urls import reverse
from rest_framework import serializers

from apps.manuscripts.models import ItemImage

from .models import TutorSession
from .services import tutor


class StartSessionSerializer(serializers.Serializer):
    """A corpus page by id, or a picture of the student's own, not both."""

    item_image = serializers.PrimaryKeyRelatedField(queryset=ItemImage.objects.all(), required=False)
    # A plain file rather than DRF's ImageField: the picture is checked, decoded
    # within bounds and turned upright by the service, which refuses what it
    # cannot read in words fit for the student.
    picture = serializers.FileField(required=False)
    language = serializers.ChoiceField(choices=sorted(tutor.LANGUAGES), default="en")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if ("item_image" in attrs) == ("picture" in attrs):
            raise serializers.ValidationError("Send either item_image or picture.")
        return attrs


class QuestionSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000, trim_whitespace=True)


class PageSerializer(serializers.ModelSerializer):
    """A corpus page offered to learn from."""

    label = serializers.SerializerMethodField()
    charter = serializers.SerializerMethodField()
    date = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = ItemImage
        fields = ("id", "label", "charter", "date", "thumbnail_url")
        read_only_fields = fields

    def get_label(self, page: ItemImage) -> str:
        return str(page)

    def get_charter(self, page: ItemImage) -> str:
        return str(page.item_part.historical_item)

    def get_date(self, page: ItemImage) -> str:
        historical = page.item_part.historical_item
        return str(historical.date) if historical.date_id else ""

    def get_thumbnail_url(self, page: ItemImage) -> str | None:
        try:
            identifier = page.image.iiif.identifier
        except (AttributeError, TypeError, ValueError):  # fmt: skip
            return None
        return f"{identifier}/full/!400,400/0/default.jpg"


class TutorSessionSerializer(serializers.ModelSerializer):
    """A lesson as its page shows it, to whoever has its link.

    `cost_micros`, the transcript and the requester's key are absent: what a
    lesson cost is an operator's business, the transcript is the model's side
    of the conversation, and the key is what the requester is told apart by.
    `can_ask` says whether this requester may ask the lesson more.
    """

    page = serializers.SerializerMethodField()
    picture_url = serializers.SerializerMethodField()
    can_ask = serializers.SerializerMethodField()
    questions_left = serializers.SerializerMethodField()

    class Meta:
        model = TutorSession
        fields = (
            "id",
            "status",
            "error",
            "item_image",
            "page",
            "uploaded",
            "picture_url",
            "width",
            "height",
            "language",
            "walkthrough",
            "messages",
            "progress",
            "can_ask",
            "questions_left",
            "created",
            "updated",
        )
        read_only_fields = fields

    def get_page(self, session: TutorSession) -> dict[str, Any] | None:
        if session.item_image is None:
            return None
        return dict(PageSerializer(session.item_image).data)

    def get_picture_url(self, session: TutorSession) -> str | None:
        if not session.picture:
            return None
        path = reverse("learn-session-picture", kwargs={"pk": session.pk})
        request = self.context.get("request")
        return str(request.build_absolute_uri(path)) if request is not None else path

    def _asked(self, session: TutorSession) -> int:
        return sum(1 for message in session.messages if message.get("role") == "student")

    def get_questions_left(self, session: TutorSession) -> int:
        return max(0, int(settings.LEARN_QUESTIONS_PER_SESSION) - self._asked(session))

    def get_can_ask(self, session: TutorSession) -> bool:
        requester = self.context.get("requester")
        if requester is None:
            return False
        actor, key = requester
        return session.started_by(actor=actor, requester_key=key) and self.get_questions_left(session) > 0
