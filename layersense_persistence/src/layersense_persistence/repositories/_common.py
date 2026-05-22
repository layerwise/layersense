from __future__ import annotations

import re
import unicodedata
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def new_id() -> str:
    return str(uuid4())


def slugify(value: str, *, max_length: int = 80) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized.lower()).strip("-")
    return (slug or "project")[:max_length].strip("-") or "project"


def next_order_index(
    session: Session, model: type, foreign_key_name: str, foreign_key: str
) -> int:
    order_index = session.scalar(
        select(func.max(model.order_index)).where(getattr(model, foreign_key_name) == foreign_key)
    )
    if order_index is None:
        return 0
    return int(order_index) + 1
