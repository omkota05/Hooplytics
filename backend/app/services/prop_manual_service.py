from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.analytics.categories import get_category
from app.analytics.lines import validate_line
from app.models import Game, Player
from app.models.sportsbook import PropOffer
from app.schemas.prop_finder import ManualPropIn
from app.services.errors import BadRequestError, NotFoundError
from app.services.prop_hit_cache_service import (
    apply_hit_to_offer_values,
    current_data_sync_reference,
    get_or_compute_hit_cache,
)
from app.services.prop_matching import opponent_for_player


def create_manual_prop(session: Session, body: ManualPropIn) -> PropOffer:
    validate_line(body.line)
    get_category(body.category_key)
    player = session.get(Player, body.player_id)
    game = session.scalar(
        select(Game)
        .options(joinedload(Game.home_team), joinedload(Game.away_team))
        .where(Game.id == body.game_id)
    )
    if player is None:
        raise NotFoundError(f"Player {body.player_id} not found")
    if game is None:
        raise NotFoundError(f"Game {body.game_id} not found")
    if player.current_team_id not in (game.home_team_id, game.away_team_id):
        raise BadRequestError("Player is not in this game")

    opponent_id = opponent_for_player(session, game.id, player.id)
    sync_ref = current_data_sync_reference(session)
    hit_json, hit_cache_id, hit_computed_at = get_or_compute_hit_cache(
        session,
        player_id=player.id,
        game_id=game.id,
        opponent_team_id=opponent_id,
        category_key=body.category_key,
        line=body.line,
        season=game.season,
        before_start=game.start_time,
        data_sync_reference=sync_ref,
    )
    values = apply_hit_to_offer_values(
        {
            "source_kind": "manual",
            "sportsbook_label": body.sportsbook_label,
            "player_id": player.id,
            "game_id": game.id,
            "opponent_team_id": opponent_id,
            "category_key": body.category_key,
            "line": body.line,
            "pick_side": body.pick_side,
            "american_odds": body.american_odds,
            "event_name": f"{game.away_team.abbreviation} @ {game.home_team.abbreviation}",
            "player_name_raw": player.full_name,
            "game_start_time": game.start_time,
            "game_date": game.game_date,
            "is_active": True,
            "match_status": "matched",
            "imported_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        },
        hit_rates=hit_json,
        pick_side=body.pick_side,
        hit_cache_id=hit_cache_id,
        computed_at=hit_computed_at,
    )
    offer = PropOffer(**values)
    session.add(offer)
    session.flush()
    return offer
