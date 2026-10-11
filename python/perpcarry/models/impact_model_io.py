"""M5-T3: strict, inspectable per-symbol impact artifacts, without raw book rows."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path

from perpcarry.models.impact_model import FORMS, TARGET, FitReport, FittedLaw, ImpactModelError

SCHEMA_VERSION = 1
SIZE_UNIT = "ADV fraction"
DEPTHS = ("inside_validated_depth", "beyond_validated_depth")
FIT_FIELDS = {
    "side",
    "schedule",
    "depth",
    "size_regime",
    "size_bin_edges_adv_fraction",
    "model",
    "train_rows",
    "test_rows",
    "train_days",
    "test_days",
    "training_size_min",
    "training_size_max",
    "usable_as_nonnegative_impact_law",
    "zero_training_targets",
    "negative_training_targets",
    "fit_rows_used",
    "beyond_validated_depth_rows",
}
ARTIFACT_FIELDS = {
    "schema_version",
    "symbol",
    "primary_form",
    "target",
    "size_unit",
    "output_unit",
    "train_start",
    "train_end_exclusive",
    "test_end_exclusive",
    "provenance",
    "caveats",
    "fits",
}
PROVENANCE_FIELDS = {
    "kind",
    "fit_date",
    "code_version",
    "fitting_source_sha256",
    "inputs",
    "corpus_days",
    "supporting_train_rows",
    "supporting_test_rows",
    "row_count_scope",
}
ROW_COUNT_SCOPE = "unique rows supporting all_sizes square_root fits; bins/forms overlap"


def _fields(value, expected, name):
    if not isinstance(value, dict) or set(value) != expected:
        raise ImpactModelError(f"{name}: missing or unexpected fields")


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ImpactModelError(f"{name}: expected nonempty text")


def _count(value, name):
    if type(value) is not int or value < 0:
        raise ImpactModelError(f"{name}: expected nonnegative integer")


def _number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ImpactModelError(f"{name}: expected finite number")


def _date(value):
    if not isinstance(value, str) or str(dt.date.fromisoformat(value)) != value:
        raise ImpactModelError("expected canonical ISO date")
    return value


def _days(values):
    if not isinstance(values, list) or not values or values != sorted(set(values)):
        raise ImpactModelError("days must be nonempty, sorted and unique")
    return [_date(value) for value in values]


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ImpactModelError("expected SHA-256 digest")


def validate(artifact: dict) -> None:
    """Reject incompatible schemas and ambiguous units/coverage before use or save."""
    try:
        _validate(artifact)
    except (TypeError, ValueError, OverflowError) as error:
        if isinstance(error, ImpactModelError):
            raise
        raise ImpactModelError(f"invalid impact artifact: {error}") from error


def _validate_provenance(provenance, symbol, start, end):
    _fields(provenance, PROVENANCE_FIELDS, "provenance")
    if provenance["kind"] not in ("synthetic", "verified_calibration"):
        raise ImpactModelError("unknown provenance kind")
    _date(provenance["fit_date"])
    _text(provenance["code_version"], "code_version")
    _digest(provenance["fitting_source_sha256"])
    if provenance["row_count_scope"] != ROW_COUNT_SCOPE:
        raise ImpactModelError("unsupported row count scope")
    for key in ("supporting_train_rows", "supporting_test_rows"):
        _count(provenance[key], key)
    corpus_days = _days(provenance["corpus_days"])
    if any(not start <= day < end for day in corpus_days):
        raise ImpactModelError("corpus day outside fold")
    if not isinstance(provenance["inputs"], list):
        raise ImpactModelError("inputs must be a list")
    input_days = []
    for item in provenance["inputs"]:
        _fields(item, {"symbol", "date", "manifest_sha256"}, "input")
        if item["symbol"] != symbol:
            raise ImpactModelError("input symbol mismatch")
        day = _date(item["date"])
        if not start <= day < end or day in input_days:
            raise ImpactModelError("duplicate or out-of-fold input")
        input_days.append(day)
        _digest(item["manifest_sha256"])
    if provenance["kind"] == "verified_calibration" and not set(corpus_days) <= set(input_days):
        raise ImpactModelError("missing calibration evidence for corpus days")
    return corpus_days


def _validate_fit(fit_record, start, cutoff, end):
    days = set()
    _fields(fit_record, FIT_FIELDS, "fit")
    _fields(fit_record["model"], {"form", "coefficient", "exponent"}, "model")
    model = fit_record["model"]
    if (
        model["form"] not in FORMS
        or fit_record["depth"] not in DEPTHS
        or fit_record["side"]
        not in (
            "buy",
            "sell",
        )
    ):
        raise ImpactModelError("unsupported fit identity")
    _text(fit_record["schedule"], "schedule")
    regime = fit_record["size_regime"]
    if not isinstance(regime, str) or not re.fullmatch(r"all_sizes|training_size_bin_\d+", regime):
        raise ImpactModelError("unsupported size regime")
    identity = (
        fit_record["side"],
        fit_record["schedule"],
        fit_record["depth"],
        regime,
        model["form"],
    )
    for key in ("coefficient", "exponent"):
        _number(model[key], key)
    fixed = {"square_root": 0.5, "linear": 1.0}
    if model["form"] in fixed and model["exponent"] != fixed[model["form"]]:
        raise ImpactModelError("exponent disagrees with form")
    usable = model["coefficient"] >= 0 and model["exponent"] > 0
    if type(fit_record["usable_as_nonnegative_impact_law"]) is not bool or (
        fit_record["usable_as_nonnegative_impact_law"] != usable
    ):
        raise ImpactModelError("incorrect usability flag")
    for key in (
        "train_rows",
        "test_rows",
        "zero_training_targets",
        "negative_training_targets",
        "fit_rows_used",
        "beyond_validated_depth_rows",
    ):
        _count(fit_record[key], key)
    if not fit_record["train_rows"] or not fit_record["test_rows"]:
        raise ImpactModelError("evaluated fit requires training and test rows")
    if (
        fit_record["zero_training_targets"] + fit_record["negative_training_targets"]
        > fit_record["train_rows"]
    ):
        raise ImpactModelError("invalid target counts")
    used = fit_record["train_rows"] - (
        fit_record["zero_training_targets"] + fit_record["negative_training_targets"]
        if model["form"] == "power_diagnostic"
        else 0
    )
    if fit_record["fit_rows_used"] != used:
        raise ImpactModelError("invalid fitted row count")
    deep_rows = (
        fit_record["train_rows"] + fit_record["test_rows"]
        if fit_record["depth"] == DEPTHS[1]
        else 0
    )
    if fit_record["beyond_validated_depth_rows"] != deep_rows:
        raise ImpactModelError("incorrect beyond-depth count")
    for key, low, high in (("train_days", start, cutoff), ("test_days", cutoff, end)):
        observed = _days(fit_record[key])
        if any(not low <= day < high for day in observed):
            raise ImpactModelError("fit days violate chronological split")
        if len(observed) > fit_record[key.replace("days", "rows")]:
            raise ImpactModelError("more days than rows")
        days.update(observed)
    edges = fit_record["size_bin_edges_adv_fraction"]
    if not isinstance(edges, list):
        raise ImpactModelError("edges must be a list")
    for size in [*edges, fit_record["training_size_min"], fit_record["training_size_max"]]:
        _number(size, "size")
        if size <= 0:
            raise ImpactModelError("size must be positive ADV fraction")
    if (
        edges != sorted(set(edges))
        or fit_record["training_size_min"] > fit_record["training_size_max"]
    ):
        raise ImpactModelError("invalid size boundaries")
    if regime != "all_sizes" and int(regime.rsplit("_", 1)[1]) > len(edges):
        raise ImpactModelError("size bin outside edges")
    return identity, days


def _validate(artifact):
    _fields(artifact, ARTIFACT_FIELDS, "artifact")
    if type(artifact["schema_version"]) is not int or artifact["schema_version"] != SCHEMA_VERSION:
        raise ImpactModelError("unknown schema version")
    _text(artifact["symbol"], "symbol")
    if (
        artifact["primary_form"],
        artifact["target"],
        artifact["size_unit"],
        artifact["output_unit"],
    ) != (
        "square_root",
        TARGET,
        SIZE_UNIT,
        "bps",
    ):
        raise ImpactModelError("unsupported form, target or units")
    start, cutoff, end = (
        _date(artifact[key])
        for key in (
            "train_start",
            "train_end_exclusive",
            "test_end_exclusive",
        )
    )
    if not start < cutoff < end:
        raise ImpactModelError("invalid chronological window")
    provenance = artifact["provenance"]
    corpus_days = _validate_provenance(provenance, artifact["symbol"], start, end)
    if not isinstance(artifact["caveats"], list) or not artifact["caveats"]:
        raise ImpactModelError("caveats required")
    for caveat in artifact["caveats"]:
        _text(caveat, "caveat")
    if not isinstance(artifact["fits"], list) or not artifact["fits"]:
        raise ImpactModelError("no fitted laws")
    identities, days, counts = set(), set(), [0, 0]
    has_primary = False
    for fit_record in artifact["fits"]:
        identity, fit_days = _validate_fit(fit_record, start, cutoff, end)
        if identity in identities:
            raise ImpactModelError("duplicate fitted law")
        identities.add(identity)
        days.update(fit_days)
        if (
            fit_record["size_regime"] == "all_sizes"
            and fit_record["model"]["form"] == "square_root"
        ):
            has_primary = True
            counts[0] += fit_record["train_rows"]
            counts[1] += fit_record["test_rows"]
    if (
        not has_primary
        or sorted(days) != corpus_days
        or counts
        != [
            provenance["supporting_train_rows"],
            provenance["supporting_test_rows"],
        ]
    ):
        raise ImpactModelError("primary law or provenance counts/days disagree")


def from_fit_report(
    report: FitReport,
    symbol: str,
    *,
    fit_date: str,
    code_version: str,
    kind: str = "verified_calibration",
) -> dict:
    """Export evaluated laws; retain unsupported strata as explicit coverage caveats.

    Code version/date describe the fitting run, never an inferred later export run.
    Synthetic provenance must be explicitly selected for synthetic fixtures.
    """
    s = report.summary
    fits, unavailable = [], []
    for record in s["fits"]:
        if record["symbol"] != symbol:
            continue
        if record["status"] != "evaluated":
            unavailable.append(json.dumps(record, sort_keys=True, allow_nan=False))
            continue
        selected = {
            key: deepcopy(record[key]) for key in FIT_FIELDS if key != "beyond_validated_depth_rows"
        }
        selected["beyond_validated_depth_rows"] = (
            record["train_rows"] + record["test_rows"] if record["depth"] == DEPTHS[1] else 0
        )
        fits.append(selected)
    primary = [
        f for f in fits if f["size_regime"] == "all_sizes" and f["model"]["form"] == "square_root"
    ]
    a = {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol,
        "primary_form": s["primary_form"],
        "target": s["config"]["target"],
        "size_unit": SIZE_UNIT,
        "output_unit": "bps",
        **{key: s[key] for key in ("train_start", "train_end_exclusive", "test_end_exclusive")},
        "provenance": {
            "kind": kind,
            "fit_date": fit_date,
            "code_version": code_version,
            "fitting_source_sha256": s["fitting_source_sha256"],
            "inputs": deepcopy([i for i in s.get("inputs", []) if i["symbol"] == symbol]),
            "corpus_days": sorted(
                {day for f in fits for key in ("train_days", "test_days") for day in f[key]}
            ),
            "supporting_train_rows": sum(f["train_rows"] for f in primary),
            "supporting_test_rows": sum(f["test_rows"] for f in primary),
            "row_count_scope": ROW_COUNT_SCOPE,
        },
        "caveats": [
            s[key]
            for key in (
                "caveat",
                "weighting",
                "size_regimes",
                "signed_targets",
                "power_diagnostic",
                "exclusion_note",
            )
        ]
        + ["Unsupported stratum: " + item for item in unavailable]
        + [
            "Group coverage: " + json.dumps(g, sort_keys=True, allow_nan=False)
            for g in s["groups"]
            if g["symbol"] == symbol
        ],
        "fits": fits,
    }
    validate(a)
    return a


def save(artifact: dict, path: Path) -> None:
    """Validate then atomically replace with human-readable, lossless JSON."""
    validate(artifact)
    payload = json.dumps(artifact, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ImpactModelError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise ImpactModelError(f"non-finite JSON number: {value}")


def load(path: Path) -> dict:
    try:
        artifact = json.loads(
            Path(path).read_text(), object_pairs_hook=_unique_pairs, parse_constant=_reject_constant
        )
    except (OSError, ValueError) as error:
        raise ImpactModelError(f"cannot load impact model: {error}") from error
    validate(artifact)
    return artifact


def law(
    artifact: dict,
    *,
    side: str,
    schedule: str,
    depth: str,
    size_regime: str,
    form: str = "square_root",
) -> FittedLaw:
    """Explicit stratum lookup; no fallback, pooling, or choice from held-out scores."""
    validate(artifact)
    for f in artifact["fits"]:
        if (f["side"], f["schedule"], f["depth"], f["size_regime"], f["model"]["form"]) == (
            side,
            schedule,
            depth,
            size_regime,
            form,
        ):
            return FittedLaw(**f["model"])
    raise ImpactModelError("requested fitted stratum is unavailable")
