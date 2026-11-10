from app.schemas.candidate import Candidate
from app.schemas.job import Competency
from app.schemas.resume import (
    Evidence,
    CompetencyAssessment,
)
from app.stages.stage1_resume.competency_loader import CompetencyLoader
import re


class CompetencyMatcher:

    def match(
        self,
        candidate: Candidate,
        resume_text: str,
        competencies: list[Competency],
    ) -> list[CompetencyAssessment]:

        results = []

        for competency in competencies:

            evidence = self._find_evidence(
                competency,
                resume_text,
            )

            score = self._calculate_score(
                evidence,
                custom_criterion=competency.name not in self._keyword_map(),
                criterion_term_count=len(self._criterion_terms(competency.name)),
            )

            results.append(
                CompetencyAssessment(
                    competency=competency.name,
                    score=score,
                    evidence=evidence,
                    reasoning=self._build_reasoning(
                        competency,
                        score,
                        evidence,
                    ),
                )
            )

        return results

    def _find_evidence(
        self,
        competency: Competency,
        text: str,
    ) -> list[Evidence]:

        keyword_map = self._keyword_map()

        keywords = keyword_map.get(competency.name)
        if keywords is None:
            # Program criteria are written by departments, so support
            # criterion names that are not in the built-in job-hiring list.
            keywords = self._criterion_terms(competency.name)

        text_lower = text.lower()
        evidence = []
        for keyword in dict.fromkeys(keywords):
            position = text_lower.find(keyword.lower())
            if position < 0:
                continue
            start = max(0, position - 55)
            end = min(len(text), position + len(keyword) + 75)
            excerpt = " ".join(text[start:end].split())
            evidence.append(
                Evidence(
                    text=f"Resume excerpt: …{excerpt}…",
                    source="resume",
                    relevance=0.7,
                )
            )
        return evidence

    @staticmethod
    def _keyword_map():
        return {
            "Technical Skills": [
                "python",
                "java",
                "javascript",
                "react",
                "fastapi",
                "spring",
            ],
            "Problem Solving": [
                "optimized",
                "debugged",
                "solved",
                "improved",
                "algorithm",
            ],
            "System Design": [
                "architecture",
                "microservices",
                "distributed",
                "scalable",
                "system design",
            ],
            "Software Engineering": [
                "testing",
                "git",
                "version control",
                "ci/cd",
                "code review",
            ],
            "Databases": [
                "sql",
                "mysql",
                "postgresql",
                "mongodb",
                "redis",
                "database",
            ],
            "Cloud and DevOps": [
                "docker",
                "kubernetes",
                "aws",
                "azure",
                "deployment",
                "ci/cd",
            ],
            "Communication": [
                "presentation",
                "presented",
                "documentation",
                "communicated",
            ],
            "Leadership": [
                "led",
                "lead",
                "mentor",
                "mentored",
                "team",
            ],
            "Adaptability": [
                "learned",
                "adapted",
                "new technology",
                "new framework",
            ],
            "Project Experience": [
                "project",
                "developed",
                "built",
                "implemented",
                "created",
            ],
        }

    @staticmethod
    def _criterion_terms(name: str) -> list[str]:
        stop_words = {"and", "or", "the", "of", "in", "for", "with", "to", "a", "an", "experience", "skills"}
        return [
            token for token in re.findall(r"[a-z0-9+#.]+", name.lower())
            if token not in stop_words and len(token) > 1
        ]

    def _calculate_score(
        self,
        evidence: list[Evidence],
        custom_criterion: bool = False,
        criterion_term_count: int = 1,
    ) -> float:

        if not evidence:
            return 0.0

        denominator = max(1, criterion_term_count) if custom_criterion else 5
        return round(min(len(evidence) / denominator, 1.0), 2)

    def _build_reasoning(
        self,
        competency: Competency,
        score: float,
        evidence: list[Evidence],
    ) -> str:

        if not evidence:
            return (
                f"No direct evidence found for "
                f"{competency.name}."
            )

        return (
            f"Found {len(evidence)} evidence signal(s) "
            f"related to {competency.name}."
        )
