"""Local pronoun review API, protected by the existing /api middleware."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, StrictInt

from novel2epub.pronoun_review import (
    PronounPreviewStale, apply_pronoun_preview, preview_pronouns,
)
from novel2epub.storage import Storage
from novel2epub.pronouns import DialogueMarks
from .. import deps

router = APIRouter()


class PronounScope(BaseModel):
    branch: Literal["ai", "local_mt"]
    indexes: list[StrictInt] = Field(min_length=1, max_length=50)
    dialogue_marks: DialogueMarks = "standard"


class PronounApproval(PronounScope):
    token: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmed: Literal[True]


def _storage(slug: str) -> Storage:
    try:
        cfg = deps.resolved_cfg(slug)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy truyện.") from exc
    storage = Storage(cfg.output.data_dir, cfg.novel.slug)
    if storage.load_manifest() is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy truyện hoặc mục lục.")
    return storage


@router.post("/api/ui/ebooks/{slug}/pronouns/preview")
def preview(slug: str, body: PronounScope):
    try:
        return preview_pronouns(_storage(slug), branch=body.branch, indexes=body.indexes, dialogue_marks=body.dialogue_marks)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/ui/ebooks/{slug}/pronouns/apply")
def apply(slug: str, body: PronounApproval):
    try:
        return apply_pronoun_preview(_storage(slug), branch=body.branch, indexes=body.indexes, token=body.token, dialogue_marks=body.dialogue_marks)
    except PronounPreviewStale as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
