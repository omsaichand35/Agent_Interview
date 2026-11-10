from pathlib import Path
from typing import Optional, List, Dict, Any

from app.workflows.persistence import HiringWorkflowPersistence
from app.workflows.resume import HiringWorkflowResumer


class Shortlist(list):
    """Custom list enabling both `candidate_id in shortlist` and object membership."""
    def __contains__(self, item):
        if super().__contains__(item):
            return True
        for cand in self:
            if isinstance(cand, dict) and cand.get("candidate_id") == item:
                return True
            if hasattr(cand, "candidate_id") and getattr(cand, "candidate_id") == item:
                return True
        return False


class RecommendationsList(list):
    """Custom list enabling both `candidate_id in recommendations` and dict membership."""
    def __contains__(self, item):
        if super().__contains__(item):
            return True
        for rec in self:
            if isinstance(rec, dict) and rec.get("candidate_id") == item:
                return True
            if hasattr(rec, "candidate_id") and getattr(rec, "candidate_id") == item:
                return True
        return False


class HumanReviewList(list):
    """Custom list enabling both `candidate_id in human_review` and dict membership."""
    def __contains__(self, item):
        if super().__contains__(item):
            return True
        for rev in self:
            if isinstance(rev, dict) and rev.get("candidate_id") == item:
                return True
            if hasattr(rev, "candidate_id") and getattr(rev, "candidate_id") == item:
                return True
        return False


class WorkflowState(dict):
    """Workflow state dictionary with attribute-style access for status, shortlist, etc."""
    def __getattr__(self, name):
        try:
            val = self[name]
            if name == "shortlist" and isinstance(val, list) and not isinstance(val, Shortlist):
                val = Shortlist(val)
                self[name] = val
            elif name == "recommendations" and isinstance(val, list) and not isinstance(val, RecommendationsList):
                val = RecommendationsList(val)
                self[name] = val
            elif name == "human_review" and isinstance(val, list) and not isinstance(val, HumanReviewList):
                val = HumanReviewList(val)
                self[name] = val
            return val
        except KeyError:
            raise AttributeError(f"'WorkflowState' has no attribute '{name}'")

    def __setattr__(self, name, value):
        self[name] = value

    @property
    def shortlist(self):
        val = self.get("shortlist", [])
        if not isinstance(val, Shortlist):
            val = Shortlist(val)
            self["shortlist"] = val
        return val

    @shortlist.setter
    def shortlist(self, value):
        self["shortlist"] = Shortlist(value)

    @property
    def recommendations(self):
        val = self.get("recommendations", [])
        if not isinstance(val, RecommendationsList):
            val = RecommendationsList(val)
            self["recommendations"] = val
        return val

    @recommendations.setter
    def recommendations(self, value):
        self["recommendations"] = RecommendationsList(value)

    @property
    def human_review(self):
        val = self.get("human_review", [])
        if not isinstance(val, HumanReviewList):
            val = HumanReviewList(val)
            self["human_review"] = val
        return val

    @human_review.setter
    def human_review(self, value):
        self["human_review"] = HumanReviewList(value)

    @property
    def interview_sessions(self):
        return self.get("interview_sessions", {})

    @property
    def current_candidate_id(self):
        return self.get("current_candidate_id")

    @current_candidate_id.setter
    def current_candidate_id(self, value):
        self["current_candidate_id"] = value

    @property
    def status(self):
        return self.get("status")

    @status.setter
    def status(self, value):
        self["status"] = value


