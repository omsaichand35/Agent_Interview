from app.stages.stage3_identity.identity_service import (
    IdentityService,
)


_identity_service = None


def get_identity_service():
    global _identity_service

    if _identity_service is None:
        from app.stages.stage3_identity.identity_logger import (
            IdentityLogger,
        )

        logger = IdentityLogger(
            output_dir="data/outputs/identity_logs"
        )

        _identity_service = IdentityService(
            logger=logger,
            log_dir="data/outputs/identity_logs",
        )

    return _identity_service


_candidate_repository = None


def get_candidate_repository():
    global _candidate_repository

    if _candidate_repository is None:
        from app.stages.stage3_identity.candidate_repository import (
            CandidateRepository,
        )

        _candidate_repository = CandidateRepository()

    return _candidate_repository


_recommendation_service = None


def get_recommendation_service():
    global _recommendation_service

    if _recommendation_service is None:
        from app.stages.stage5_recommendation.recommendation_service import (
            RecommendationService,
        )

        _recommendation_service = RecommendationService()

    return _recommendation_service


_workflow_service = None


def get_workflow_service():
    global _workflow_service

    if _workflow_service is None:
        from app.workflows.persistence import HiringWorkflowPersistence
        from app.workflows.resume import HiringWorkflowResumer
        from app.workflows.session_manager import WorkflowService

        persistence = HiringWorkflowPersistence()
        rec_service = get_recommendation_service()
        resumer = HiringWorkflowResumer(
            persistence=persistence,
            recommendation_service=rec_service,
        )
        _workflow_service = WorkflowService(
            persistence=persistence,
            resumer=resumer,
        )

    return _workflow_service


_recruiter_service = None


def get_recruiter_service():
    global _recruiter_service

    if _recruiter_service is None:
        from app.services.recruiter_service import RecruiterService
        from app.stages.stage4_interview.dependencies import registry as interview_reg

        _recruiter_service = RecruiterService(
            workflow_service=get_workflow_service(),
            recommendation_service=get_recommendation_service(),
            interview_registry=interview_reg,
        )

    return _recruiter_service
