"""Temporary script: data scale counts for RESUME_METRICS.md (read-only)."""
from __future__ import annotations

import json
from sqlalchemy import func, select, text

from app.db import session_scope
from app.models import Game, Player, PlayerGameStat, Team
from app.models.sportsbook import PropImportRun, PropLineHitCache, PropOffer


def main() -> None:
    with session_scope() as s:
        counts = {
            "teams": s.scalar(select(func.count()).select_from(Team)) or 0,
            "teams_active": s.scalar(select(func.count()).select_from(Team).where(Team.is_active.is_(True))) or 0,
            "players_total": s.scalar(select(func.count()).select_from(Player)) or 0,
            "players_with_box_score": s.scalar(
                select(func.count(func.distinct(PlayerGameStat.player_id))).select_from(PlayerGameStat)
            )
            or 0,
            "players_active_flag": s.scalar(select(func.count()).select_from(Player).where(Player.is_active.is_(True)))
            or 0,
            "player_game_stats": s.scalar(select(func.count()).select_from(PlayerGameStat)) or 0,
            "player_game_stats_played": s.scalar(
                select(func.count()).select_from(PlayerGameStat).where(PlayerGameStat.did_not_play.is_(False))
            )
            or 0,
            "games_total": s.scalar(select(func.count()).select_from(Game)) or 0,
            "games_final": s.scalar(select(func.count()).select_from(Game).where(Game.status == "final")) or 0,
            "distinct_seasons_in_games": s.scalar(select(func.count(func.distinct(Game.season)))) or 0,
            "prop_offers_total": s.scalar(select(func.count()).select_from(PropOffer)) or 0,
            "prop_offers_active": s.scalar(
                select(func.count()).select_from(PropOffer).where(PropOffer.is_active.is_(True))
            )
            or 0,
            "prop_offers_matched": s.scalar(
                select(func.count()).select_from(PropOffer).where(
                    PropOffer.is_active.is_(True), PropOffer.player_id.is_not(None)
                )
            )
            or 0,
            "prop_line_hit_cache_rows": s.scalar(select(func.count()).select_from(PropLineHitCache)) or 0,
            "prop_import_runs": s.scalar(select(func.count()).select_from(PropImportRun)) or 0,
        }
        seasons = s.execute(
            select(Game.season, func.count())
            .where(Game.status == "final", Game.boxscore_synced_at.is_not(None))
            .group_by(Game.season)
            .order_by(Game.season)
        ).all()
        counts["final_games_with_boxscore_by_season"] = {int(season): int(n) for season, n in seasons}

        import_agg = s.execute(
            select(
                func.coalesce(func.sum(PropImportRun.offers_seen), 0),
                func.coalesce(func.sum(PropImportRun.offers_upserted), 0),
                func.coalesce(func.sum(PropImportRun.offers_matched), 0),
            ).select_from(PropImportRun)
        ).one()
        counts["prop_import_offers_seen_lifetime"] = int(import_agg[0])
        counts["prop_import_offers_upserted_lifetime"] = int(import_agg[1])
        counts["prop_import_offers_matched_lifetime"] = int(import_agg[2])

        backfill = s.execute(
            text(
                """
                SELECT kind, COUNT(*), SUM(boxscores_synced), SUM(requests_made)
                FROM sync_runs WHERE status IN ('success','partial')
                GROUP BY kind ORDER BY kind
                """
            )
        ).all()
        counts["sync_runs_by_kind"] = [
            {"kind": row[0], "runs": row[1], "boxscores_synced": int(row[2] or 0), "requests_made": int(row[3] or 0)}
            for row in backfill
        ]

        print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()