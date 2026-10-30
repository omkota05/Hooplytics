from app.models.sportsbook import UnabatedIdentityMapping
from app.services.prop_matching import mapping_lookup, save_mapping
from sqlalchemy import select


def test_save_mapping_upserts_duplicate_event(session):
    save_mapping(
        session,
        entity_type="event",
        unabated_id=134553,
        hooplytics_id=401909884,
        method="teams_time",
    )
    save_mapping(
        session,
        entity_type="event",
        unabated_id=134553,
        hooplytics_id=401909884,
        method="teams_time",
    )
    session.flush()
    rows = list(
        session.scalars(
            select(UnabatedIdentityMapping).where(
                UnabatedIdentityMapping.entity_type == "event",
                UnabatedIdentityMapping.unabated_id == 134553,
            )
        )
    )
    assert len(rows) == 1
    assert rows[0].hooplytics_id == 401909884
    assert mapping_lookup(session, "event", 134553) == 401909884


def test_save_mapping_updates_hooplytics_id(session):
    save_mapping(
        session,
        entity_type="event",
        unabated_id=1,
        hooplytics_id=100,
        method="teams_time",
    )
    save_mapping(
        session,
        entity_type="event",
        unabated_id=1,
        hooplytics_id=200,
        method="teams_time",
    )
    session.flush()
    assert mapping_lookup(session, "event", 1) == 200
