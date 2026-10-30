import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.odds.unabated.client import UnabatedClient
from app.schemas.prop_finder import ManualPropIn, PropFinderDetailOut, PropFinderListOut, PropImportStatusOut
from app.schemas.prop_analyzer import PropAnalyzerOut
from app.services.prop_analyzer_service import get_prop_analyzer
from app.services.prop_finder_service import get_prop_detail, import_status, list_props
from app.services.prop_refresh_worker import start_background_import
from app.services.prop_manual_service import create_manual_prop

router = APIRouter(prefix="/prop-finder", tags=["prop-finder"])


@router.get("/status", response_model=PropImportStatusOut)
def prop_finder_status(session: Session = Depends(get_db)):
    client = UnabatedClient.instance()
    return PropImportStatusOut(**import_status(session, configured=client.configured))


@router.post("/import", response_model=PropImportStatusOut, status_code=202)
def refresh_odds(session: Session = Depends(get_db)):
    start_background_import()  # no-op when a refresh is already running
    client = UnabatedClient.instance()
    return PropImportStatusOut(**import_status(session, configured=client.configured))


@router.get("", response_model=PropFinderListOut)
def prop_finder_list(
    session: Session = Depends(get_db),
    sportsbook: str | None = None,
    game_id: int | None = None,
    player_id: int | None = None,
    team_id: int | None = None,
    category: str | None = None,
    pick_side: str | None = None,
    game_date: date | None = None,
    min_hit_pct: float | None = None,
    min_games: int = 10,
    min_sample: int | None = None,
    sort: str = "hcs",
    limit: int = 10,
    offset: int = 0,
):
    if min_games not in (1, 5, 10, 20):
        min_games = 10
    return list_props(
        session,
        sportsbook=sportsbook,
        game_id=game_id,
        player_id=player_id,
        team_id=team_id,
        category=category,
        pick_side=pick_side,
        game_date=str(game_date) if game_date else None,
        min_hit_pct=min_hit_pct,
        min_games=min_games,
        min_sample=min_sample,
        sort=sort,
        limit=limit,
        offset=offset,
    )


@router.get("/{prop_id}/analyzer", response_model=PropAnalyzerOut)
def prop_finder_analyzer(prop_id: int, session: Session = Depends(get_db)):
    return get_prop_analyzer(session, prop_id)


@router.get("/{prop_id}", response_model=PropFinderDetailOut)
def prop_finder_detail(prop_id: int, session: Session = Depends(get_db)):
    return get_prop_detail(session, prop_id)


@router.post("/manual", response_model=PropFinderDetailOut)
def prop_finder_manual(body: ManualPropIn, session: Session = Depends(get_db)):
    offer = create_manual_prop(session, body)
    session.commit()
    return get_prop_detail(session, offer.id)


@router.post("/import-csv")
async def prop_finder_csv(file: UploadFile = File(...), session: Session = Depends(get_db)):
    raw = await file.read()
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    created = 0
    for row in reader:
        try:
            payload = ManualPropIn(
                player_id=int(row["player_id"]),
                game_id=int(row["game_id"]),
                category_key=row["category_key"],
                line=float(row["line"]),
                pick_side=row["pick_side"],
                american_odds=int(row["american_odds"]) if row.get("american_odds") else None,
                sportsbook_label=row.get("sportsbook_label") or "CSV import",
            )
            create_manual_prop(session, payload)
            created += 1
        except (KeyError, ValueError):
            continue
    session.commit()
    return {"imported": created}
