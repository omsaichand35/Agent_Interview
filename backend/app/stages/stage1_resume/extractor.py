import re

from app.schemas.candidate import (
    Candidate,
    Experience,
    Education,
)
from app.schemas.job import (
    JobDescription,
    Competency,
)


class ResumeExtractor:

    def extract(
        self,
        candidate_id: str,
        text: str,
    ) -> Candidate:

        name = self._extract_name(text)

        email = self._extract_email(text)

        skills = self._extract_skills(text)

        return Candidate(
            candidate_id=candidate_id,
            name=name,
            email=email,
            skills=skills,
        )

    def _extract_name(self, text: str) -> str:

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        if not lines:
            return "Unknown Candidate"

        return lines[0]

    def _extract_email(self, text: str) -> str:

        pattern = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"

        match = re.search(pattern, text)

        if match:
            return match.group(0)

        return ""

    def _extract_skills(self, text: str) -> list[str]:

        known_skills = [
            "python",
            "java",
            "javascript",
            "typescript",
            "react",
            "fastapi",
            "spring",
            "sql",
            "mysql",
            "postgresql",
            "mongodb",
            "redis",
            "docker",
            "kubernetes",
            "aws",
            "azure",
            "git",
            "linux",
            "kafka",
            "tensorflow",
            "pytorch",
            "langchain",
            "langgraph",
        ]

        text_lower = text.lower()

        return [
            skill
            for skill in known_skills
            if skill in text_lower
        ]

class JDExtractor:

    def extract(
        self,
        job_id: str,
        text: str,
        competencies: list[Competency],
    ) -> JobDescription:

        title = self._extract_title(text)

        return JobDescription(
            job_id=job_id,
            title=title,
            description=text,
            competencies=competencies,
        )

    def _extract_title(
        self,
        text: str,
    ) -> str:

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        if not lines:
            return "Unknown Position"

        return lines[0]