from pathlib import Path
from typing import Optional

from app.schemas.job import JobDescription
from app.stages.stage1_resume.parser import (
    ResumeParser,
    JDParser,
)
from app.stages.stage1_resume.extractor import (
    ResumeExtractor,
    JDExtractor,
)
from app.stages.stage1_resume.competency_matcher import (
    CompetencyMatcher,
)
from app.stages.stage1_resume.competency_loader import (
    CompetencyLoader,
)
from app.stages.stage1_resume.scorer import (
    ResumeScorer,
)


from app.llm.provider import get_llm_client
from app.stages.stage1_resume.llm_analyzer import LLMResumeAnalyzer
from app.stages.stage1_resume.llm_score_adapter import LLMScoreAdapter


class ResumeService:

    def __init__(
        self,
        competency_config: Optional[str] = None,
    ):
        if competency_config is None:
            default_config = (
                Path(__file__).resolve().parents[4]
                / "config"
                / "competencies.yaml"
            )
            competency_config = str(default_config)

        self.parser = ResumeParser()
        self.extractor = ResumeExtractor()
        self.competency_loader = (
            CompetencyLoader(
                competency_config
            )
        )
        self.matcher = CompetencyMatcher()
        self.scorer = ResumeScorer()

        try:
            self.llm_analyzer = LLMResumeAnalyzer(
                get_llm_client()
            )
        except Exception:
            self.llm_analyzer = None

    def evaluate_resume(
        self,
        candidate_id: str,
        resume_path: str,
        job: Optional[JobDescription] = None,
    ):
        # 1. Parse resume
        resume_text = self.parser.parse(
            resume_path
        )

        # 2. Extract candidate
        candidate = self.extractor.extract(
            candidate_id=candidate_id,
            text=resume_text,
        )

        # 3. Determine competencies
        competencies = (
            job.competencies
            if job is not None
            else self.competency_loader.load()
        )

        # 4. Match against competencies
        assessments = self.matcher.match(
            candidate=candidate,
            resume_text=resume_text,
            competencies=competencies,
        )

        # 5. Score
        score = self.scorer.score(
            candidate_id=candidate_id,
            assessments=assessments,
            competencies=competencies,
        )

        return {
            "candidate": candidate,
            "resume_score": score,
        }

    def evaluate(
        self,
        resume_path: str,
        job: JobDescription,
        candidate_id: str,
    ):
        resume_text = self.parser.parse(resume_path)

        candidate = self.extractor.extract(
            candidate_id=candidate_id,
            text=resume_text,
        )

        if self.llm_analyzer is not None:
            analysis = self.llm_analyzer.analyze(
                resume_text=resume_text,
                job=job,
            )

            resume_score = LLMScoreAdapter.convert(
                analysis=analysis,
                candidate_id=candidate.candidate_id,
                competencies=job.competencies,
            )
        else:
            assessments = self.matcher.match(
                candidate=candidate,
                resume_text=resume_text,
                competencies=job.competencies,
            )

            resume_score = self.scorer.score(
                candidate_id=candidate.candidate_id,
                assessments=assessments,
                competencies=job.competencies,
            )

        candidate.resume_score = resume_score.overall_score

        return {
            "candidate": candidate,
            "resume_score": resume_score,
        }

    def run(
        self,
        job_description,
        candidates,
        limit: int = 5,
        **kwargs,
    ):
        # 1. Resolve job_description
        job = None
        if isinstance(job_description, JobDescription):
            job = job_description
        elif isinstance(job_description, str):
            jd_path = Path(job_description)
            if jd_path.exists():
                jd_service = JDService()
                job = jd_service.load_job(job_id=jd_path.stem, jd_path=str(jd_path))
            else:
                competencies = self.competency_loader.load()
                job = JDExtractor().extract(
                    job_id=kwargs.get("job_id") or "",
                    text=job_description,
                    competencies=competencies,
                )
        elif isinstance(job_description, dict):
            if "competencies" in job_description and isinstance(
                job_description["competencies"], list
            ):
                try:
                    job = JobDescription(**job_description)
                except Exception:
                    pass
            if job is None:
                competencies = self.competency_loader.load()
                job = JDExtractor().extract(
                    job_id=job_description.get(
                        "job_id", kwargs.get("job_id") or ""
                    ),
                    text=job_description.get("text", str(job_description)),
                    competencies=competencies,
                )

        # 2. Evaluate candidates internally
        evaluated = []
        for cand in candidates:
            if isinstance(cand, dict):
                cid = cand.get("candidate_id")
                rpath = cand.get("resume_path")
                rtext = cand.get("resume_text")
                cand_data = dict(cand)
            else:
                cid = getattr(cand, "candidate_id", None)
                rpath = getattr(cand, "resume_path", None)
                rtext = getattr(cand, "resume_text", None)
                cand_data = (
                    cand.__dict__.copy()
                    if hasattr(cand, "__dict__")
                    else {"candidate_id": cid}
                )

            if rpath:
                if not cid:
                    raise ValueError("Each candidate requires a candidate_id")
                result = self.evaluate_resume(
                    candidate_id=cid,
                    resume_path=str(rpath),
                    job=job,
                )
                score_val = (
                    result["resume_score"].overall_score
                    if hasattr(result["resume_score"], "overall_score")
                    else float(result["resume_score"])
                )
                cand_data["resume_score"] = score_val
                cand_data["score"] = score_val
                if hasattr(result.get("candidate"), "skills"):
                    cand_data.setdefault("skills", result["candidate"].skills)
                if hasattr(result.get("candidate"), "name"):
                    cand_data.setdefault("name", result["candidate"].name)
                evaluated.append(cand_data)
            elif rtext:
                if not cid:
                    raise ValueError("Each candidate requires a candidate_id")
                cand_obj = self.extractor.extract(candidate_id=cid, text=rtext)
                comps = (
                    job.competencies
                    if job is not None
                    else self.competency_loader.load()
                )
                assessments = self.matcher.match(
                    candidate=cand_obj,
                    resume_text=rtext,
                    competencies=comps,
                )
                score_obj = self.scorer.score(
                    candidate_id=cid,
                    assessments=assessments,
                    competencies=comps,
                )
                cand_data["resume_score"] = score_obj.overall_score
                cand_data["score"] = score_obj.overall_score
                cand_data.setdefault("skills", cand_obj.skills)
                cand_data.setdefault("name", cand_obj.name)
                evaluated.append(cand_data)
            else:
                score_val = float(
                    cand_data.get("resume_score")
                    or cand_data.get("score")
                    or 0.0
                )
                cand_data["resume_score"] = score_val
                cand_data["score"] = score_val
                evaluated.append(cand_data)

        # 3. Sort & Shortlist
        ranked = sorted(
            evaluated,
            key=lambda c: c.get("resume_score", 0.0),
            reverse=True,
        )
        shortlist = ranked[:limit]

        return {
            "shortlist": shortlist,
        }


