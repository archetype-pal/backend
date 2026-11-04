from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.scribes.models import Hand, Scribe

from .serializers import scribe_similar_hands_data, similar_hands_data
from .services import hand_similarity


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
