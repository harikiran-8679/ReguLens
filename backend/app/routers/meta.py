"""Reference / meta endpoints used by the frontend dropdowns and static text."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..deps import get_current_user
from ..utils import IMG_SIDES

router = APIRouter(prefix="/meta", tags=["meta"])


@router.get("/catalog")
def catalog(db: Session = Depends(get_db), _: models.User = Depends(get_current_user)):
    cats = db.query(models.ProductCategory).order_by(models.ProductCategory.id).all()
    return {
        "categories": [{"code": c.code, "label": c.label, "imported_only": c.imported_only} for c in cats],
        "sides": IMG_SIDES,
        "package_types": ["rigid", "flexible", "curved", "carton", "bottle", "can", "jar", "sachet", "other"],
        "premises_types": ["Retail Store", "Supermarket / Hypermarket", "Wholesale", "Warehouse",
                           "Manufacturing Unit", "E-commerce Fulfilment", "Street Vendor", "Other"],
    }
