from app.models import Game, Player, Team
from app.schemas.common import (
    SEASON_TYPE_LABELS,
    GameOut,
    PlayerSummaryOut,
    TeamOut,
    season_label,
)


def team_out(team: Team) -> TeamOut:
    return TeamOut.model_validate(team)


def player_summary(player: Player) -> PlayerSummaryOut:
    return PlayerSummaryOut(
        id=player.id,
        full_name=player.full_name,
        position=player.position,
        jersey=player.jersey,
        headshot_url=player.headshot_url,
        is_active=player.is_active,
        team=team_out(player.current_team) if player.current_team else None,
    )


def game_out(game: Game) -> GameOut:
    return GameOut(
        id=game.id,
        season=game.season,
        season_label=season_label(game.season),
        season_type=game.season_type,
        season_type_label=SEASON_TYPE_LABELS.get(game.season_type, "Other"),
        start_time=game.start_time,
        game_date=game.game_date,
        status=game.status,
        status_detail=game.status_detail,
        home_team=team_out(game.home_team),
        away_team=team_out(game.away_team),
        home_score=game.home_score,
        away_score=game.away_score,
        venue_name=game.venue_name,
        venue_city=game.venue_city,
        venue_state=game.venue_state,
        neutral_site=game.neutral_site,
    )


def round_or_none(value, digits: int = 1) -> float | None:
    return round(float(value), digits) if value is not None else None
