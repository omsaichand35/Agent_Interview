"""
Application-level standard exceptions for consistent API error responses.
"""

from typing import Any, Optional


class AppException(Exception):
    """
    Base application exception for standardized API error handling.
    All application exceptions carry a machine-readable code, an HTTP status_code,
    and a human-readable message.
    """

    def __init__(
        self,
        message: str = "An error occurred",
        code: str = "APP_ERROR",
        status_code: int = 400,
        details: Optional[Any] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details


class InvalidRequestException(AppException):
    def __init__(self, message: str = "Invalid request", details: Optional[Any] = None):
        super().__init__(
            message=message,
            code="INVALID_REQUEST",
            status_code=400,
            details=details,
        )


class CandidateNotFound(AppException):
    def __init__(self, candidate_id: Optional[str] = None, message: str = "Candidate not found"):
        msg = f"Candidate '{candidate_id}' not found" if candidate_id else message
        super().__init__(
            message=msg,
            code="CANDIDATE_NOT_FOUND",
            status_code=404,
        )


class InterviewNotFound(AppException):
    def __init__(self, session_id: Optional[str] = None, message: str = "Interview session not found"):
        msg = f"Interview session '{session_id}' not found" if session_id else message
        super().__init__(
            message=msg,
            code="INTERVIEW_NOT_FOUND",
            status_code=404,
        )


class WorkflowNotFound(AppException):
    def __init__(self, job_id: Optional[str] = None, message: str = "Workflow not found"):
        msg = f"Workflow '{job_id}' not found" if job_id else message
        super().__init__(
            message=msg,
            code="WORKFLOW_NOT_FOUND",
            status_code=404,
        )


class JobNotFound(AppException):
    def __init__(self, job_id: Optional[str] = None, message: str = "Job not found"):
        msg = f"Job '{job_id}' not found" if job_id else message
        super().__init__(
            message=msg,
            code="JOB_NOT_FOUND",
            status_code=404,
        )


class IdentityVerificationFailed(AppException):
    def __init__(self, message: str = "Identity verification failed", reason: Optional[str] = None):
        msg = f"{message}: {reason}" if reason else message
        super().__init__(
            message=msg,
            code="IDENTITY_VERIFICATION_FAILED",
            status_code=422,
        )


class DuplicateScheduleException(AppException):
    def __init__(self, message: str = "Duplicate schedule: candidate or slot is already scheduled"):
        super().__init__(
            message=message,
            code="DUPLICATE_SCHEDULE",
            status_code=409,
        )


class InvalidUploadException(AppException):
    def __init__(
        self,
        message: str = "Invalid upload",
        details: Optional[Any] = None,
        code: str = "INVALID_UPLOAD",
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=422,
            details=details,
        )


class InvalidResumeException(InvalidUploadException):
    def __init__(self, message: str = "Invalid resume PDF", details: Optional[Any] = None, code: str = "INVALID_UPLOAD"):
        super().__init__(message=message, details=details, code=code)


class InvalidImageException(InvalidUploadException):
    def __init__(self, message: str = "Invalid image", details: Optional[Any] = None, code: str = "INVALID_UPLOAD"):
        super().__init__(message=message, details=details, code=code)


class InvalidAudioException(InvalidUploadException):
    def __init__(self, message: str = "Invalid audio", details: Optional[Any] = None, code: str = "INVALID_UPLOAD"):
        super().__init__(message=message, details=details, code=code)




class ServiceUnavailableException(AppException):
    def __init__(self, message: str = "Service unavailable", code: str = "SERVICE_UNAVAILABLE"):
        super().__init__(
            message=message,
            code=code,
            status_code=503,
        )


class LLMUnavailableException(ServiceUnavailableException):
    def __init__(self, message: str = "LLM service is currently unavailable"):
        super().__init__(
            message=message,
            code="LLM_UNAVAILABLE",
        )


class STTUnavailableException(ServiceUnavailableException):
    def __init__(self, message: str = "STT speech recognition service is currently unavailable"):
        super().__init__(
            message=message,
            code="STT_UNAVAILABLE",
        )


class UnauthorizedException(AppException):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            message=message,
            code="UNAUTHORIZED",
            status_code=401,
        )


class ForbiddenException(AppException):
    def __init__(self, message: str = "Forbidden: Access denied"):
        super().__init__(
            message=message,
            code="FORBIDDEN",
            status_code=403,
        )
