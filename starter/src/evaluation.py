"""TODO: evaluate retrieved evidence and preserve per-query traces."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any

def _first_value(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return None


def _normalise_text(value: Any) -> str:
    text = unicodedata.normalize("NFC", str(value or "")).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _normalise_source(value: Any) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    # Compare full normalized path first; basename also permits a manifest
    # to use "manual.pdf" while the ingested source stores "data/manual.pdf".
    return str(PurePosixPath(raw)).casefold()


def _source_matches(actual_source: Any, actual_doc_id: Any, expected: Any) -> bool:
    if expected is None:
        return False
    expected_norm = _normalise_source(expected)
    expected_stem = PurePosixPath(expected_norm).stem
    expected_name = PurePosixPath(expected_norm).name
    for actual in (actual_source, actual_doc_id):
        if actual is not None:
            act_norm = _normalise_source(actual)
            if (act_norm == expected_norm
                or PurePosixPath(act_norm).name == expected_name
                or PurePosixPath(act_norm).stem == expected_stem):
                return True
    return False


def _extract_gold_candidates(question: dict[str, Any]) -> list[dict[str, Any]]:
    raw = _first_value(
        question,
        ("gold_evidence", "gold", "expected_evidence", "evidence"),
    )

    if raw is None:
        # Also accept a flat record when the benchmark keeps gold fields
        # alongside the question rather than under gold_evidence.
        evidence = _first_value(
            question,
            ("evidence_quote", "gold_evidence", "gold_text", "gold_quote", "evidence_text", "gold_snippet", "evidence")
        )
        source = _first_value(
            question,
            ("gold_source_id", "gold_source", "source_id", "source", "document_id")
        )
        page = _first_value(question, ("gold_page", "page"))
        if evidence is None or source is None or page is None:
            raise ValueError(
                f"Question {question.get('id', '<unknown>')} needs "
                "gold_evidence entries with source, page and evidence."
            )
        raw = [{"source": source, "page": page, "evidence": evidence}]

    if isinstance(raw, dict):
        # A wrapper may contain a list of acceptable alternatives.
        alternatives = raw.get("alternatives")
        if isinstance(alternatives, list):
            inherited = {k: v for k, v in raw.items() if k != "alternatives"}
            candidates = []
            for item in alternatives:
                if isinstance(item, dict):
                    candidates.append({**inherited, **item})
                else:
                    candidates.append({**inherited, "evidence": item})
            raw = candidates
        else:
            raw = [raw]

    if not isinstance(raw, list) or not raw:
        raise ValueError(
            f"Question {question.get('id', '<unknown>')} has invalid/empty gold_evidence."
        )

    candidates: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            source = _first_value(question, ("gold_source", "source"))
            page = _first_value(question, ("gold_page", "page"))
            item = {"source": source, "page": page, "evidence": item}
        if not isinstance(item, dict):
            raise ValueError("Each gold_evidence alternative must be an object or string.")

        # Support explicit alternative evidence snippets for the same source/page.
        source = _first_value(item, ("source", "gold_source_id", "gold_source", "document_id", "file", "filename"))
        page = _first_value(item, ("page", "gold_page", "page_number"))
        evidence = _first_value(
            item, ("evidence_quote", "evidence", "quote", "gold_text", "snippet", "text")
        )
        evidence_alternatives = _first_value(
            item, ("evidence_alternatives", "alternative_quotes")
        )

        if source is None or page is None:
            raise ValueError(
                f"Gold alternative for question {question.get('id', '<unknown>')} "
                "must include source and page."
            )
        if evidence is None and not evidence_alternatives:
            raise ValueError(
                f"Gold alternative for question {question.get('id', '<unknown>')} "
                "must include evidence text."
            )

        if isinstance(evidence, str):
            required_phrases = [evidence]
        elif isinstance(evidence, list):
            required_phrases = [str(x) for x in evidence if str(x).strip()]
        elif evidence is None:
            required_phrases = []
        else:
            required_phrases = [str(evidence)]

        if evidence_alternatives:
            if isinstance(evidence_alternatives, str):
                evidence_alternatives = [evidence_alternatives]
            alternative_sets = [[str(x)] for x in evidence_alternatives]
        else:
            alternative_sets = [required_phrases]

        if not any(all(_normalise_text(x) for x in group) for group in alternative_sets):
            raise ValueError(
                f"Gold evidence for question {question.get('id', '<unknown>')} is empty."
            )

        candidates.append(
            {
                "source": str(source),
                "page": int(page),
                "evidence_alternatives": alternative_sets,
            }
        )

    return candidates


def _hit_source_page(hit: dict[str, Any]) -> tuple[Any, Any, Any]:
    metadata = hit.get("metadata") or {}
    source = hit.get("source", metadata.get("source"))
    page = hit.get("page", metadata.get("page"))
    document_id = hit.get("document_id", metadata.get("document_id"))
    return source, page, document_id


def _hit_matches_candidate(
    hit: dict[str, Any], candidate: dict[str, Any]
) -> bool:
    source, page, doc_id = _hit_source_page(hit)
    if not _source_matches(source, doc_id, candidate["source"]):
        return False
    try:
        if int(page) != int(candidate["page"]):
            return False
    except (TypeError, ValueError):
        return False

    hit_text = _normalise_text(hit.get("text", ""))
    if not hit_text:
        return False

    # Any documented evidence alternative is accepted. If an alternative is
    # a list, every phrase in that list must be contained in this same chunk.
    for phrase_group in candidate["evidence_alternatives"]:
        normalized_phrases = [_normalise_text(p) for p in phrase_group]
        if normalized_phrases and all(p in hit_text for p in normalized_phrases):
            return True
    return False

def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    """TODO: check source/page and enough gold evidence; keep hit@1 and hit@3 trace.

    Accept any documented alternative gold evidence. Do not infer human grounding
    or chunk coherence labels from exact string match.
    """
    # raise NotImplementedError("TODO: evaluate_query")
    question_id = str(
        _first_value(question, ("id", "question_id", "qid")) or "unknown"
    )
    question_text = _first_value(question, ("question", "query", "input", "text"))
    split = str(_first_value(question, ("split", "set", "partition")) or "unspecified").lower()
    candidates = _extract_gold_candidates(question)

    matched_index = None
    matched_gold_index = None
    for hit_index, hit in enumerate(hits[:3]):
        for gold_index, candidate in enumerate(candidates):
            if _hit_matches_candidate(hit, candidate):
                matched_index = hit_index
                matched_gold_index = gold_index
                break
        if matched_index is not None:
            break

    top1_hit = bool(
        hits
        and any(_hit_matches_candidate(hits[0], candidate) for candidate in candidates)
    )

    return {
        "question_id": question_id,
        "split": split,
        "question": question_text,
        "hit_at_1": top1_hit,
        "evidence_hit_at_3": matched_index is not None,
        "matched_hit_rank": matched_index + 1 if matched_index is not None else None,
        "matched_gold_alternative": matched_gold_index,
        "gold_alternatives_count": len(candidates),
    }

def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """TODO: aggregate Hit@1 and Evidence Hit@3 by strategy and dev/test split."""
    # raise NotImplementedError("TODO: summarize")
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    for trace in traces:
        strategy = str(trace.get("strategy", "unknown"))
        split = str(trace.get("split", "unspecified")).lower()
        groups[(strategy, split)].append(trace)

    summary: dict[str, Any] = {}
    for (strategy, split), items in sorted(groups.items()):
        total = len(items)
        hit1_count = sum(bool(item.get("hit_at_1")) for item in items)
        hit3_count = sum(bool(item.get("evidence_hit_at_3")) for item in items)
        summary.setdefault(strategy, {})[split] = {
            "questions": total,
            "hit_at_1": {
                "hits": hit1_count,
                "total": total,
                "rate": hit1_count / total if total else None,
            },
            "evidence_hit_at_3": {
                "hits": hit3_count,
                "total": total,
                "rate": hit3_count / total if total else None,
            },
        }

    return summary