import hashlib
import re
import uuid

from django.conf import settings
from django.http import Http404, StreamingHttpResponse
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from media_assets.models import MediaAsset
from media_assets.serializers import (
    MediaAssetSerializer,
    ProxyUploadSerializer,
    UploadRequestSerializer,
)
from media_assets.storage import get_storage
from media_assets.tasks import validate_media_asset
from vendors.models import VendorMember
from vendors.policies import VendorContext


def _user(request: Request) -> User:
    return request.user  # type: ignore[return-value]


def _asset_for_backoffice(request: Request, asset_id: uuid.UUID) -> MediaAsset:
    asset = MediaAsset.objects.filter(pk=asset_id).first()
    if asset is None:
        raise Http404
    context = VendorContext.resolve(user=_user(request), vendor_id=asset.vendor_id)
    return context.get_object_or_404(MediaAsset.objects, pk=asset.id)


class SessionAPIView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)


class UploadCreateView(SessionAPIView):
    def post(self, request: Request) -> Response:
        serializer = UploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        context = VendorContext.resolve(
            user=_user(request),
            vendor_id=data["vendor_id"],
            roles=(VendorMember.Role.OWNER, VendorMember.Role.EDITOR),
        )
        asset_id = uuid.uuid4()
        key = f"vendors/{context.vendor.id}/assets/{asset_id}/source"
        asset = MediaAsset.objects.create(
            id=asset_id,
            vendor=context.vendor,
            kind=data["kind"],
            bucket=settings.MEDIA_S3_BUCKET,
            object_key=key,
            original_name=data["original_name"],
            content_type=str(data["content_type"]).lower(),
            size_bytes=data["size_bytes"],
            sha256=data["sha256"],
            created_by=_user(request),
        )
        upload = get_storage().create_upload_post(
            key=asset.object_key,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
            sha256=asset.sha256,
        )
        return Response(
            {"asset": MediaAssetSerializer(asset).data, "upload": upload},
            status=status.HTTP_201_CREATED,
        )


class MediaTransferConfigView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        return Response({"mode": settings.MEDIA_TRANSFER_MODE})


class ProxyUploadView(SessionAPIView):
    def post(self, request: Request) -> Response:
        if settings.MEDIA_TRANSFER_MODE != "proxy":
            raise Http404
        serializer = ProxyUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        context = VendorContext.resolve(
            user=_user(request),
            vendor_id=data["vendor_id"],
            roles=(VendorMember.Role.OWNER, VendorMember.Role.EDITOR),
        )
        uploaded = data["file"]
        asset_id = uuid.uuid4()
        object_key = f"vendors/{context.vendor.id}/assets/{asset_id}/{uuid.uuid4().hex}"
        digest = hashlib.sha256()
        for chunk in uploaded.chunks():
            digest.update(chunk)
        uploaded.file.seek(0)
        asset = MediaAsset.objects.create(
            id=asset_id,
            vendor=context.vendor,
            kind=data["kind"],
            bucket=settings.MEDIA_S3_BUCKET,
            object_key=object_key,
            original_name=uploaded.name,
            content_type=str(uploaded.content_type).lower(),
            size_bytes=uploaded.size,
            sha256=digest.hexdigest(),
            created_by=_user(request),
        )
        try:
            get_storage().upload_fileobj(
                key=object_key, fileobj=uploaded.file, content_type=asset.content_type
            )
        except Exception:
            asset.delete()
            raise
        asset.status = MediaAsset.Status.UPLOADED
        asset.save(update_fields=("status", "updated_at"))
        validate_media_asset.delay(str(asset.id))
        return Response(MediaAssetSerializer(asset).data, status=status.HTTP_201_CREATED)


class UploadCompleteView(SessionAPIView):
    def post(self, request: Request, asset_id: uuid.UUID) -> Response:
        asset = _asset_for_backoffice(request, asset_id)
        if asset.status == MediaAsset.Status.PENDING:
            asset.status = MediaAsset.Status.UPLOADED
            asset.save(update_fields=("status", "updated_at"))
            validate_media_asset.delay(str(asset.id))
        return Response(MediaAssetSerializer(asset).data, status=status.HTTP_202_ACCEPTED)


class MediaStatusView(SessionAPIView):
    def get(self, request: Request, asset_id: uuid.UUID) -> Response:
        return Response(MediaAssetSerializer(_asset_for_backoffice(request, asset_id)).data)


class StreamURLView(SessionAPIView):
    def get(self, request: Request, asset_id: uuid.UUID) -> Response:
        asset = _asset_for_backoffice(request, asset_id)
        if asset.status != MediaAsset.Status.READY:
            return Response({"code": "MEDIA_NOT_READY"}, status=status.HTTP_409_CONFLICT)
        url = (
            f"/api/v1/vendor/media/{asset.id}/content"
            if settings.MEDIA_TRANSFER_MODE == "proxy"
            else get_storage().create_download_url(key=asset.object_key)
        )
        response = Response({"url": url})
        response["Cache-Control"] = "no-store"
        return response


def _parse_range(value: str | None, size: int) -> tuple[int, int] | None:
    if not value or not value.startswith("bytes=") or "," in value:
        return None
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if match is None:
        return None
    start_text, end_text = match.groups()
    if not start_text and not end_text:
        return None
    if not start_text:
        length = int(end_text)
        return (max(size - length, 0), size - 1) if length > 0 else None
    start = int(start_text)
    end = int(end_text) if end_text else size - 1
    if start >= size or end < start:
        return None
    return start, min(end, size - 1)


def serve_asset_content(request: Request, asset: MediaAsset) -> StreamingHttpResponse:
    head = get_storage().head(key=asset.object_key)
    size = int(head.get("ContentLength", asset.size_bytes))
    requested = request.headers.get("Range")
    selected = _parse_range(requested, size)
    if requested and selected is None:
        response = StreamingHttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        return response
    start, end = selected or (0, size - 1)
    response = StreamingHttpResponse(
        get_storage().read_range(key=asset.object_key, start=start, end=end),
        status=206 if selected else 200,
        content_type=asset.content_type,
    )
    response["Content-Length"] = str(end - start + 1)
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, no-store"
    if selected:
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
    return response


class VendorMediaContentView(SessionAPIView):
    def get(self, request: Request, asset_id: uuid.UUID) -> StreamingHttpResponse:
        asset = MediaAsset.objects.filter(pk=asset_id).first()
        if asset is None:
            raise Http404
        VendorContext.resolve(
            user=_user(request),
            vendor_id=asset.vendor_id,
            roles=(VendorMember.Role.OWNER, VendorMember.Role.EDITOR),
        )
        if asset.status != MediaAsset.Status.READY:
            raise Http404
        return serve_asset_content(request, asset)
