# Candidate Data Inventory & Privacy Classification

This document inventories candidate data processed by the AI Hiring Intelligence Platform. Rows distinguish implemented storage/access behavior from configured retention targets: configuration values do not themselves delete data. In particular, the new application flow does not yet enforce biometric retention or provide complete applicant deletion.

---

## 1. Candidate Data Inventory Matrix

| Data Item | Purpose | Storage Location | Access Controls | Retention Period | Required? | Deletion Mechanism |
| :--- | :--- | :--- | :--- | :--- | :---: | :--- |
| **Candidate Profile** | Contact information, candidate identity, application tracking | Database (`candidates` table) | Candidate (Read own), Recruiter (Authorized), Admin | Application lifecycle (`RESUME_RETENTION_DAYS` = 180 days) | **Yes** | Database record purge + cascading file deletion |
| **Resume (Raw File & Text)** | Extract qualifications, evidence, and score competencies | Object Storage (`data/storage/resumes/{candidate_id}/`) & DB | Candidate (Read own), Recruiter (Authorized) | 180 days (`RESUME_RETENTION_DAYS`) | **Yes** | Secure file shredding + DB metadata delete |
| **Face Reference Image** | Per-application baseline for interview identity comparison | Private local storage (`data/storage/identity/{candidate_id}/{application_id}_reference.jpg`) | No public static route; used by application/interview identity services | **No purge job is currently enforced for these references**; `IDENTITY_RETENTION_DAYS` is configuration only | **Yes** for this application flow | Manual/private file deletion; automated end-to-end deletion is follow-up work |
| **Application and biometric consent** | Link student, program, resume score and identity enrollment; record consent receipt | Database (`applications` table), including face reference path, consent timestamp and version | Candidate (own application), recruiter/admin (review); API checks ownership | No application-specific automated purge is currently enforced | **Yes** for this flow | Database deletion and associated private file deletion must be coordinated; no self-service deletion endpoint yet |
| **Face Embeddings / Feature Vectors** | Mathematical vector representation for real-time verification | Identity service runtime; implementation-dependent | Identity service | No application-flow retention schedule verified | **Yes** (if identity enabled) | Runtime cleanup depends on matcher implementation; verify before deployment |
| **Identity Verification Logs** | Liveness scores, timestamped confidence, fraud alerts | Database (`identity_verifications` table) | Recruiter (Audit summary), Compliance/Admin (Full) | 90 days for audit trail | **Yes** | Scheduled compliance purge |
| **Interview Audio Recording** | Raw acoustic input for transcription and speech-to-text processing | Secure Object Storage (`data/storage/audio/{session_id}/`) | Recruiter (Authorized replay), Candidate (On request) | 30 days (`AUDIO_RETENTION_DAYS`) | **Optional** (can process ephemeral stream) | File unlinking across storage partitions |
| **Interview Transcript** | Textual candidate answers and interviewer questions | Object Storage & DB (`interview_turns` table) | Candidate (Read own), Recruiter (Authorized) | 90 days (`TRANSCRIPT_RETENTION_DAYS`) | **Yes** | Turn history purge + file removal |
| **Interview Reasoning & Traces** | Evidence detections, trigger phrases, graph decisions | Database (`decision_traces` table) | Recruiter (Audit rationale), Admin | 180 days | **Yes** | Cascade deletion with candidate |
| **Competency Scores** | Sub-scores (Evidence quality, technical depth, specificity) | Database (`competency_scores` table) | Candidate (Feedback summary), Recruiter (Authorized) | 180 days | **Yes** | Cascade deletion with candidate |
| **Final Recommendation & Notes** | Stage 5 hire/consider/reject decision & human review notes | Database (`recommendations` table) | Recruiter (Authorized), Hiring Manager, Admin | 180 days | **Yes** | Cascade deletion with candidate |

---

## 2. Logical Data Separation

To enforce least privilege, candidate data is segregated into isolated domains rather than stored in a monolithic blob:

```text
Candidate Domain Segregation
      │
      ├── 1. Profile Domain (Contact, name, email, application status)
      │
      ├── 2. Resume Domain (Raw PDF/text, extracted skills, work history)
      │
      ├── 3. Interview Domain (Turn transcripts, acoustic audio pointers, competency scores)
      │
      ├── 4. Identity Domain [RESTRICTED] (Face reference, liveness metrics, anti-fraud logs)
      │
      └── 5. Audit & Recruiter Domain (Human reviews, override justifications, GDPR deletion events)
```

### Key Security Boundary:
The **Identity Domain** is partitioned from general interview and resume data. Identity images and biometric vectors are never exposed via standard interview APIs or general candidate endpoints.

---

## 3. Storage Separation Model

Large media files and raw documents are stored in controlled object storage partitions rather than inline in relational databases:

```text
                 Application Server
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   PostgreSQL      Object Storage     Audit Logs
   (Metadata,      (Files & Media)    (Immutable,
    Scores, IDs)         │             No PII)
                         ├─ /resumes/{candidate_id}/
                         ├─ /audio/{session_id}/
                         ├─ /identity/{candidate_id}/ [Non-public]
                         └─ /transcripts/{session_id}/
```

---

## 4. Encryption Architecture

1. **In Transit:** All external and internal communication (Browser $\rightarrow$ Backend, Backend $\rightarrow$ Storage/DB) enforces TLS 1.3 / HTTPS.
2. **At Rest:**
   - Object storage volumes enforce AES-256 server-side encryption.
   - Database volumes enforce transparent data encryption (TDE) at the block layer.
   - Credentials and passwords use salted `bcrypt` hashes; JWT access tokens are signed via HMAC-SHA256 (`HS256`).
3. **No Proprietary Cryptography:** Only standard, audited libraries (`bcrypt`, `python-jose`, `cryptography`) are utilized.
