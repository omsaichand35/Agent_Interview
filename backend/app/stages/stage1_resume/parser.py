from pathlib import Path
import pymupdf
from docx import Document


class ResumeParser:

    def parse(self, file_path: str) -> str:

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Resume not found: {file_path}"
            )

        suffix = path.suffix.lower()

        if suffix == ".pdf":
            return self._parse_pdf(path)

        if suffix == ".docx":
            return self._parse_docx(path)

        if suffix == ".txt":
            return path.read_text(encoding="utf-8")

        raise ValueError(
            f"Unsupported resume format: {suffix}"
        )

    def _parse_pdf(self, path: Path) -> str:

        document = pymupdf.open(path)

        pages = []

        for page in document:
            pages.append(page.get_text())

        document.close()

        return "\n".join(pages).strip()

    def _parse_docx(self, path: Path) -> str:

        document = Document(path)

        paragraphs = [
            paragraph.text
            for paragraph in document.paragraphs
            if paragraph.text.strip()
        ]

        return "\n".join(paragraphs).strip()


class JDParser:

    def parse(self, file_path: str) -> str:

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"Job description not found: {file_path}"
            )

        if path.suffix.lower() != ".txt":
            raise ValueError(
                "Currently only .txt JD files are supported."
            )

        return path.read_text(
            encoding="utf-8"
        ).strip()