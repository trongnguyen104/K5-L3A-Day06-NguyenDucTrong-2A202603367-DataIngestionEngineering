"""Read and normalize source data. TODO: implement functions."""
from pathlib import Path
from .models import DocumentPage
import unicodedata
import re
from pypdf import PdfReader

def load_pdf(path: Path, document_id: str, source: str) -> list[DocumentPage]:
    """TODO: extract each physical page; keep its page number and source.

    Detect and record pages with no text. OCR, when needed, is a separate step.
    """
    # raise NotImplementedError("TODO: load_pdf")
    reader = PdfReader(str(path))

    pages = []

    for page_number, pdf_page in enumerate(reader.pages, start=1):
        # Trích xuất văn bản; nếu không có thì dùng chuỗi rỗng
        raw_text = pdf_page.extract_text() or ""

        # Chuẩn hóa văn bản
        text = normalize_text(raw_text)

        # Tạo DocumentPage kể cả khi trang không có văn bản
        document_page = DocumentPage(
            document_id=document_id,
            source=source,
            page=page_number,
            text=text,
            metadata={
                "is_empty": not bool(text)
            }
        )

        pages.append(document_page)

    return pages

def normalize_text(text: str) -> str:
    """TODO: normalize Unicode and whitespace without discarding useful structure."""
    # raise NotImplementedError("TODO: normalize_text")
    # 1. Chuẩn hóa Unicode
    text = unicodedata.normalize("NFC", text)

    # 2. Chuẩn hóa kiểu xuống dòng
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3. Xóa khoảng trắng ở đầu và cuối từng dòng
    lines = [line.strip() for line in text.split("\n")]

    # 4. Ghép lại, giữ cấu trúc xuống dòng
    text = "\n".join(lines)

    # 5. Giới hạn các dòng trống liên tiếp tối đa 2 dòng
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
    # 1. Chuẩn hóa Unicode
    text = unicodedata.normalize("NFC", text)

    # 2. Chuẩn hóa kiểu xuống dòng
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3. Xóa khoảng trắng ở đầu và cuối từng dòng
    lines = [line.strip() for line in text.split("\n")]

    # 4. Ghép lại, giữ cấu trúc xuống dòng
    text = "\n".join(lines)

    # 5. Giới hạn các dòng trống liên tiếp tối đa 2 dòng
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
