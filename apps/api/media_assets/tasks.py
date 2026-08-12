import uuid

from celery import shared_task
from django.db import transaction

from media_assets.models import MediaAsset
from media_assets.storage import get_storage
from media_assets.validation import MediaValidationError, validate_asset


@shared_task(ignore_result=True)  # type: ignore[misc]
def validate_media_asset(asset_id: str) -> None:
    with transaction.atomic():
        asset = MediaAsset.objects.select_for_update().filter(pk=uuid.UUID(asset_id)).first()
        if asset is None or asset.status != MediaAsset.Status.UPLOADED:
            return
        asset.status = MediaAsset.Status.VALIDATING
        asset.rejection_reason = None
        asset.save(update_fields=("status", "rejection_reason", "updated_at"))

    try:
        details = validate_asset(asset, get_storage())
    except MediaValidationError as error:
        _reject(asset, str(error))
        return
    except Exception:
        _reject(asset, "Media validation failed.")
        return

    MediaAsset.objects.filter(pk=asset.id).update(
        status=MediaAsset.Status.READY,
        duration_seconds=details.duration_seconds,
        width=details.width,
        height=details.height,
        rejection_reason=None,
    )


def _reject(asset: MediaAsset, reason: str) -> None:
    try:
        get_storage().delete(key=asset.object_key)
    except Exception:
        # A lifecycle policy handles a failed cleanup; never hide the rejection state.
        pass
    finally:
        MediaAsset.objects.filter(pk=asset.id).update(
            status=MediaAsset.Status.REJECTED, rejection_reason=reason
        )
