# Security Access Control Matrix (RBAC)

This document defines the Role-Based Access Control (RBAC) policies governing all candidate and interview resources in accordance with the principle of least privilege.

The matrix below describes the intended platform policy and is broader than the endpoints implemented in this repository. The admissions-specific controls currently enforced in code are listed in Section 4; do not treat an unimplemented matrix row as an available or verified capability.

---

## 1. Access Control Matrix

| Resource / Action | Candidate | Recruiter | Hiring Manager | System Auditor |
| :--- | :---: | :---: | :---: | :---: |
| **Own Profile** | Read / Update | Read | Read | Read |
| **Other Candidate Profile** | **DENIED** | Read | Read | **DENIED** |
| **Own Resume** | Read / Update | Read | Read | **DENIED** |
| **Other Candidate Resume** | **DENIED** | Read | Read | **DENIED** |
| **Own Interview Transcript** | Read | Read | Read | **DENIED** |
| **Other Candidate Transcript** | **DENIED** | Read | Read | **DENIED** |
| **Own Identity Verification Status** | Limited (Pass/Pending) | Authorized (Full Score) | Authorized (Full Score) | Authorized |
| **Identity Reference Images / Vectors** | **DENIED** | **RESTRICTED** | **DENIED** | Audit Only |
| **Detailed Identity Logs & Alerts** | **DENIED** | Authorized | Authorized | Authorized |
| **Audio Recordings** | Read (Self-Request) | Authorized Replay | Authorized Replay | **DENIED** |
| **AI Competency Scores** | Limited Summary | Full Breakdown | Full Breakdown | Authorized |
| **AI Recommendation (Stage 5)** | **DENIED** | Read / Override | Read / Override | Authorized |
| **Recruiter Review Notes** | **DENIED** | Read / Write | Read / Write | Authorized |
| **Audit Logs (Tamper & Deletion)** | **DENIED** | **DENIED** | **DENIED** | Read-Only |
| **Trigger Candidate Deletion (GDPR)**| Own Data Only | Authorized | **DENIED** | Compliance Review |

---

## 2. Permission Levels Defined

- **Read**: Access to own submitted or generated information.
- **Limited**: Sanitized, non-sensitive summary (e.g. Identity status displays as *"Verified"* rather than exposing face embedding vectors or fraud classification matrices).
- **Authorized**: Role-based access granted to assigned recruiters and hiring managers for hiring evaluation.
- **Restricted**: Strict access controls requiring privileged role flags, logged with mandatory audit justifications.
- **DENIED**: Hard 403 Forbidden boundary enforced by API middleware and service layer.

---

## 3. Critical Access Control Invariants

1. **Candidate-to-Candidate Isolation:** A candidate authenticated as `CAND_001` can never read, modify, or infer the existence of records belonging to `CAND_002`.
2. **Identity Image Protection:** Raw face reference images are stored in isolated non-public storage partitions with zero public URL exposure.
3. **Internal Trace Concealment:** Candidates cannot view internal LLM reasoning, trigger detection phrases, or automated Stage 5 hiring recommendations before recruiter release.
4. **Audit Immutability:** Audit records and deletion logs cannot be updated or deleted by recruiters or candidates.

## 4. Admissions Flow Controls Currently Enforced

- Public `POST /auth/register` accepts candidate accounts only and rejects caller-supplied `candidate_id` values. Recruiter accounts are created by the local provisioning script; role assignment is not available to an unauthenticated browser caller.
- Candidates can submit applications and list their own applications. Application detail access checks that the authenticated candidate owns the record.
- Recruiters/admins can create programs and list applications. Program/application pages send the existing bearer token; endpoint dependencies enforce the role.
- Interview start derives the candidate, program criteria, and private face-reference path from the application ID, then checks candidate ownership.
- Live frames are required with candidate answers. Identity failures block interview progression. Face reference paths are not served from static web paths.
- The prototype does not yet implement application withdrawal/deletion, reviewer decision endpoints, application-specific enforced retention, or an automated biometric purge job. Those policy items remain unimplemented.
