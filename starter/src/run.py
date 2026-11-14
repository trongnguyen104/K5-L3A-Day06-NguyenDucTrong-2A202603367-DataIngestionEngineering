"""Suggested pipeline entry point; TODO: implement the orchestration."""

from __future__ import annotations

import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .chunking import by_paragraph, fixed_size
from .embeddings import MyEmbedder
from .evaluation import evaluate_query, summarize
from .ingestion import load_pdf
from .store import PgVectorStore


DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
TOP_K = 3
FIXED_SIZE = 500
FIXED_OVERLAP = 50
PARAGRAPH_MAX_SIZE = 500


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def _resolve_path(value: str, root: Path, corpus_dir: Path) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate
    root_candidate = (root / candidate).resolve()
    if root_candidate.exists():
        return root_candidate
    return (corpus_dir / candidate).resolve()


def _find_manifest(root: Path, corpus_dir: Path) -> Path | None:
    # 1. Nếu người dùng cấu hình MANIFEST_PATH trong .env thì ưu tiên dùng trước
    configured = os.getenv("MANIFEST_PATH")
    if configured:
        path = _resolve_path(configured, root, corpus_dir)
        if not path.is_file():
            raise FileNotFoundError(f"MANIFEST_PATH does not exist: {path}")
        return path
    # 2. Tự động tìm ở cả starter/ lẫn thư mục gốc của repo
    candidates = (
        corpus_dir / "manifest.json",
        root / "manifest.json",
        root.parent / "data" / "manifest.json",
        root.parent / "manifest.json",
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def _manifest_documents(manifest: Any) -> list[dict[str, Any]]:
    if isinstance(manifest, list):
        documents = manifest
    elif isinstance(manifest, dict):
        documents = manifest.get("documents")
    else:
        documents = None

    if not isinstance(documents, list) or not documents:
        raise ValueError(
            "Manifest must be a non-empty list or an object with a 'documents' list."
        )
    if not all(isinstance(item, dict) for item in documents):
        raise ValueError("Every manifest document must be a JSON object.")
    return documents


def _content_page_numbers(document: dict[str, Any]) -> set[int] | None:
    raw = document.get("content_pages", document.get("included_pages"))
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("Manifest content_pages must be a list of physical page numbers.")

    numbers: set[int] = set()
    for item in raw:
        if isinstance(item, dict):
            item = item.get("page", item.get("page_number"))
        if item is None:
            raise ValueError("A content_pages item is missing its page number.")
        numbers.add(int(item))
    return numbers


def _load_corpus(root: Path, corpus_dir: Path) -> tuple[list[Any], list[dict[str, Any]]]:
    manifest_path = _find_manifest(root, corpus_dir)
    document_specs: list[dict[str, Any]]

    if manifest_path:
        manifest = _load_json(manifest_path)
        document_specs = _manifest_documents(manifest)
    else:
        pdfs = sorted(corpus_dir.rglob("*.pdf"))
        if not pdfs:
            raise FileNotFoundError(
                f"No PDF files found under {corpus_dir}. Put corpus PDFs in data/ "
                "or provide MANIFEST_PATH."
            )
        document_specs = [
            {
                "document_id": pdf.stem,
                "path": str(pdf),
                "source": str(pdf.relative_to(corpus_dir)).replace("\\", "/"),
                "metadata": {},
            }
            for pdf in pdfs
        ]
        print(
            "WARNING: no manifest.json found. PDFs will be ingested with empty "
            "custom metadata; add a manifest to define verified filter fields."
        )

    pages: list[Any] = []
    document_report: list[dict[str, Any]] = []

    for index, spec in enumerate(document_specs, start=1):
        local_path_value = (
            spec.get("path")
            or spec.get("file")
            or spec.get("filename")
            or spec.get("source_path")
        )
        if local_path_value is None:
            source_path_or_url = spec.get("source_path_or_url")
            if source_path_or_url and str(source_path_or_url).lower().startswith(("http://", "https://")):
                raise ValueError(
                    f"Document {spec.get('source_id', index)} points to a URL. "
                    "Download the PDF into data/ and set its local path in manifest.json."
                )
            local_path_value = source_path_or_url

        if not local_path_value:
            raise ValueError(f"Manifest document #{index} is missing its local PDF path.")

        pdf_path = _resolve_path(str(local_path_value), root, corpus_dir)
        if not pdf_path.is_file():
            raise FileNotFoundError(f"PDF not found for manifest document: {pdf_path}")
        if pdf_path.suffix.lower() != ".pdf":
            raise ValueError(f"Only PDF inputs are supported by this pipeline: {pdf_path}")

        document_id = str(
            spec.get("document_id") or spec.get("source_id") or pdf_path.stem
        )
        source = str(
            spec.get("source")
            or spec.get("source_path_or_url")
            or pdf_path.name
        )
        metadata = spec.get("metadata") or spec.get("filter_metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError(f"metadata for {pdf_path.name} must be a JSON object.")

        extracted = load_pdf(pdf_path, document_id=document_id, source=source)
        allowed_pages = _content_page_numbers(spec)
        selected = []
        empty_pages = 0

        for page in extracted:
            if allowed_pages is not None and page.page not in allowed_pages:
                continue
            if not page.text.strip():
                empty_pages += 1
                continue
            page.metadata = {**page.metadata, **metadata}
            selected.append(page)

        pages.extend(selected)
        document_report.append(
            {
                "document_id": document_id,
                "source": source,
                "path": str(pdf_path),
                "physical_pages": len(extracted),
                "selected_content_pages": len(selected),
                "empty_selected_pages": empty_pages,
                "metadata_fields": sorted(metadata.keys()),
                "content_pages_were_explicitly_curated": allowed_pages is not None,
            }
        )

    return pages, document_report


def _find_benchmark(root: Path, corpus_dir: Path) -> Path:
    configured = os.getenv("BENCHMARK_PATH")
    if configured:
        path = _resolve_path(configured, root, corpus_dir)
        if not path.is_file():
            raise FileNotFoundError(f"BENCHMARK_PATH does not exist: {path}")
        return path

    candidates = (
        corpus_dir / "benchmark.json",
        corpus_dir / "questions.json",
        root / "benchmark.json",
        root / "questions.json",
        root.parent / "benchmark" / "benchmark.json",
        root.parent / "benchmark.json",
        root.parent / "data" / "benchmark.json",
    )
    for path in candidates:
        if path.is_file():
            return path

    raise FileNotFoundError(
        "Benchmark JSON not found. Create data/benchmark.json (or set BENCHMARK_PATH). "
        "It must contain at least 20 questions: 15 dev and 5 test."
    )


def _load_questions(path: Path) -> list[dict[str, Any]]:
    payload = _load_json(path)
    if isinstance(payload, list):
        questions = payload
    elif isinstance(payload, dict):
        questions = payload.get("questions")
    else:
        questions = None

    if not isinstance(questions, list) or not questions:
        raise ValueError("Benchmark must be a JSON list or an object with 'questions'.")

    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            raise ValueError(f"Benchmark question #{index} must be an object.")
        if not any(question.get(key) for key in ("question", "query", "input", "text")):
            raise ValueError(f"Benchmark question #{index} has no question/query text.")
        if not any(question.get(key) for key in ("split", "set", "partition")):
            raise ValueError(
                f"Benchmark question #{index} needs split='dev' or split='test'."
            )
        # Evaluate with no hits to validate the gold source/page/evidence schema.
        evaluate_query(question, [])

    splits = [
        str(q.get("split", q.get("set", q.get("partition", "")))).lower()
        for q in questions
    ]
    dev_count = sum(split == "dev" for split in splits)
    test_count = sum(split == "test" for split in splits)
    filter_questions = sum(
        bool(q.get("filters") or q.get("metadata_filter") or q.get("filter"))
        for q in questions
    )
    test_filter_questions = sum(
        split == "test"
        and bool(q.get("filters") or q.get("metadata_filter") or q.get("filter"))
        for q, split in zip(questions, splits)
    )

    if len(questions) < 20 or dev_count < 15 or test_count < 5:
        raise ValueError(
            f"Benchmark needs >=20 questions with >=15 dev and >=5 test; "
            f"found {len(questions)} total, {dev_count} dev, {test_count} test."
        )
    if filter_questions < 3 or test_filter_questions < 1:
        raise ValueError(
            "Benchmark needs at least 3 metadata-filter questions, including "
            "at least 1 test question."
        )

    return questions


def _question_filters(question: dict[str, Any]) -> dict[str, Any]:
    filters = question.get("filters") or question.get("metadata_filter") or question.get("filter") or {}
    if not isinstance(filters, dict):
        raise ValueError(
            f"Filters for question {question.get('id', '<unknown>')} must be an object."
        )
    return filters


def _validate_filter_values(
    questions: list[dict[str, Any]], pages: list[Any]
) -> None:
    metadata_values: dict[str, set[str]] = {}
    for page in pages:
        for key, value in page.metadata.items():
            if key == "is_empty" or value is None:
                continue
            metadata_values.setdefault(str(key), set()).add(str(value))

    for question in questions:
        for key, value in _question_filters(question).items():
            if str(key) not in metadata_values:
                raise ValueError(
                    f"Filter field '{key}' in question {question.get('id')} "
                    "does not exist in corpus metadata. Add it to manifest.json."
                )
            if str(value) not in metadata_values[str(key)]:
                raise ValueError(
                    f"Filter value {value!r} for '{key}' in question "
                    f"{question.get('id')} does not occur in corpus metadata."
                )


def _build_chunks(pages: list[Any]) -> dict[str, list[Any]]:
    strategy_a: list[Any] = []
    strategy_b: list[Any] = []

    for page in pages:
        strategy_a.extend(fixed_size(page, size=FIXED_SIZE, overlap=FIXED_OVERLAP))
        strategy_b.extend(by_paragraph(page, max_size=PARAGRAPH_MAX_SIZE))

    if not strategy_a or not strategy_b:
        raise ValueError("Chunking produced no chunks. Check PDF extraction and content pages.")

    # C changes only retrieval filtering; its chunking and metadata are identical to B.
    return {"A": strategy_a, "B": strategy_b, "C": list(strategy_b)}


def _token_count(embedder: MyEmbedder, text: str) -> int | None:
    tokenizer = getattr(getattr(embedder, "model", None), "tokenizer", None)
    if tokenizer is None:
        return None
    encoded = tokenizer(text, add_special_tokens=True, truncation=False)
    return len(encoded["input_ids"])


def _resource_stats(
    chunks: list[Any],
    embedder: MyEmbedder,
    embedding_seconds: float,
    ingest_seconds: float,
    embedding_reused_from: str | None = None,
) -> dict[str, Any]:
    lengths = [len(chunk.text) for chunk in chunks]
    token_counts = [_token_count(embedder, chunk.text) for chunk in chunks]
    known_tokens = [count for count in token_counts if count is not None]
    max_sequence_length = getattr(embedder.model, "max_seq_length", None)

    return {
        "chunk_count": len(chunks),
        "total_characters": sum(lengths),
        "chunk_length_characters": {
            "min": min(lengths) if lengths else 0,
            "max": max(lengths) if lengths else 0,
            "mean": statistics.mean(lengths) if lengths else 0,
            "median": statistics.median(lengths) if lengths else 0,
            "p95": sorted(lengths)[min(len(lengths) - 1, int(0.95 * len(lengths)))] if lengths else 0,
        },
        "total_tokens": sum(known_tokens) if known_tokens else None,
        "max_tokens_in_chunk": max(known_tokens) if known_tokens else None,
        "model_max_sequence_length": max_sequence_length,
        "chunks_over_model_limit": (
            sum(count > max_sequence_length for count in known_tokens)
            if max_sequence_length and known_tokens else None
        ),
        "embedding_seconds": round(embedding_seconds, 4),
        "ingest_seconds": round(ingest_seconds, 4),
        "embedding_reused_from": embedding_reused_from,
        "estimated_api_cost": 0,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)


def _manual_assessment_template(
    pages: list[Any],
    strategy_chunks: dict[str, list[Any]],
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    locations = []
    for page in pages:
        locations.append(
            {
                "document_id": page.document_id,
                "source": page.source,
                "page": page.page,
            }
        )
    locations = locations[:10]

    coherence = []
    for location in locations:
        strategy_samples = {}
        for strategy, chunks in strategy_chunks.items():
            strategy_samples[strategy] = [
                {"chunk_id": chunk.chunk_id, "text": chunk.text}
                for chunk in chunks
                if chunk.document_id == location["document_id"]
                and chunk.page == location["page"]
            ]
        coherence.append(
            {
                **location,
                "chunks_by_strategy": strategy_samples,
                "manual_score_0_to_2": None,
                "reason": "",
            }
        )

    test_traces = [trace for trace in traces if trace["split"] == "test"]
    metadata_review = []
    grounding_review = []
    for trace in test_traces:
        for hit in trace["hits"]:
            metadata_review.append(
                {
                    "strategy": trace["strategy"],
                    "question_id": trace["question_id"],
                    "chunk_id": hit["chunk_id"],
                    "source": hit.get("source"),
                    "page": hit.get("page"),
                    "metadata": hit.get("metadata", {}),
                    "complete_and_correct": None,
                    "notes": "",
                }
            )
        grounding_review.append(
            {
                "strategy": trace["strategy"],
                "question_id": trace["question_id"],
                "question": trace["question"],
                "top3": trace["hits"],
                "manual_grounding_score_0_to_2": None,
                "reason": "",
            }
        )

    return {
        "instructions": {
            "chunk_coherence": "0=không hiểu do cắt ý; 1=hiểu một phần; 2=tự hiểu được và giữ trọn ý.",
            "metadata_usefulness": "Đánh dấu complete_and_correct sau khi đối chiếu source/page/metadata với tài liệu gốc.",
            "grounding_quality": "0=không có bằng chứng; 1=có nhưng thiếu điều kiện/ngữ cảnh; 2=đủ để trả lời và truy nguồn.",
            "human_review_required": True,
        },
        "chunk_coherence": coherence,
        "metadata_review_test_top3": metadata_review,
        "grounding_quality_test": grounding_review,
    }

def main() -> None:
    """TODO:

    1. Load the corpus and benchmark; validate at least 30 content pages.
    2. Build strategies A (fixed), B (paragraph) and C (B + metadata filter).
    3. Embed with the same model and store vectors/metadata per strategy.
    4. Run the same dev/test questions and save full top-3 traces.
    5. Report retrieval metrics and prepare samples for manual assessment.

    Follow the five dimensions in ../../BENCHMARK.md.
    """
    # raise NotImplementedError("TODO: implement the Day 06 pipeline")
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. Configure it in starter/.env before running."
        )

    configured_corpus = os.getenv("CORPUS_DIR")
    if configured_corpus:
        corpus_dir = _resolve_path(configured_corpus, root, root / "data")
    else:
        # Nếu starter/data có PDF thì dùng, nếu không thì fallback sang data/ ở thư mục gốc repo
        corpus_candidate = (root / "data").resolve()
        if not any(corpus_candidate.glob("*.pdf")) and (root.parent / "data").is_dir():
            corpus_dir = (root.parent / "data").resolve()
        else:
            corpus_dir = corpus_candidate
    if not corpus_dir.is_dir():
        raise FileNotFoundError(f"Corpus directory does not exist: {corpus_dir}")
        
    minimum_pages = int(os.getenv("MIN_CONTENT_PAGES", "30"))
    pages, document_report = _load_corpus(root, corpus_dir)
    if len(pages) < minimum_pages:
        raise ValueError(
            f"Only {len(pages)} non-empty selected content pages found; "
            f"the lab requires at least {minimum_pages}. Curate content_pages "
            "in manifest.json to exclude cover, contents, blank and reference-only pages."
        )

    benchmark_path = _find_benchmark(root, corpus_dir)
    questions = _load_questions(benchmark_path)
    _validate_filter_values(questions, pages)

    model_name = os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL)
    print(f"Loading embedding model: {model_name}")
    embedder = MyEmbedder(model_name)
    store = PgVectorStore(database_url, dimensions=embedder.dimensions)
    store.create_schema()

    strategy_chunks = _build_chunks(pages)
    resource_metrics: dict[str, Any] = {}

    print(
        f"Corpus: {len(document_report)} document(s), {len(pages)} content pages; "
        f"benchmark: {len(questions)} questions."
    )

    # A: fixed-size chunking.
    chunks_a = strategy_chunks["A"]
    start = time.perf_counter()
    vectors_a = embedder.embed_documents([chunk.text for chunk in chunks_a])
    embedding_seconds_a = time.perf_counter() - start
    start = time.perf_counter()
    store.upsert("A", chunks_a, vectors_a)
    ingest_seconds_a = time.perf_counter() - start
    resource_metrics["A"] = _resource_stats(
        chunks_a, embedder, embedding_seconds_a, ingest_seconds_a
    )

    # B: paragraph chunking.
    chunks_b = strategy_chunks["B"]
    start = time.perf_counter()
    vectors_b = embedder.embed_documents([chunk.text for chunk in chunks_b])
    embedding_seconds_b = time.perf_counter() - start
    start = time.perf_counter()
    store.upsert("B", chunks_b, vectors_b)
    ingest_seconds_b = time.perf_counter() - start
    resource_metrics["B"] = _resource_stats(
        chunks_b, embedder, embedding_seconds_b, ingest_seconds_b
    )

    # C: exactly the same paragraph chunks/vectors as B; only query-time filters differ.
    chunks_c = strategy_chunks["C"]
    start = time.perf_counter()
    store.upsert("C", chunks_c, vectors_b)
    ingest_seconds_c = time.perf_counter() - start
    resource_metrics["C"] = _resource_stats(
        chunks_c,
        embedder,
        0.0,
        ingest_seconds_c,
        embedding_reused_from="B",
    )

    chunk_lookup = {
        strategy: {chunk.chunk_id: chunk for chunk in chunks}
        for strategy, chunks in strategy_chunks.items()
    }

    traces: list[dict[str, Any]] = []
    query_vectors: dict[str, list[float]] = {}
    for question in questions:
        question_id = str(
            question.get("id")
            or question.get("question_id")
            or question.get("qid")
        )
        query_text = (
            question.get("question")
            or question.get("query")
            or question.get("input")
            or question.get("text")
        )
        query_vectors[question_id] = embedder.embed_query(str(query_text))

    for strategy in ("A", "B", "C"):
        for question in questions:
            question_id = str(
                question.get("id")
                or question.get("question_id")
                or question.get("qid")
            )
            split = str(
                question.get("split", question.get("set", question.get("partition")))
            ).lower()
            filters = _question_filters(question) if strategy == "C" else None

            hits = store.search(
                strategy=strategy,
                query_vector=query_vectors[question_id],
                top_k=TOP_K,
                filters=filters,
            )

            # The store's search contract returns chunk_id/text/metadata/score.
            # Restore source/page from the in-memory chunk for auditable evaluation.
            enriched_hits = []
            for hit in hits:
                chunk = chunk_lookup[strategy].get(hit["chunk_id"])
                if chunk is None:
                    raise RuntimeError(
                        f"Search returned unknown chunk_id {hit['chunk_id']!r} "
                        f"for strategy {strategy}."
                    )
                enriched_hits.append(
                    {
                        **hit,
                        "source": chunk.source,
                        "page": chunk.page,
                        "document_id": chunk.document_id,
                    }
                )

            metrics = evaluate_query(question, enriched_hits)
            traces.append(
                {
                    "strategy": strategy,
                    "question_id": metrics.get("question_id"),
                    "split": metrics.get("split"),
                    "question": metrics.get("question"),
                    "gold": {
                        "source": question.get("gold_source_id") or question.get("gold_source") or question.get("source"),
                        "page": question.get("gold_page") or question.get("page"),
                        "evidence": question.get("evidence_quote") or question.get("gold_evidence") or question.get("gold_text"),
                        "expected_answer": question.get("expected_answer"),
                    },
                    "hit_at_1": metrics.get("hit_at_1"),
                    "evidence_hit_at_3": metrics.get("evidence_hit_at_3"),
                    "matched_hit_rank": metrics.get("matched_hit_rank"),
                    "filters_applied": filters or {},
                    "hits": enriched_hits,
                }
            )

        print(f"Completed retrieval evaluation for strategy {strategy}.")

    results_dir = root / "results"
    _write_json(results_dir / "traces.json", traces)

    metrics_summary = summarize(traces)
    _write_json(results_dir / "summary.json", metrics_summary)
    _write_json(results_dir / "resource_metrics.json", resource_metrics)

    manual_template = _manual_assessment_template(
        pages, strategy_chunks, traces
    )
    _write_json(
        results_dir / "manual_assessment_template.json",
        manual_template,
    )

    run_metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "embedding_model": embedder.model_name,
        "embedding_dimensions": embedder.dimensions,
        "vector_store": "PostgreSQL + pgvector",
        "distance_metric": "cosine",
        "top_k": TOP_K,
        "corpus_directory": str(corpus_dir),
        "benchmark_path": str(benchmark_path),
        "document_report": document_report,
        "content_page_count": len(pages),
        "question_count": len(questions),
        "split_counts": {
            split: sum(
                str(q.get("split", q.get("set", q.get("partition")))).lower() == split
                for q in questions
            )
            for split in ("dev", "test")
        },
        "strategies": {
            "A": {"chunking": "fixed_size", "size": FIXED_SIZE, "overlap": FIXED_OVERLAP, "query_filter": False},
            "B": {"chunking": "by_paragraph", "max_size": PARAGRAPH_MAX_SIZE, "query_filter": False},
            "C": {"chunking": "same as B", "max_size": PARAGRAPH_MAX_SIZE, "query_filter": "only when question supplies filters"},
        },
        "human_assessment_required": [
            "chunk_coherence",
            "metadata_usefulness",
            "grounding_quality",
            "data_strategy_impact_interpretation",
        ],
        "estimated_api_cost": 0,
    }
    _write_json(results_dir / "run_metadata.json", run_metadata)

    print("\nRetrieval summary (rates are fractions; see summary.json):")
    print(json.dumps(metrics_summary, ensure_ascii=False, indent=2))
    print(f"\nResults saved to: {results_dir}")
    print("Manual review template: results/manual_assessment_template.json")

if __name__ == "__main__":
    main()
