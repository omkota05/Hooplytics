"""Regression tests for prop offer identity, odds validation, and maintenance."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Game, Player
from app.models.sportsbook import PropOffer
from app.services.prop_import_service import _natural_key, _normalize_american_odds
from app.services.prop_offer_maintenance import consolidate_duplicate_offers, deactivate_past_game_offers


def test_natural_key_ignores_market_line_id():
    k1 = _natural_key(
        sportsbook_label="Underdog Fantasy",
        event_id=1,
        person_id=2,
        bet_type_id=3,
        side_index=0,
        market_line_id=100,
        line=4.5,
        pick_side="over",
        alternate_key=None,
    )
    k2 = _natural_key(
        sportsbook_label="Underdog Fantasy",
        event_id=1,
        person_id=2,
        bet_type_id=3,
        side_index=1,
        market_line_id=200,
        line=4.5,
        pick_side="over",
        alternate_key=None,
    )
    assert k1 == k2


def test_normalize_american_rejects_extreme():
    assert _normalize_american_odds(-10532) is None
    assert _normalize_american_odds(-124) == -124


def test_deactivate_past_game_offers(session, session_factory):
    from dataclasses import replace

    from app.ingestion.providers.espn import normalize as n
    from app.sync import writer
    from tests.fixtures import espn_payloads as fx
    from tests.test_api import STAR

    with session_factory() as s:
        writer.upsert_teams(s, n.normalize_teams_payload(fx.TEAMS_PAYLOAD))
        base = n.normalize_boxscore_payload(fx.summary_payload(event_id=1, date="2099-01-02T00:30Z"))
        game = replace(base.game, id=5000, start_time=datetime.now(UTC) - timedelta(days=1))
        stats = [replace(s, game_id=game.id) for s in base.stats]
        writer.write_boxscore(s, replace(base, game=game, stats=stats), {fx.HOME_ID, fx.AWAY_ID})
        s.add(
            PropOffer(
                source_kind="manual",
                sportsbook_label="Test",
                player_id=STAR,
                game_id=5000,
                category_key="pts",
                line=10.5,
                pick_side="over",
                match_status="matched",
                is_active=True,
                game_start_time=game.start_time,
            )
        )
        s.commit()

    n_deact = deactivate_past_game_offers(session)
    assert n_deact >= 1
    offer = session.scalar(select(PropOffer).where(PropOffer.game_id == 5000))
    assert offer is not None
    assert offer.is_active is False


def test_consolidate_duplicate_offers(session):
    player = session.scalar(select(Player.id).limit(1))
    game = session.scalar(
        select(Game.id).where(Game.start_time > datetime.now(UTC)).limit(1)
    )
    if not player or not game:
        pytest.skip("needs player and upcoming game")
    for i in range(3):
        session.add(
            PropOffer(
                source_kind="manual",
                sportsbook_label="SameBook",
                player_id=player,
                game_id=game,
                category_key="pts",
                line=20.5,
                pick_side="over",
                match_status="matched",
                is_active=True,
                l20_games=10,
                hcs_score=80 - i,
                updated_at=datetime.now(UTC),
            )
        )
    session.commit()
    n = consolidate_duplicate_offers(session)
    assert n == 2
    active = session.scalars(
        select(PropOffer).where(
            PropOffer.sportsbook_label == "SameBook",
            PropOffer.line == 20.5,
            PropOffer.is_active.is_(True),
        )
    ).all()
    assert len(active) == 1
