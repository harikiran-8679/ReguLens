"""Image endpoints: upload/capture, server-side quality + duplicate checks,
and file serving for the evidence viewer / report builder."""
from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .. import models, serializers
from ..config import settings
from ..database import get_db
from ..deps import get_current_user, get_inspection_or_404, require_owner_or_admin
from ..security import decode_token
from ..services.audit import record
from ..services import quality as quality_service
from ..utils import IMG_SIDES

_bearer = HTTPBearer(auto_error=False)


def _resolve_image_user(credentials: HTTPAuthorizationCredentials | None, token: str | None, db: Session) -> models.User:
    """Resolve the user for image serving from either the Authorization header
    (fetch / report calls) or the `token` query parameter (plain <img> tags,
    which cannot send headers)."""
    raw = credentials.credentials if credentials else (token or None)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated.")
    payload = decode_token(raw)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
    user = db.query(models.User).filter(models.User.username == payload.get("sub")).first()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found.")
    if user.status != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is not active.")
    return user

router = APIRouter(tags=["images"])


def _img_check_side(side: str) -> str:
    side = (side or "front").strip().lower()
    if side not in IMG_SIDES:
        side = "additional"
    return side


@router.post("/inspections/{inspection_id}/images/upload")
def upload_image(
    inspection_id: int,
    file: UploadFile = File(...),
    side: str = Form(default="front"),
    description: str = Form(default=""),
    source: str = Form(default="upload"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    if inspection.status == "finalized":
        raise HTTPException(400, "Finalised inspections are read-only.")
    data = file.file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    if len(data) > settings.UPLOAD_MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {settings.UPLOAD_MAX_MB} MB limit.")

    digest = hashlib.sha256(data).hexdigest()
    existing = (
        db.query(models.InspectionImage)
        .filter(models.InspectionImage.inspection_id == inspection.id,
                models.InspectionImage.file_hash == digest)
        .first()
    )
    duplicate = existing is not None

    # Validate + quick-assess pixels before storing
    report = quality_service.quick_assess_bytes(data)
    if report["overall"] == "poor" and report["checks"][0]["metric"] == "image_load":
        raise HTTPException(400, "Uploaded file is not a readable image (JPG/PNG).")

    folder = settings.storage_dir / "uploads" / inspection.inspection_id
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "image.jpg").suffix or ".jpg"
    rel_name = f"{uuid.uuid4().hex}{suffix.lower()}"
    rel = f"uploads/{inspection.inspection_id}/{rel_name}"
    path = settings.storage_dir / rel
    path.write_bytes(data)

    from PIL import Image as PILImage

    try:
        with PILImage.open(path) as im:
            width, height = im.size
            fmt = (im.format or "JPEG").upper()
    except Exception as exc:  # pragma: no cover
        path.unlink(missing_ok=True)
        raise HTTPException(400, "Image could not be decoded.") from exc

    side_val = _img_check_side(side)
    count = len(inspection.images) + 1
    img = models.InspectionImage(
        inspection_id=inspection.id,
        image_id=f"IMG-{inspection.inspection_id.split('-')[-1]}-{count:02d}",
        side=side_val,
        source="camera" if source == "camera" else "upload",
        storage_path=rel,
        file_hash=digest,
        width=width, height=height, format=fmt,
        quality=report,
        ocr_suitability=report["ocr_suitability"],
        processing_status="pending",
        is_duplicate=duplicate,
        duplicate_of=existing.image_id if duplicate else None,
        captured_at=dt.datetime.now(dt.timezone.utc),
        meta={"description": description},
    )
    db.add(img)
    db.commit()
    record(db, actor_user=user, inspection_id=inspection.id, action="image_uploaded",
           entity_type="image", entity_id=img.image_id,
           details={"side": side_val, "duplicate": duplicate, "ocr_suitability": report["ocr_suitability"]})
    return serializers.image_dict(img)


@router.get("/inspections/{inspection_id}/images")
def list_images(inspection_id: int, db: Session = Depends(get_db),
                user: models.User = Depends(get_current_user)):
    inspection = get_inspection_or_404(inspection_id, db)
    require_owner_or_admin(inspection, user)
    images = sorted(inspection.images, key=lambda i: i.id)
    coverage = {s: {"captured": False, "image_id": None} for s in IMG_SIDES}
    for im in images:
        if im.side in coverage:
            coverage[im.side] = {"captured": True, "image_id": im.image_id}
    return {
        "images": [serializers.image_dict(i) for i in images],
        "coverage": coverage,
        "max_images": 8,
    }


@router.get("/images/{image_id}/file")
def image_file(image_id: int,
               token: str | None = Query(default=None, description="JWT for <img> tags that cannot send the Authorization header"),
               credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
               db: Session = Depends(get_db)):
    """Serve an image file. Auth is accepted from the Bearer header (fetch-based
    calls) or the `token` query param (browser <img> tags). Ownership scoping
    is enforced either way."""
    user = _resolve_image_user(credentials, token, db)
    img = db.query(models.InspectionImage).filter(models.InspectionImage.id == image_id).first()
    if img is None:
        raise HTTPException(404, "Image not found.")
    inspection = get_inspection_or_404(img.inspection_id, db)
    require_owner_or_admin(inspection, user)
    path = settings.storage_dir / img.storage_path
    if not path.exists():
        raise HTTPException(404, "Image file missing on disk.")
    return FileResponse(str(path), media_type="image/jpeg", filename=img.image_id + ".jpg")