class HiringWorkflowSessionManager:

    def __init__(
        self,
        persistence: Optional[HiringWorkflowPersistence] = None,
        resumer: Optional[HiringWorkflowResumer] = None,
    ):
        self.persistence = persistence or HiringWorkflowPersistence()
        self.resumer = resumer or HiringWorkflowResumer(persistence=self.persistence)
        # Give the resumer a back-reference so resume() can call
        # run_shortlisting / run_scheduling without circular imports.
        if hasattr(self.resumer, "workflow_session_manager"):
            self.resumer.workflow_session_manager = self

    def create(
        self,
        job_id: str,
        candidate_ids: Optional[List[str]] = None,
        job_description: Optional[dict] = None,
        candidates: Optional[List[dict]] = None,
        title: str = "",
        department: str = "",
    ) -> WorkflowState:
        if candidate_ids is not None:
            c_ids = candidate_ids
        elif candidates:
            c_ids = [c.get("candidate_id") for c in candidates if isinstance(c, dict) and "candidate_id" in c]
        else:
            c_ids = []
        c_list = candidates or []
        state = WorkflowState({
            "job_id": job_id,
            "job_title": title,
            "department": department,
            "job_description": job_description or {"title": title, "department": department},
            "status": "CREATED",
            "candidate_ids": c_ids,
            "candidates": c_list,
            "shortlist": Shortlist(),
            "schedules": [],
            "current_candidate_id": None,
            "identity_results": {},
            "interview_sessions": {},
            "interview_results": {},
            "recommendations": RecommendationsList(),
            "human_review": [],
        })
        self.persistence.save(state)
        return state

    def run_shortlisting(self, workflow, resume_service=None) -> WorkflowState:
        wf = WorkflowState(workflow) if not isinstance(workflow, WorkflowState) else workflow
        candidates = wf.get("candidates", [])
        if resume_service and hasattr(resume_service, "run"):
            res = resume_service.run(
                job_description=wf.get("job_description", {}),
                candidates=candidates,
            )
            items = res.get("shortlist", candidates)
        else:
            items = [c for c in candidates if (c.get("resume_score") or 0) >= 70.0] or candidates

        shortlist = Shortlist([c["candidate_id"] if isinstance(c, dict) else c for c in items])
        wf["shortlist"] = shortlist
        wf["status"] = "SHORTLISTED"
        self.persistence.save(wf)
        return wf

    def run_scheduling(self, workflow, scheduling_service=None) -> WorkflowState:
        wf = WorkflowState(workflow) if not isinstance(workflow, WorkflowState) else workflow
        shortlist = wf.get("shortlist", [])
        if scheduling_service is None:
            from app.stages.stage2_scheduling.scheduling_service import SchedulingService
            scheduling_service = SchedulingService()
        res = scheduling_service.schedule(shortlist=shortlist)
        schedules = res.get("schedules", [])
        wf["schedules"] = schedules
        wf["status"] = "SCHEDULED" if schedules else "SHORTLISTED"
        self.persistence.save(wf)
        return wf

    def prepare_interview(self, workflow, candidate_id: str) -> WorkflowState:
        wf = WorkflowState(workflow) if not isinstance(workflow, WorkflowState) else workflow
        wf["current_candidate_id"] = candidate_id
        wf["status"] = "IDENTITY_CHECK"
        self.persistence.save(wf)
        return wf

    def identity_passed(self, workflow, candidate_id: str, identity_result) -> WorkflowState:
        wf = WorkflowState(workflow) if not isinstance(workflow, WorkflowState) else workflow
        dumped = identity_result.model_dump() if hasattr(identity_result, "model_dump") else identity_result
        wf["identity_results"][candidate_id] = dumped
        wf["status"] = "INTERVIEW_READY"
        self.persistence.save(wf)
        return wf

    def identity_failed(self, workflow, candidate_id: str, identity_result) -> WorkflowState:
        wf = WorkflowState(workflow) if not isinstance(workflow, WorkflowState) else workflow
        dumped = identity_result.model_dump() if hasattr(identity_result, "model_dump") else identity_result
        wf["identity_results"][candidate_id] = dumped
        reason = dumped.get("failure_reason") or dumped.get("reason") or "Face mismatch"
        wf["human_review"].append({
            "candidate_id": candidate_id,
            "reason": reason,
            "identity_result": dumped,
        })
        wf["status"] = "HUMAN_REVIEW"
        self.persistence.save(wf)
        return wf

    def interview_completed(self, workflow, candidate_id: str, interview_result) -> WorkflowState:
        wf = WorkflowState(workflow) if not isinstance(workflow, WorkflowState) else workflow
        dumped = interview_result.model_dump() if hasattr(interview_result, "model_dump") else interview_result
        wf["interview_results"][candidate_id] = dumped
        wf["status"] = "INTERVIEW_COMPLETED"
        self.persistence.save(wf)
        return wf

    def generate_recommendation(self, workflow, candidate_id: str) -> WorkflowState:
        wf = WorkflowState(workflow) if not isinstance(workflow, WorkflowState) else workflow
        candidates = wf.get("candidates", [])
        candidate = next((c for c in candidates if c["candidate_id"] == candidate_id), None)
        if candidate is None:
            raise ValueError(f"Candidate {candidate_id} is not part of workflow {wf.get('job_id')}")
        interview_res = wf["interview_results"].get(candidate_id, {})
        identity_res = wf["identity_results"].get(candidate_id, {})

        rec = self.resumer.recommendation_service.generate(
            candidate=candidate,
            interview_result=interview_res,
            identity_result=identity_res,
        )
        dumped = rec.model_dump() if hasattr(rec, "model_dump") else rec
        wf.recommendations.append(dumped)
        wf["status"] = "RECOMMENDATION_READY"
        self.persistence.save(wf)
        return wf

    def get(self, job_id: str) -> "Optional[WorkflowState]":
        state = self.persistence.load(job_id)
        if state is not None:
            return WorkflowState(state)
        return None

    get_session = get

    def list_jobs(self) -> List[dict]:
        jobs = []
        if self.persistence.output_dir.exists():
            for f in self.persistence.output_dir.glob("*_workflow.json"):
                try:
                    job_id = f.name.replace("_workflow.json", "")
                    job_state = self.persistence.load(job_id)
                    jobs.append(job_state)
                except Exception:
                    continue
        return jobs

    def create_job(
        self,
        job_id: str,
        title: str = "",
        department: str = "",
        candidates: Optional[List[dict]] = None,
    ) -> dict:
        candidate_list = candidates or []
        shortlist = [c for c in candidate_list if (c.get("resume_score") or 0) >= 70.0]
        state = WorkflowState({
            "job_id": job_id,
            "job_title": title,
            "department": department,
            "status": "SHORTLISTED" if shortlist else "CREATED",
            "candidate_ids": [c["candidate_id"] for c in candidate_list],
            "candidates": candidate_list,
            "shortlist": Shortlist(shortlist),
            "schedules": [],
            "current_candidate_id": shortlist[0]["candidate_id"] if shortlist else None,
            "identity_results": {},
            "interview_sessions": {},
            "interview_results": {},
            "recommendations": RecommendationsList(),
            "human_review": [],
        })
        self.persistence.save(state)
        return state

    def resume_interview(
        self,
        job_id: str,
        interview_result: dict,
    ):
        state = self.persistence.load(job_id)
        if state is None:
            state = self.get(job_id)
            if state is None:
                raise FileNotFoundError(f"Workflow not found: {job_id}")

        result = self.resumer.resume_after_interview(
            state,
            interview_result,
        )

        return result

    # Aliases for flexible integration
    resume = resume_interview
    resume_after_interview = resume_interview

    def resume_from_status(self, job_id: str) -> WorkflowState:
        """Delegate to resumer.resume() for status-based dispatch."""
        result = self.resumer.resume(job_id)
        return WorkflowState(result) if isinstance(result, dict) else result


WorkflowSessionManager = HiringWorkflowSessionManager
WorkflowService = HiringWorkflowSessionManager
