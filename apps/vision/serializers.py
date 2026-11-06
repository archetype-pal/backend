from rest_framework import serializers

from apps.scribes.models import Hand
from apps.symbols_structure.models import Allograph

from .models import LetterRequest, PageDraft
from .services import page_search
from .services.hand_similarity import MIN_GLYPHS, NearestHands, ScribeNearest


class _HandSummarySerializer(serializers.ModelSerializer):
    item_part_display_label = serializers.CharField(source="item_part.display_label", read_only=True)
    scribe = serializers.SerializerMethodField()
    date = serializers.StringRelatedField()
    place = serializers.StringRelatedField()

    class Meta:
        model = Hand
        fields = ["id", "name", "item_part", "item_part_display_label", "scribe", "date", "place"]

    def get_scribe(self, hand: Hand) -> dict | None:
        # Below pk 1 is the DigiPal import's placeholder for an unattributed hand, not a scribe.
        if hand.scribe_id is None or hand.scribe_id < 1:
            return None
        return {"id": hand.scribe_id, "name": hand.scribe.name}


def similar_hands_data(nearest: NearestHands) -> dict:
    """GET hands/<id>/similar/: the hand's nearest hands and the letters each is compared on."""

    def letter(entry: dict) -> dict:
        allograph = nearest.allographs.get(entry["allograph"])
        return {
            "allograph": entry["allograph"],
            "name": allograph.name if allograph else None,
            "character": allograph.character.name if allograph else None,
            "similarity": entry["similarity"],
            "glyphs": entry["glyphs"],
        }

    return {
        "hand": nearest.hand_id,
        "glyphs": nearest.glyphs,
        "minimum_glyphs": MIN_GLYPHS,
        "vectors": nearest.rows[0].vectors if nearest.rows else None,
        "computed": nearest.rows[0].created.isoformat() if nearest.rows else None,
        "results": [
            {
                "rank": row.rank,
                "similarity": row.similarity,
                "hand": _HandSummarySerializer(row.other).data,
                "letters": [letter(entry) for entry in row.letters],
            }
            for row in nearest.rows
        ],
    }


def scribe_similar_hands_data(nearest: ScribeNearest) -> dict:
    """GET scribes/<id>/similar/: the hands near this scribe's, and how near its own hands come to each other."""
    own = {hand.pk for hand in nearest.hands}
    stored = [row for rows in nearest.rows.values() for row in rows]
    return {
        "scribe": nearest.scribe_id,
        "minimum_glyphs": MIN_GLYPHS,
        "vectors": stored[0].vectors if stored else None,
        "computed": stored[0].created.isoformat() if stored else None,
        "hands": [
            {
                "id": hand.pk,
                "name": hand.name,
                "item_part": hand.item_part_id,
                "item_part_display_label": hand.item_part.display_label(),
                "compared": hand.pk in nearest.rows,
                "siblings": [
                    {"hand": row.other_id, "rank": row.rank, "similarity": row.similarity}
                    for row in nearest.rows.get(hand.pk, [])
                    if row.other_id in own
                ],
            }
            for hand in nearest.hands
        ],
        "results": [
            {
                "hand": _HandSummarySerializer(match.other).data,
                "similarity": match.best,
                "near": [{"hand": row.hand_id, "rank": row.rank, "similarity": row.similarity} for row in match.near],
            }
            for match in nearest.matches
        ],
    }


class FindOnPageRequestSerializer(serializers.Serializer):
    """POST management/vision/pages/<id>/find/: a request in words, or the letter itself."""

    request = serializers.CharField(required=False, max_length=500, trim_whitespace=True)
    allograph = serializers.PrimaryKeyRelatedField(
        queryset=Allograph.objects.select_related("character"), required=False
    )
    hand = serializers.PrimaryKeyRelatedField(queryset=Hand.objects.all(), required=False, allow_null=True)
    count = serializers.IntegerField(required=False, min_value=1, max_value=page_search.MAX_COUNT)

    def validate(self, attrs: dict) -> dict:
        if bool(attrs.get("request")) == bool(attrs.get("allograph")):
            raise serializers.ValidationError("Give either `request` or `allograph`.")
        return attrs


def letter_data(allograph: Allograph) -> dict:
    return {"id": allograph.pk, "name": allograph.name, "character": allograph.character.name}


class PageDraftSerializer(serializers.ModelSerializer):
    """A page's drafting request, as the backoffice follows it."""

    requested_by = serializers.SlugRelatedField(slug_field="username", read_only=True)
    cost_micros = serializers.IntegerField(source="ml_job.cost_micros", read_only=True, default=None)

    class Meta:
        model = PageDraft
        fields = [
            "id",
            "item_image",
            "status",
            "error",
            "requested_by",
            "image_text",
            "ml_job",
            "cost_micros",
            "created",
            "updated",
        ]
        read_only_fields = fields


class LetterRequestSerializer(serializers.ModelSerializer):
    """A request for a page's letters, as the backoffice follows it."""

    requested_by = serializers.SlugRelatedField(slug_field="username", read_only=True)

    class Meta:
        model = LetterRequest
        fields = [
            "id",
            "item_image",
            "status",
            "error",
            "requested_by",
            "ml_job",
            "found",
            "proposed",
            "created",
            "updated",
        ]
        read_only_fields = fields
