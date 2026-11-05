from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsSuperuser
from apps.manuscripts.models import ItemImage
from apps.ml.models import MLJob
from apps.scribes.models import Hand, Scribe

from . import images
from .models import PageDraft
from .serializers import (
    FindOnPageRequestSerializer,
    PageDraftSerializer,
    letter_data,
    scribe_similar_hands_data,
    similar_hands_data,
)
from .services import hand_similarity, page_drafts, page_search


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


# Each refusal of a draft as the status a client can act on.
DRAFT_STATUS_FOR = {
    page_drafts.Unavailable: status.HTTP_503_SERVICE_UNAVAILABLE,
    page_drafts.CapReached: status.HTTP_429_TOO_MANY_REQUESTS,
    page_drafts.Transcribed: status.HTTP_409_CONFLICT,
    page_drafts.Busy: status.HTTP_409_CONFLICT,
}


class PageDraftView(APIView):
    """W1.4: draft this page's transcription with a model, when a user asks; or follow the page's latest draft.

    Asking answers 202 at once with the draft, which the page then follows: the
    reading runs in a worker and takes a minute or two.
    """

    permission_classes = [IsSuperuser]

    def get(self, request, pk: int):
        image = get_object_or_404(ItemImage, pk=pk)
        draft = PageDraft.objects.filter(item_image=image).select_related("requested_by", "ml_job").first()
        if draft is None:
            raise NotFound("This page has not been drafted.")
        return Response(PageDraftSerializer(draft).data)

    def post(self, request, pk: int):
        image = get_object_or_404(ItemImage, pk=pk)
        try:
            draft = page_drafts.request_draft(image, actor=request.user)
        except page_drafts.DraftError as exc:
            body: dict = {"detail": str(exc)}
            if isinstance(exc, page_drafts.Busy):
                body["draft"] = PageDraftSerializer(exc.draft).data
            if isinstance(exc, page_drafts.Transcribed):
                body["image_text"] = exc.text.pk
            return Response(body, status=DRAFT_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST))
        return Response(PageDraftSerializer(draft).data, status=status.HTTP_202_ACCEPTED)


class PageDraftFilterSet(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=PageDraft.Status.choices)

    class Meta:
        model = PageDraft
        fields = ["item_image", "status"]


class PageDraftListView(generics.ListAPIView):
    """W1.4: the pages users have asked to have drafted, newest first.

    `?status=queued&status=working` gives the drafts under way.
    """

    permission_classes = [IsSuperuser]
    queryset = PageDraft.objects.select_related("requested_by", "ml_job")
    serializer_class = PageDraftSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = PageDraftFilterSet


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
