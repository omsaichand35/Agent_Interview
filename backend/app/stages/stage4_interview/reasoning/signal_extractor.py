import re
from typing import List, Optional


class SignalExtractor:

    TAXONOMY_MAP = {
        "leadership": [
            "led", "lead", "mentor", "mentored", "mentoring", "managed a",
            "managed engineers", "managed developers", "managed a small", "team leadership",
            "led developers", "supervised", "spearheaded", "people management",
        ],
        "system_design": [
            "architecture", "microservice", "microservices", "distributed", "scalable",
            "system design", "distributed architecture", "high availability", "architected",
        ],
        "databases": [
            "database", "databases", "sql", "postgresql", "postgres", "redis", "mongodb",
            "mysql", "relational database", "sql database", "queries", "schema",
        ],
        "cloud_devops": [
            "docker", "kubernetes", "k8s", "aws", "aws eks", "azure", "ci/cd", "deployment",
            "container orchestration", "terraform",
        ],
        "problem_solving": [
            "debugged", "bottleneck", "optimized", "problem", "issue", "solved",
            "latency", "starvation", "memory leak", "root cause",
        ],
        "backend_development": [
            "api", "apis", "rest", "fastapi", "spring boot", "spring", "django", "flask",
            "backend", "endpoints", "microservices api", "crud endpoints",
        ],
        "technical_skills": [
            "python", "java", "golang", "c++", "programming", "data structures",
        ],
        "software_engineering": [
            "testing", "pytest", "unit test", "unit testing", "integration test",
            "git", "version control", "code review", "code reviews", "clean code",
        ],
    }

    # Normalization lookup mapping specific phrases directly to canonical competency IDs
    NORMALIZATION_MAP = {
        "team leadership": "leadership",
        "led developers": "leadership",
        "mentored engineers": "leadership",
        "managed a small engineering team": "leadership",
        "mentoring": "leadership",
        "leadership": "leadership",
        "postgres": "databases",
        "postgresql": "databases",
        "relational database": "databases",
        "sql database": "databases",
        "mysql": "databases",
        "databases": "databases",
        "aws eks": "cloud_devops",
        "k8s": "cloud_devops",
        "container orchestration": "cloud_devops",
        "docker": "cloud_devops",
        "kubernetes": "cloud_devops",
        "cloud_devops": "cloud_devops",
        "pytest": "software_engineering",
        "unit testing": "software_engineering",
        "code reviews": "software_engineering",
        "software_engineering": "software_engineering",
        "api": "backend_development",
        "rest api": "backend_development",
        "fastapi": "backend_development",
        "spring boot": "backend_development",
        "backend_development": "backend_development",
        "microservices architecture": "system_design",
        "distributed systems": "system_design",
        "system_design": "system_design",
        "architected": "system_design",
        "problem_solving": "problem_solving",
        "debugging": "problem_solving",
    }

    def normalize(self, phrase: str) -> Optional[str]:
        """Normalize variations or phrases to canonical competency ID."""
        clean = " ".join(phrase.strip().lower().split())
        if clean in self.NORMALIZATION_MAP:
            return self.NORMALIZATION_MAP[clean]

        for canonical, keywords in self.TAXONOMY_MAP.items():
            for kw in keywords:
                if kw in clean or clean in kw:
                    return canonical
        return None

    def extract(
        self,
        answer: str,
        known_competencies: Optional[List[str]] = None,
    ) -> List[str]:
        signals = []
        answer_lower = answer.lower()

        for competency, keywords in self.TAXONOMY_MAP.items():
            for keyword in keywords:
                pattern = r"\b" + re.escape(keyword) + r"\b"
                if re.search(pattern, answer_lower):
                    if competency not in signals:
                        signals.append(competency)
                    break

        return signals