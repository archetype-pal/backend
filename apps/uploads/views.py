from typing import Any

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import BaseParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.permissions import IsSuperuser
from apps.uploads import services
from apps.uploads.models import ImageUploadSession
from apps.uploads.serializers import ImageUploadSessionCreateSerializer, ImageUploadSessionSerializer


class OctetStreamParser(BaseParser):
    """Pass the raw request body stream through untouched (chunk uploads)."""

    media_type = "application/octet-stream"

    def parse(self, stream: Any, media_type: str | None = None, parser_context: dict | None = None) -> Any:
        return stream


def _error_response(exc: services.UploadError) -> Response:
    body: dict[str, str] = {"detail": str(exc)}
    if exc.code:
        body["code"] = exc.code
    return Response(body, status=exc.status_code)


class ImageUploadSessionViewSet(viewsets.GenericViewSet):
    """Chunked-upload sessions: create → PUT chunks → finalize → poll."""

    permission_classes = [IsSuperuser]
    queryset = ImageUploadSession.objects.select_related("item_part", "owner")
    serializer_class = ImageUploadSessionSerializer

    def create(self, request: Request) -> Response:
        payload = ImageUploadSessionCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        try:
            session, created = services.create_session(
                owner=request.user,
                item_part=data["item_part"],
                filename=data["filename"],
                size=data["size"],
                locus=data["locus"],
                tags=data["tags"],
            )
        except services.UploadError as exc:
            return _error_response(exc)
        # 200 = an interrupted session for this same file was handed back;
        # the client resumes from `missing_chunks` instead of re-uploading.
        return Response(
            ImageUploadSessionSerializer(session).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def retrieve(self, request: Request, pk: str | None = None) -> Response:
        return Response(ImageUploadSessionSerializer(self.get_object()).data)

    def destroy(self, request: Request, pk: str | None = None) -> Response:
        session = self.get_object()
        self._check_owner(request, session)
        try:
            services.abort_session(session)
        except services.UploadError as exc:
            return _error_response(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=True,
        methods=["put"],
        url_path=r"chunks/(?P<chunk_index>[0-9]+)",
        parser_classes=[OctetStreamParser],
    )
    def chunk(self, request: Request, pk: str | None = None, chunk_index: str = "0") -> Response:
        session = self.get_object()
        self._check_owner(request, session)
        try:
            session = services.receive_chunk(session, int(chunk_index), request.data)
        except services.UploadError as exc:
            return _error_response(exc)
        return Response({"received_chunks": session.received_chunks, "missing_chunks": session.missing_chunks()})

    @action(detail=True, methods=["post"])
    def finalize(self, request: Request, pk: str | None = None) -> Response:
        session = self.get_object()
        self._check_owner(request, session)
        try:
            session = services.finalize_session(session)
        except services.UploadError as exc:
            return _error_response(exc)
        return Response(ImageUploadSessionSerializer(session).data, status=status.HTTP_202_ACCEPTED)

    @staticmethod
    def _check_owner(request: Request, session: ImageUploadSession) -> None:
        if session.owner_id != request.user.id:
            raise PermissionDenied("Only the session's owner may modify it.")

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, services.UploadError):
            return _error_response(exc)
        return super().handle_exception(exc)
