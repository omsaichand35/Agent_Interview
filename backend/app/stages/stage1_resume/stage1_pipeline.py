from pathlib import Path
from typing import Optional

from app.stages.stage1_resume.resume_service import (
    ResumeService,
    JDService,
)
from app.stages.stage1_resume.shortlist import (
    ShortlistManager,
)


class Stage1Pipeline:

    def __init__(
        self,
        competency_config: Optional[str] = None,
        use_llm: bool = False,
    ):
        self.use_llm = use_llm

        self.jd_service = JDService(
            competency_config
        )

        self.resume_service = ResumeService(
            competency_config
        )

        self.shortlist_manager = (
            ShortlistManager()
        )

    def run(
        self,
        job_id: Optional[str] = None,
        jd_path: Optional[str] = None,
        candidates: Optional[list[dict]] = None,
        resume_paths: Optional[list[str]] = None,
        shortlist_size: Optional[int] = None,
        top_n: Optional[int] = None,
        use_llm: Optional[bool] = None,
    ):
        limit = (
            top_n
            if top_n is not None
            else (shortlist_size if shortlist_size is not None else 5)
        )

        if not jd_path:
            raise ValueError("jd_path must be provided to run().")

        if not job_id:
            job_id = Path(jd_path).stem

        # -------------------------
        # 1. Load JD
        # -------------------------
        job = self.jd_service.load_job(
            job_id=job_id,
            jd_path=jd_path,
        )

        if candidates is None:
            if resume_paths is not None:
                candidates = [
                    {
                        "candidate_id": f"C{i+1:03d}",
                        "resume_path": p,
                    }
                    for i, p in enumerate(resume_paths)
                ]
            else:
                raise ValueError(
                    "Either candidates or resume_paths must be provided to run()."
                )

        should_use_llm = (
            use_llm
            if use_llm is not None
            else self.use_llm
        )

        results = []

        # -------------------------
        # 2. Evaluate candidates
        # -------------------------
        for candidate_data in candidates:
            cid = candidate_data["candidate_id"]
            rpath = candidate_data["resume_path"]

            if should_use_llm:
                result = self.resume_service.evaluate(
                    resume_path=rpath,
                    job=job,
                    candidate_id=cid,
                )
            else:
                result = self.resume_service.evaluate_resume(
                    candidate_id=cid,
                    resume_path=rpath,
                    job=job,
                )

            results.append(result)

        # -------------------------
        # 3. Rank candidates
        # -------------------------
        scores = [
            result["resume_score"]
            for result in results
        ]

        shortlist = self.shortlist_manager.rank(
            scores,
            limit=limit,
        )

        return {
            "job": job,
            "candidates": results,
            "shortlist": shortlist,
        }