class JDService:

    def __init__(
        self,
        competency_config: Optional[str] = None,
    ):
        if competency_config is None:
            default_config = (
                Path(__file__).resolve().parents[4]
                / "config"
                / "competencies.yaml"
            )
            competency_config = str(default_config)

        self.parser = JDParser()

        self.extractor = JDExtractor()

        self.competency_loader = (
            CompetencyLoader(
                competency_config
            )
        )

    def load_job(
        self,
        *args,
        job_id: Optional[str] = None,
        jd_path: Optional[str] = None,
    ):
        if args:
            if len(args) == 1:
                if job_id is not None:
                    jd_path = args[0]
                else:
                    job_id = args[0]
            elif len(args) >= 2:
                # If first arg ends with .txt or exists as path, it might be jd_path
                arg0 = str(args[0])
                if arg0.endswith(".txt") or "/" in arg0 or "\\" in arg0:
                    jd_path = args[0]
                    job_id = args[1]
                else:
                    job_id = args[0]
                    jd_path = args[1]

        if not jd_path or not job_id:
            raise ValueError("Both job_id and jd_path must be provided to load_job.")

        text = self.parser.parse(
            jd_path
        )

        competencies = (
            self.competency_loader.load()
        )

        job = self.extractor.extract(
            job_id=job_id,
            text=text,
            competencies=competencies,
        )

        return job
