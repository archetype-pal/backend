"""The tutor's endpoints. Transport only: every decision is the services'.

Starting a lesson and asking a question both answer 202 at once with the
session, which the page then polls: the tutor works in a worker for minutes.
Anyone with a session's link may read it, as its id is unguessable; only the
requester who started it may ask it more.
"""

import hashlib
import uuid

from django.conf import settings
from django.http import FileResponse, Http404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import BaseThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.common.throttling import ByNetwork, network_of

from .models import TutorSession, picture_storage
from .serializers import PageSerializer, QuestionSerializer, StartSessionSerializer, TutorSessionSerializer
from .services import pictures, sessions

# Each refusal as the status a client can act on.
STATUS_FOR = {
    sessions.Unavailable: status.HTTP_503_SERVICE_UNAVAILABLE,
    sessions.NotAllowed: status.HTTP_403_FORBIDDEN,
    sessions.QuotaReached: status.HTTP_429_TOO_MANY_REQUESTS,
    sessions.Busy: status.HTTP_409_CONFLICT,
    sessions.Invalid: status.HTTP_400_BAD_REQUEST,
}


class LearnThrottle(ByNetwork, UserRateThrottle):
    """One bucket for starting lessons and asking questions, keyed by account or address.

    As the public agent's: the rate is read from settings directly, since DRF's
    scope table is empty under DEBUG, and it is off under DEBUG. The daily
    allowance and the spend cap still apply there.
    """

    scope = "learn"

    def get_rate(self):
        if settings.DEBUG:
            return None
        return getattr(settings, "DRF_THROTTLE_LEARN_RATE", "") or None


def requester_key(request) -> str:
    """A salted digest of the requester's address, as the public agent keeps.

    Enough to tell two anonymous requesters apart, and to know the one who
    started a lesson when they come back to ask it more, without keeping who
    either is. The address is the throttle's, read through `NUM_PROXIES`.
    """
    address = network_of(BaseThrottle().get_ident(request) or "")
    return hashlib.sha256(f"{settings.SECRET_KEY}:learn:{address}".encode()).hexdigest()[:32]


def _context(request) -> dict:
    return {"request": request, "requester": (request.user, requester_key(request))}


def _declined(exc: sessions.LearnError) -> Response:
    body = {"detail": str(exc), "code": exc.code}
    return Response(body, status=STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST))


def _session(pk: str) -> TutorSession:
    # Routed as a string, as the other apps route their ids: an id that is not
    # a UUID names no session.
    try:
        key = uuid.UUID(pk)
    except ValueError:
        raise Http404 from None
    related = TutorSession.objects.select_related("item_image__item_part__historical_item__date")
    try:
        session: TutorSession = related.get(pk=key)
    except TutorSession.DoesNotExist:
        raise Http404 from None
    return session


class LearnStatusView(APIView):
    """Whether the tutor is on, and what this requester may do with it."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(sessions.status(request.user))


class SuggestedPagesView(APIView):
    """Corpus pages to learn from, the most annotated first."""

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(PageSerializer(sessions.suggested_pages(), many=True).data)


class SessionsView(APIView):
    """POST a corpus page or a picture to start a lesson."""

    permission_classes = [AllowAny]
    throttle_classes = [LearnThrottle]

    def post(self, request):
        serializer = StartSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        upload = None
        if "picture" in data:
            # One byte past the limit is enough to know it is over it.
            upload = data["picture"].read(pictures.MAX_UPLOAD_BYTES + 1)
        try:
            session = sessions.start(
                actor=request.user,
                requester_key=requester_key(request),
                page=data.get("item_image"),
                upload=upload,
                language=data["language"],
            )
        except sessions.LearnError as exc:
            return _declined(exc)
        return Response(
            TutorSessionSerializer(session, context=_context(request)).data, status=status.HTTP_202_ACCEPTED
        )


class SessionView(APIView):
    """A lesson, as far as the tutor has got with it."""

    permission_classes = [AllowAny]

    def get(self, request, pk):
        return Response(TutorSessionSerializer(_session(pk), context=_context(request)).data)


class SessionPictureView(APIView):
    """The picture the lesson's boxes are drawn on, exactly as the tutor saw it."""

    permission_classes = [AllowAny]

    def get(self, request, pk):
        session = _session(pk)
        if not session.picture:
            raise Http404
        response = FileResponse(picture_storage.open(session.picture.name, "rb"), content_type="image/jpeg")
        # Private: a student's own picture is theirs, whoever else has the link.
        response["Cache-Control"] = "private, max-age=86400"
        return response


class QuestionsView(APIView):
    """POST a question about the lesson. Only the requester who started it may."""

    permission_classes = [AllowAny]
    throttle_classes = [LearnThrottle]

    def post(self, request, pk):
        serializer = QuestionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            session = sessions.ask(
                _session(pk),
                serializer.validated_data["question"],
                actor=request.user,
                requester_key=requester_key(request),
            )
        except sessions.LearnError as exc:
            return _declined(exc)
        return Response(
            TutorSessionSerializer(session, context=_context(request)).data, status=status.HTTP_202_ACCEPTED
        )
