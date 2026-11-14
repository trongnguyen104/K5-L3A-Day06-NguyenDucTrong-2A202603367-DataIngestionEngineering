"""Implement fixed-size and structure-aware chunking."""
from .models import Chunk, DocumentPage


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """TODO: split text into overlapping windows and retain page metadata."""
    # raise NotImplementedError("TODO: fixed_size")
    if size <= 0:
        raise ValueError("size must be positive")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be non-negative and smaller than size")
    text = page.text
    chunks = []
    step = size - overlap
    start = 0

    while start < len(text):
        end = min(start + size, len(text))
        chunk_text = text[start:end]
        if chunk_text.strip():
            chunk = Chunk(
                chunk_id=f"{page.document_id}_p{page.page}_fixed_{start}",
                document_id=page.document_id,
                source=page.source,
                page=page.page,
                text=chunk_text,
                metadata={
                    **page.metadata,
                    "start_char": start,
                    "end_char": end
                }
            )
            chunks.append(chunk)
        start += step
    return chunks

def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """TODO: group paragraphs, split oversized paragraphs and retain metadata."""
    # raise NotImplementedError("TODO: by_paragraph")
    if max_size <= 0:
        raise ValueError("max_size must be positive")

    paragraphs = [
        p.strip()
        for p in page.text.split("\n\n")
        if p.strip()
    ]

    chunks = []
    current_text = ""
    chunk_index = 0

    def save_chunk(text: str):
        nonlocal chunk_index

        if not text.strip():
            return

        chunk = Chunk(
            chunk_id=f"{page.document_id}_p{page.page}_paragraph_{chunk_index}",
            document_id=page.document_id,
            source=page.source,
            page=page.page,
            text=text,
            metadata={
                **page.metadata,
                "chunking_strategy": "paragraph"
            }
        )

        chunks.append(chunk)
        chunk_index += 1

    for paragraph in paragraphs:

        # Trường hợp đoạn văn vượt quá max_size
        if len(paragraph) > max_size:

            if current_text:
                save_chunk(current_text)
                current_text = ""

            # Chia đoạn văn dài thành các phần nhỏ
            for start in range(0, len(paragraph), max_size):
                part = paragraph[start:start + max_size]
                save_chunk(part)

        else:
            # Thử ghép đoạn văn vào chunk hiện tại
            candidate = (
                current_text + "\n\n" + paragraph
                if current_text
                else paragraph
            )

            if len(candidate) <= max_size:
                current_text = candidate
            else:
                save_chunk(current_text)
                current_text = paragraph

    # Lưu chunk cuối cùng
    if current_text:
        save_chunk(current_text)

    return chunks