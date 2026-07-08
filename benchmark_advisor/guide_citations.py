"""Offline citation index for the Benchmark Advisor statistical guide (BA5.2).

The index is deterministic and file-backed: it reads the curated
``STATISTICAL_GUIDE.md`` tables, audits rule ids/source keys, and returns compact
v2 citation cards for planner/UI explanations. It does not retrieve from the
network and it does not participate in validator decisions.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .guide import GUIDE_VERSION, KNOWN_RULE_IDS
from .schema import TEST_FAMILIES, RationaleRole, StatisticalGuideReference
from .v2_schema import LocalStatisticalCitation

DEFAULT_GUIDE_PATH = (
    Path(__file__).resolve().parents[1] / "docs_benchmark_advisor" / "planning" / "STATISTICAL_GUIDE.md"
)

_RULE_ID_RE = re.compile(r"`(G\d+\.[A-Za-z0-9_.]+)`")
_SOURCE_KEY_RE = re.compile(r"`([^`]+)`")

_ROLE_BY_FAMILY: dict[str, RationaleRole] = {
    "G1": "intent_mapping",
    "G2": "metric_choice",
    "G3": "distribution_choice",
    "G4": "budget_power",
    "G5": "criterion_choice",
    "G6": "claim_boundary",
    "G7": "ui_explanation",
}

_METHOD_FAMILY_RULE_IDS: dict[str, tuple[str, ...]] = {
    "paired_bootstrap": (
        "G5.criterion.paired_bootstrap",
        "G2.metric.pairwise_delta",
        "G4.repeats.not_independent_tasks",
    ),
    "two_proportion_wilson": (
        "G5.criterion.wilson_planning",
        "G4.mde.heuristic",
    ),
    "non_inferiority_margin": (
        "G1.regression.non_inferiority",
        "G2.metric.non_inferiority",
        "G5.criterion.non_inferiority",
    ),
    "rank_stability_bootstrap": (
        "G1.leaderboard.ranking",
        "G2.metric.rank_stability",
        "G5.criterion.rank_stability",
    ),
    "diagnostic_descriptive": (
        "G1.diagnostic.slice",
        "G2.metric.diagnostic_slice",
        "G5.criterion.descriptive_diagnostic",
    ),
    "multiplicity": (
        "G5.multiple.holm_confirmatory",
        "G5.multiple.bh_diagnostic",
        "G5.multiple.primary_vs_exploratory",
    ),
}

_METHOD_FAMILY_ALIASES: dict[str, str] = {
    "wilson_planning": "two_proportion_wilson",
    "non_inferiority": "non_inferiority_margin",
    "rank_stability": "rank_stability_bootstrap",
    "diagnostic": "diagnostic_descriptive",
}

METHOD_FAMILY_RULE_IDS: dict[str, tuple[str, ...]] = {
    **_METHOD_FAMILY_RULE_IDS,
    **{alias: _METHOD_FAMILY_RULE_IDS[canonical] for alias, canonical in _METHOD_FAMILY_ALIASES.items()},
}

ADVISOR_MODE_RULE_IDS: dict[str, tuple[str, ...]] = {
    "pairwise": (
        "G1.pairwise.selection",
        "G2.metric.pairwise_delta",
        "G5.criterion.paired_bootstrap",
        "G6.claim.no_universal_best",
    ),
    "leaderboard": (
        "G1.leaderboard.ranking",
        "G2.metric.rank_stability",
        "G5.criterion.rank_stability",
        "G6.claim.no_universal_best",
    ),
    "regression": (
        "G1.regression.non_inferiority",
        "G2.metric.non_inferiority",
        "G5.criterion.non_inferiority",
        "G6.claim.confirmatory_vs_exploratory",
    ),
    "diagnostic": (
        "G1.diagnostic.slice",
        "G2.metric.diagnostic_slice",
        "G5.criterion.descriptive_diagnostic",
        "G6.claim.diagnostic_not_selection",
    ),
}


class GuideCitationIndexError(ValueError):
    """Raised when the local guide index cannot be audited."""


@dataclass(frozen=True)
class GuideRuleRecord:
    rule_id: str
    section: str
    validator_behavior: str
    evidence_status: str
    source_keys: tuple[str, ...]
    repair_suggestions: str
    snippet: str


@dataclass(frozen=True)
class SourceReference:
    source_key: str
    reference: str
    status: str


@dataclass(frozen=True)
class GuideCitationIndex:
    records: dict[str, GuideRuleRecord]
    source_references: dict[str, SourceReference]

    def citation_for_rule(self, rule_id: str) -> LocalStatisticalCitation:
        try:
            record = self.records[rule_id]
        except KeyError as exc:
            raise GuideCitationIndexError(f"unknown guide rule id: {rule_id}") from exc
        return _to_local_citation(record)

    def citations_for_rules(self, rule_ids: Iterable[str]) -> list[LocalStatisticalCitation]:
        seen: set[str] = set()
        citations: list[LocalStatisticalCitation] = []
        for rule_id in rule_ids:
            if rule_id in seen:
                continue
            seen.add(rule_id)
            citations.append(self.citation_for_rule(rule_id))
        return citations

    def citations_for_method_family(self, method_family: str) -> list[LocalStatisticalCitation]:
        canonical = _METHOD_FAMILY_ALIASES.get(method_family, method_family)
        try:
            rule_ids = _METHOD_FAMILY_RULE_IDS[canonical]
        except KeyError as exc:
            known = ", ".join(sorted({*TEST_FAMILIES, "multiplicity"}))
            raise GuideCitationIndexError(f"unknown method family: {method_family}; known: {known}") from exc
        return self.citations_for_rules(rule_ids)

    def citations_for_advisor_mode(self, mode: str) -> list[LocalStatisticalCitation]:
        try:
            rule_ids = ADVISOR_MODE_RULE_IDS[mode]
        except KeyError as exc:
            known = ", ".join(sorted(ADVISOR_MODE_RULE_IDS))
            raise GuideCitationIndexError(f"unknown advisor mode: {mode}; known: {known}") from exc
        return self.citations_for_rules(rule_ids)


def load_guide_citation_index(guide_path: Path | str = DEFAULT_GUIDE_PATH) -> GuideCitationIndex:
    path = Path(guide_path)
    text = path.read_text(encoding="utf-8")
    index = GuideCitationIndex(records=_parse_rule_records(text), source_references=_parse_source_map(text))
    _audit(index)
    return index


def _parse_rule_records(text: str) -> dict[str, GuideRuleRecord]:
    records: dict[str, GuideRuleRecord] = {}
    section = ""
    lines = text.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("### G"):
            section = line.removeprefix("### ").strip()
        if _is_table_header(line, "rule_id"):
            headers = _split_table_row(line)
            idx += 2
            while idx < len(lines) and lines[idx].lstrip().startswith("|"):
                cells = _split_table_row(lines[idx])
                row = dict(zip(headers, cells, strict=False))
                rule_id = _extract_rule_id(row.get("rule_id", ""))
                if rule_id:
                    records[rule_id] = GuideRuleRecord(
                        rule_id=rule_id,
                        section=section,
                        validator_behavior=_clean_cell(row.get("Validator behavior", "")),
                        evidence_status=_clean_cell(row.get("Evidence status", "")),
                        source_keys=tuple(_extract_source_keys(row.get("Source keys", ""))),
                        repair_suggestions=_clean_cell(row.get("Repair suggestions", "")),
                        snippet=_build_snippet(headers, row),
                    )
                idx += 1
            continue
        idx += 1
    return records


def _parse_source_map(text: str) -> dict[str, SourceReference]:
    marker = "## Source Reference Map"
    if marker not in text:
        raise GuideCitationIndexError("STATISTICAL_GUIDE.md has no Source Reference Map")
    lines = text.split(marker, 1)[1].splitlines()
    source_map: dict[str, SourceReference] = {}
    idx = 0
    while idx < len(lines):
        if _is_table_header(lines[idx], "source_key"):
            headers = _split_table_row(lines[idx])
            idx += 2
            while idx < len(lines) and lines[idx].lstrip().startswith("|"):
                cells = _split_table_row(lines[idx])
                row = dict(zip(headers, cells, strict=False))
                keys = _SOURCE_KEY_RE.findall(row.get("source_key", ""))
                if keys:
                    key = keys[0]
                    source_map[key] = SourceReference(
                        source_key=key,
                        reference=_clean_cell(row.get("Reference", "")),
                        status=_clean_cell(row.get("Status", "")),
                    )
                idx += 1
            break
        idx += 1
    return source_map


def _audit(index: GuideCitationIndex) -> None:
    if not index.records:
        raise GuideCitationIndexError("no guide rule rows parsed")
    missing_runtime = set(index.records) - KNOWN_RULE_IDS
    missing_index = KNOWN_RULE_IDS - set(index.records)
    if missing_runtime or missing_index:
        raise GuideCitationIndexError(
            "guide citation index differs from runtime registry: "
            f"only_in_guide={sorted(missing_runtime)}, only_in_runtime={sorted(missing_index)}"
        )
    for record in index.records.values():
        if not record.section:
            raise GuideCitationIndexError(f"{record.rule_id} has no section label")
        if not record.evidence_status:
            raise GuideCitationIndexError(f"{record.rule_id} has no evidence status")
        if not record.validator_behavior:
            raise GuideCitationIndexError(f"{record.rule_id} has no validator behavior")
        if not record.source_keys:
            raise GuideCitationIndexError(f"{record.rule_id} has no source keys")
        missing_keys = set(record.source_keys) - set(index.source_references)
        if missing_keys:
            raise GuideCitationIndexError(
                f"{record.rule_id} cites missing source keys: {sorted(missing_keys)}"
            )


def _to_local_citation(record: GuideRuleRecord) -> LocalStatisticalCitation:
    family = record.rule_id.split(".", 1)[0]
    role = _ROLE_BY_FAMILY[family]
    return LocalStatisticalCitation(
        source_id=f"{GUIDE_VERSION}:{record.rule_id}",
        title="Benchmark Advisor Statistical Guide",
        section=record.section,
        evidence_status=record.evidence_status,
        source_keys=list(record.source_keys),
        snippet=record.snippet,
        guide_references=[
            StatisticalGuideReference(
                guide_version=GUIDE_VERSION,
                rule_id=record.rule_id,
                section=record.section,
                role=role,
            )
        ],
    )


def _is_table_header(line: str, first_header: str) -> bool:
    cells = _split_table_row(line)
    return bool(cells) and cells[0] == first_header


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _extract_rule_id(cell: str) -> str | None:
    match = _RULE_ID_RE.search(cell)
    return match.group(1) if match else None


def _extract_source_keys(cell: str) -> list[str]:
    return _SOURCE_KEY_RE.findall(cell)


def _clean_cell(cell: str) -> str:
    clean = re.sub(r"`([^`]+)`", r"\1", cell)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _build_snippet(headers: list[str], row: dict[str, str]) -> str:
    skip = {"rule_id", "Evidence status", "Source keys"}
    parts: list[str] = []
    for header in headers:
        if header in skip:
            continue
        value = _clean_cell(row.get(header, ""))
        if value:
            parts.append(value)
        if len(" ".join(parts)) >= 260:
            break
    snippet = " ".join(parts)
    return snippet[:357].rstrip() + "..." if len(snippet) > 360 else snippet
