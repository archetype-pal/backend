from typing import Any

from django.conf import settings
from django.shortcuts import get_object_or_404
from django_filters import rest_framework as filters
from rest_framework import generics, status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.annotations.models import Graph, GraphProposal
from apps.annotations.services import proposals
from apps.common.permissions import CanAnnotate, IsSuperuser
from apps.manuscripts.models import ItemImage
from apps.ml.models import MLJob
from apps.scribes.models import Hand, Scribe

from . import images
from .models import LetterRequest, PageDraft
from .serializers import (
    AssistLanguageSerializer,
    FindOnPageRequestSerializer,
    GraphExplanationSerializer,
    GraphSuggestRequestSerializer,
    LetterRequestSerializer,
    PageDraftSerializer,
    SuggestionRejectSerializer,
    SuggestionSerializer,
    SuggestRequestSerializer,
    letter_data,
    scribe_similar_hands_data,
    similar_hands_data,
)
from .services import glyph_assist, hand_similarity, page_drafts, page_letters, page_search


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


def _search_refused(job: MLJob) -> dict[str, Any]:
    """Why a search did not run, in words for the person who asked; the ledger keeps the operator's."""
    if job.status == MLJob.Status.REFUSED:
        return {
            "detail": "Searching with a model is switched off on this server.",
            "code": "switched_off",
            "job": job.pk,
        }
    return {"detail": "The search did not run.", "code": "failed", "job": job.pk}


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
                _search_refused(search.job),
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
            body: dict = {"detail": str(exc), "code": exc.code}
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


# Each refusal of a letters request as the status a client can act on.
LETTERS_STATUS_FOR = {
    page_letters.Unavailable: status.HTTP_503_SERVICE_UNAVAILABLE,
    page_letters.NoModels: status.HTTP_503_SERVICE_UNAVAILABLE,
    page_letters.CapReached: status.HTTP_429_TOO_MANY_REQUESTS,
    page_letters.Busy: status.HTTP_409_CONFLICT,
}


class PageLettersView(APIView):
    """W1.1: propose this page's letters with the letter models, when a user asks; or follow the latest request.

    Asking answers 202 at once with the request, which the page then follows:
    the models run in a worker. What they find goes to the review queue.
    """

    permission_classes = [IsSuperuser]

    def get(self, request, pk: int):
        image = get_object_or_404(ItemImage, pk=pk)
        run = LetterRequest.objects.filter(item_image=image).select_related("requested_by").first()
        if run is None:
            raise NotFound("Nobody has asked for this page's letters.")
        return Response(LetterRequestSerializer(run).data)

    def post(self, request, pk: int):
        image = get_object_or_404(ItemImage, pk=pk)
        try:
            run = page_letters.request_letters(image, actor=request.user)
        except page_letters.LettersError as exc:
            body: dict = {"detail": str(exc), "code": exc.code}
            if isinstance(exc, page_letters.Busy):
                body["run"] = LetterRequestSerializer(exc.run).data
            return Response(body, status=LETTERS_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST))
        return Response(LetterRequestSerializer(run).data, status=status.HTTP_202_ACCEPTED)


class LetterRequestFilterSet(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=LetterRequest.Status.choices)

    class Meta:
        model = LetterRequest
        fields = ["item_image", "status"]


class PageLettersListView(generics.ListAPIView):
    """W1.1: the pages users have asked to have their letters proposed, newest first.

    `?status=queued&status=working` gives the requests under way.
    """

    permission_classes = [IsSuperuser]
    queryset = LetterRequest.objects.select_related("requested_by")
    serializer_class = LetterRequestSerializer
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = LetterRequestFilterSet


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


class AssistThrottle(UserRateThrottle):
    """How often one account may ask a model about a shape. Read from settings, like the agent's."""

    scope = "assist"

    def get_rate(self):
        if settings.DEBUG:
            return None
        return getattr(settings, "DRF_THROTTLE_ASSIST_RATE", "") or None


