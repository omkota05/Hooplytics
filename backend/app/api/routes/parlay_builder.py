from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.parlay_builder import ParlaySearchIn, ParlaySearchOut
from app.services.parlay_builder_service import search_parlays

router = APIRouter(prefix="/parlay-builder", tags=["parlay-builder"])


@router.post("/search", response_model=ParlaySearchOut)
def parlay_search(body: ParlaySearchIn, session: Session = Depends(get_db)):
    return search_parlays(session, body)
