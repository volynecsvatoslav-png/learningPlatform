import uuid

from django.conf import settings
from django.http import Http404
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from media_assets.models import MediaAsset
from media_assets.serializers import MediaAssetSerializer, UploadRequestSerializer
from media_assets.storage import get_storage
from media_assets.tasks import validate_media_asset
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
        context = VendorContext.resolve(user=_user(request), vendor_id=data["vendor_id"])
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
        response = Response({"url": get_storage().create_download_url(key=asset.object_key)})
        response["Cache-Control"] = "no-store"
        return response