# Each refusal as the status a client can act on.
ASSIST_STATUS_FOR = {
    glyph_assist.Unavailable: status.HTTP_503_SERVICE_UNAVAILABLE,
    glyph_assist.CapReached: status.HTTP_429_TOO_MANY_REQUESTS,
    glyph_assist.Refused: status.HTTP_400_BAD_REQUEST,
}


def _assist_failed(exc: glyph_assist.AssistError) -> Response:
    return Response(
        {"detail": str(exc), "code": exc.code},
        status=ASSIST_STATUS_FOR.get(type(exc), status.HTTP_502_BAD_GATEWAY),
    )


class AssistStatusView(APIView):
    """Whether a model can be asked about a shape here, for the viewer to say before anyone asks."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"enabled": glyph_assist.enabled()})


class SuggestView(APIView):
    """W3.5: a researcher asks what the shape they drew is."""

    permission_classes = [CanAnnotate]
    throttle_classes = [AssistThrottle]

    def post(self, request, pk: int):
        image = get_object_or_404(ItemImage, pk=pk)
        body = SuggestRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            proposal = glyph_assist.suggest(
                image,
                body.validated_data["annotation"],
                user=request.user,
                allograph=body.validated_data.get("allograph"),
                language=body.validated_data["language"],
            )
        except glyph_assist.AssistError as exc:
            return _assist_failed(exc)
        return Response(SuggestionSerializer(proposal).data, status=status.HTTP_201_CREATED)


class GraphSuggestView(APIView):
    """W3.5: a researcher asks a model to fill in a saved annotation; it stays as it is until they save."""

    permission_classes = [CanAnnotate]
    throttle_classes = [AssistThrottle]

    def post(self, request, pk: int):
        graph = get_object_or_404(
            Graph.objects.visible_to(request.user).select_related("allograph__character", "item_image"),
            pk=pk,
            annotation_type=Graph.AnnotationType.IMAGE,
        )
        body = GraphSuggestRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            proposal = glyph_assist.suggest(
                graph.item_image,
                graph.annotation,
                user=request.user,
                allograph=body.validated_data.get("allograph", graph.allograph),
                language=body.validated_data["language"],
                recorded=graph,
            )
        except glyph_assist.AssistError as exc:
            return _assist_failed(exc)
        return Response(SuggestionSerializer(proposal).data, status=status.HTTP_201_CREATED)


class SuggestionRejectView(APIView):
    """W3.5: the person who asked turns the suggestion down. Theirs alone to decide."""

    permission_classes = [CanAnnotate]

    def post(self, request, pk: int):
        proposal = get_object_or_404(GraphProposal, pk=pk, requested_by=request.user)
        body = SuggestionRejectSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            glyph_assist.reject(proposal, user=request.user, reason=body.validated_data["reason"])
        except proposals.ProposalError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response({"status": proposal.status})


class ExplainView(APIView):
    """W3.6: why this annotation is this allograph, as far as the evidence shows."""

    permission_classes = [IsAuthenticated]

    def get_throttles(self):
        # Looking for a stored answer asks no model, so it spends none of the allowance.
        return [AssistThrottle()] if self.request.method == "POST" else []

    def _graph(self, request, pk: int) -> Any:
        return get_object_or_404(
            Graph.objects.visible_to(request.user).select_related("allograph__character", "hand", "item_image"), pk=pk
        )

    def get(self, request, pk: int):
        graph = self._graph(request, pk)
        body = AssistLanguageSerializer(data=request.query_params)
        body.is_valid(raise_exception=True)
        try:
            stored = glyph_assist.stored_explanation(graph, user=request.user, language=body.validated_data["language"])
        except glyph_assist.AssistError as exc:
            return _assist_failed(exc)
        if stored is None:
            raise NotFound("Nobody has asked about this annotation as it stands.")
        return Response(GraphExplanationSerializer(stored).data)

    def post(self, request, pk: int):
        graph = self._graph(request, pk)
        body = AssistLanguageSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            explanation = glyph_assist.explain(graph, user=request.user, language=body.validated_data["language"])
        except glyph_assist.AssistError as exc:
            return _assist_failed(exc)
        return Response(GraphExplanationSerializer(explanation).data)
