"""M3-T3 shared batch adapter: exact column mapping and rejected unknown sides.

All rows are synthetic; no vendor raw book fixtures enter the repository.
"""

import perpcarry_cpp
import pyarrow as pa
import pytest

from perpcarry.ingestion.book_partitions import EVENT_COLUMNS
from perpcarry.replay import ReplayInputError, updates_from_batch


def make_batch(rows: list[dict]) -> pa.RecordBatch:
    """Build a batch with the shared feed's column list, never a restated one (C15)."""
    columns = {name: [row[name] for row in rows] for name in EVENT_COLUMNS}
    return pa.RecordBatch.from_pydict(columns)


def test_every_column_lands_in_the_field_it_belongs_to():
    batch = make_batch(
        [
            {
                "timestamp": 1000,
                "local_timestamp": 1002,
                "is_snapshot": True,
                "side": "bid",
                "price": 100.5,
                "quantity": 4.25,
            },
            {
                "timestamp": 1001,
                "local_timestamp": 1003,
                "is_snapshot": False,
                "side": "ask",
                "price": 101.5,
                "quantity": 7.75,
            },
        ]
    )

    updates = updates_from_batch(batch)

    assert len(updates) == 2
    first, second = updates
    # Asserted field by field, with every value distinct, so a transposition of any two
    # columns fails rather than cancelling out.
    assert first.timestamp == 1000
    assert first.local_timestamp == 1002
    assert first.is_snapshot is True
    assert first.side == perpcarry_cpp.Side.Bid
    assert first.price == 100.5
    assert first.quantity == 4.25

    assert second.timestamp == 1001
    assert second.local_timestamp == 1003
    assert second.is_snapshot is False
    assert second.side == perpcarry_cpp.Side.Ask
    assert second.price == 101.5
    assert second.quantity == 7.75


def test_an_unknown_side_is_rejected_rather_than_defaulted():
    """A silent default would put every unrecognised row on the bid side."""
    batch = make_batch(
        [
            {
                "timestamp": 1000,
                "local_timestamp": 1000,
                "is_snapshot": True,
                "side": "buy",  # the archive's word, not this feed's
                "price": 100.0,
                "quantity": 1.0,
            }
        ]
    )

    with pytest.raises(ReplayInputError, match="unknown side"):
        updates_from_batch(batch)
