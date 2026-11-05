from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsSuperuser
from apps.manuscripts.models import ItemImage
from apps.ml.models import MLJob
from apps.scribes.models import Hand, Scribe

from . import images
from .serializers import (
    FindOnPageRequestSerializer,
    letter_data,
    scribe_similar_hands_data,
    similar_hands_data,
)
from .services import hand_similarity, page_search


class SimilarHandsView(APIView):
    """W1.3: the hands whose letters are most like this hand's."""

    permission_classes = [AllowAny]

    def get(self, request, pk: int):
        try:
            nearest = hand_similarity.nearest_hands(pk)
        except Hand.DoesNotExist:
            raise NotFound("No such hand.") from None
        return Response(similar_hands_data(nearest))


class ScribeSimilarHandsView(APIView):
    """W1.3: the hands whose letters are most like a scribe's hands."""

    permission_classes = [AllowAny]

    def get(self, request, pk: int):
        try:
            nearest = hand_similarity.nearest_to_scribe(pk)
        except Scribe.DoesNotExist:
            raise NotFound("No such scribe.") from None
        return Response(scribe_similar_hands_data(nearest))


class FindOnPageView(APIView):
    """W3.4: "label every long-s on this folio". Files what it finds as proposals for review."""

    permission_classes = [IsSuperuser]

    def post(self, request, pk: int):
        image = get_object_or_404(ItemImage, pk=pk)
        body = FindOnPageRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            letters = page_search.page_letters(image)
        except images.ImageUnavailable as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        allograph = body.validated_data.get("allograph")
        if allograph is None:
            readings = page_search.read_request(body.validated_data["request"], letters)
            if not readings:
                return Response({"status": "cannot", "reason": "unknown_letter", "options": _options(letters)})
            if len(readings) > 1:
                return Response({"status": "ask", "options": _options(letters, readings)})
            allograph = readings[0]

        try:
            search = page_search.find_on_page(
                letters,
                allograph,
                hand=body.validated_data.get("hand"),
                count=body.validated_data.get("count", page_search.DEFAULT_COUNT),
                actor=request.user,
            )
        except page_search.CannotSearch as exc:
            return Response(
                {"status": "cannot", "reason": exc.reason, "allograph": letter_data(allograph), **exc.details}
            )
        except images.ImageUnavailable as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        if search.job.status != MLJob.Status.SUCCEEDED:
            return Response(
                {"detail": search.job.error or "The search did not run.", "job": search.job.pk},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            {
                "status": "proposed",
                "allograph": letter_data(search.allograph),
                "hand": search.hand.pk if search.hand else None,
                "examples": search.examples,
                "job": search.job.pk,
                "proposed": len(search.proposals),
            },
            status=status.HTTP_201_CREATED,
        )


def _options(letters: page_search.PageLetters, readings=None) -> list[dict]:
    """The letters a request could mean, or every letter marked on the page, with their example counts."""
    from apps.symbols_structure.models import Allograph

    allographs = readings
    if allographs is None:
        allographs = sorted(
            Allograph.objects.filter(pk__in=letters.by_allograph).select_related("character"),
            key=lambda allograph: (allograph.character.name, allograph.name),
        )
    return [
        {"allograph": letter_data(allograph), "examples": len(letters.examples(allograph.pk))}
        for allograph in allographs
    ]
