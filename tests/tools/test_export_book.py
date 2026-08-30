"""M2-T2 -- the CSV exporter feeding the replay validator.

Spec: docs/specs/M2/M2-T2-book-replay.md, decision D-018.

Every fixture is synthetic: the vendor's terms forbid book rows entering the repository
(Tardis Clause 9.2(2), convention C9).
"""

from __future__ import annotations

import csv
import datetime as dt
import struct

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from perpcarry.ingestion import fetch_book
from perpcarry.ingestion import tardis_archive as tardis
from perpcarry.tools import export_book

DATE = dt.date(2026, 6, 1)
SYMBOL = "TESTUSDT"


def write_partition(dataset: str, rows: dict[str, list], schema: pa.Schema) -> None:
    """Write a synthetic partition where the fetcher would have put a real one.

    The location comes from ``fetch_book.partition_path`` rather than being restated here:
    a fixture that hard-codes the layout can only ever agree with the code by luck, and it
    fails in the direction that looks like success (C15).
    """
    directory = fetch_book.partition_path(dataset, SYMBOL, DATE)
    directory.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {name: pa.array(values, schema.field(name).type) for name, values in rows.items()}
    )
    pq.write_table(table.select(schema.names), directory / "part-0.parquet")


def events_rows() -> dict[str, list]:
    return {
        "exchange": ["binance-futures"] * 5,
        "timestamp": [1000, 1000, 1001, 1002, 1002],
        "local_timestamp": [1002, 1002, 1003, 1004, 1004],
        "latency_us": [2000] * 5,
        "is_snapshot": [True, True, False, False, False],
        "side": ["bid", "ask", "bid", "bid", "ask"],
        "price": [100.0, 101.0, 99.5, 0.30000000000000004, 1e-9],
        "quantity": [5.0, 7.0, 3.0, 0.0, 2.5],
    }


def reference_rows() -> dict[str, list]:
    return {
        "exchange": ["binance-futures"] * 4,
        "timestamp": [1001, 1001, 1002, 1005],
        "local_timestamp": [1003, 1003, 1004, 1007],
        "latency_us": [2000] * 4,
        "side": ["ask", "bid", "bid", "bid"],
        "level": [0, 0, 0, 0],
        "price": [101.0, 100.0, 100.0, 100.0],
        "quantity": [7.0, 5.0, 5.0, 5.0],
    }


@pytest.fixture
def corpus():
    write_partition(tardis.INCREMENTAL_BOOK_L2, events_rows(), fetch_book.SCHEMA)
    write_partition(tardis.BOOK_SNAPSHOT_25, reference_rows(), fetch_book.SNAPSHOT_SCHEMA)


def read_csv(path):
    with path.open(newline="") as handle:
        return list(csv.reader(handle))


def test_export_writes_both_files_with_the_documented_columns(corpus):
    report = export_book.export(SYMBOL, DATE)

    events = read_csv(report.events_path)
    reference = read_csv(report.reference_path)

    assert events[0] == export_book.EVENT_COLUMNS
    assert reference[0] == export_book.REFERENCE_COLUMNS
    assert report.events == 5
    assert len(events) == 6  # header + rows


def test_export_preserves_file_order(corpus):
    # Row order *is* the sequence: this feed carries no sequence number and millisecond
    # timestamps tie freely, so a reader that reordered rows would silently corrupt the
    # replay while every value remained individually correct.
    report = export_book.export(SYMBOL, DATE)
    rows = read_csv(report.events_path)[1:]

    assert [row[0] for row in rows] == ["1000", "1000", "1001", "1002", "1002"]
    assert [row[3] for row in rows] == ["bid", "ask", "bid", "bid", "ask"]


def test_exported_prices_round_trip_bit_for_bit(corpus):
    # The comparison downstream is exact, with no tolerance. A price that loses its last
    # bit in the CSV would surface as a replay mismatch -- pointing the reader at the book
    # instead of at this function.
    report = export_book.export(SYMBOL, DATE)
    written = [float(row[4]) for row in read_csv(report.events_path)[1:]]

    for original, roundtripped in zip(events_rows()["price"], written, strict=True):
        assert struct.pack("d", original) == struct.pack("d", roundtripped)


def test_reference_is_truncated_to_the_exported_event_window(corpus):
    # The image at 1005 sits past the last event, so nothing could be compared against it.
    report = export_book.export(SYMBOL, DATE)
    timestamps = [row[0] for row in read_csv(report.reference_path)[1:]]

    assert timestamps == ["1001", "1001", "1002"]
    assert report.images == 2
    assert report.last_timestamp == 1002


def test_max_events_truncates_both_files_consistently(corpus):
    report = export_book.export(SYMBOL, DATE, max_events=3)

    assert report.events == 3
    assert report.truncated is True
    assert report.last_timestamp == 1001
    # Only the image at or before the last exported event survives.
    assert [row[0] for row in read_csv(report.reference_path)[1:]] == ["1001", "1001"]
    assert report.images == 1


def test_max_events_never_cuts_a_millisecond_in_half(corpus):
    # The vendor emits an image once every update sharing an exchange millisecond has been
    # applied, so a cut inside a group leaves the last image describing a book strictly
    # ahead of the replayed one -- a guaranteed mismatch that looks exactly like a replay
    # defect. Observed on BTCUSDT 2026-06-01 before the exporter rounded up to the group
    # boundary. Rows 4 and 5 here both sit at 1002; asking for 4 must yield 5.
    report = export_book.export(SYMBOL, DATE, max_events=4)

    assert report.events == 5
    assert report.truncated is True
    assert report.last_timestamp == 1002
    assert [row[0] for row in read_csv(report.events_path)[1:]] == [
        "1000",
        "1000",
        "1001",
        "1002",
        "1002",
    ]


def test_max_events_landing_exactly_on_a_boundary_does_not_overrun(corpus):
    # Three events covers 1000, 1000, 1001 exactly, and 1001 is complete, so nothing extra
    # is owed -- the round-up must not swallow the next millisecond as well.
    report = export_book.export(SYMBOL, DATE, max_events=3)
    assert report.events == 3


def test_a_full_export_is_not_marked_truncated(corpus):
    assert export_book.export(SYMBOL, DATE).truncated is False
    assert export_book.export(SYMBOL, DATE, max_events=99).truncated is False


def test_output_defaults_under_the_data_root(corpus):
    # The output is raw vendor rows, so it must land where the gitignore already covers it
    # rather than wherever the caller happened to be (Tardis Clause 9.2(2), C9).
    from perpcarry import storage

    report = export_book.export(SYMBOL, DATE)
    assert storage.data_root() in report.events_path.parents


def test_a_missing_partition_is_an_error_not_an_empty_export():
    with pytest.raises(export_book.ExportError, match="no .* partition"):
        export_book.export("ABSENTUSDT", DATE)
