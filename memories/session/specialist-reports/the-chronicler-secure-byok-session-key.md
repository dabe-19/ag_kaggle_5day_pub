## Full Report

### Layer: Documentation

### Files Touched
- `README.md` — Updated security architecture section to explain backend encryption and `HttpOnly` session cookie (`gemini_session_key`) storage.
- `docs/users_guide.md` — Updated the Activation & Landing Screen section, replacing browser storage references with secure cookie and boolean expiry flag details.
- `docs/kaggle_submission_writeup_final.md` — Aligned BYOK core design summary with the cookie-based session model.

### Diff Summary
- Documentation has been fully updated to correctly describe the backend-encrypted, HttpOnly session cookie architecture instead of client sessionStorage and custom headers.

### Decisions & Alternatives
- Focused edits exactly on user-visible description blocks rather than rewriting the broader threat-modeling prose, keeping explanations clear and concise.

### Risks / Follow-ups
- None.
