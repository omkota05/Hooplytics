import json
from pathlib import Path

import pytest

from app.odds.unabated.response import (
    UnabatedResponseShapeError,
    data_records,
    person_display_name,
    record_id,
)

PEOPLE_FIXTURE = Path(__file__).parent / "fixtures" / "unabated_props_people_sample.json"


def test_data_records_dict_of_players():
    body = json.loads(PEOPLE_FIXTURE.read_text())
    rows = data_records(body["data"], context="people")
    assert len(rows) == 2
    assert person_display_name(rows[0]) == "LeBron James"
    assert record_id(rows[1], "id") == 417208


def test_data_records_rejects_string_values():
    with pytest.raises(UnabatedResponseShapeError):
        data_records({"1": "oops"}, context="test")


def test_data_records_list_still_supported():
    rows = data_records([{"id": 1, "name": "A"}], context="test")
    assert rows[0]["name"] == "A"
