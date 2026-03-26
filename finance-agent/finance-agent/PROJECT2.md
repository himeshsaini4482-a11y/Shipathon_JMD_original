# PROJECT2.md — Employee Onboarding Automation

> **For Claude Code**: Read this entire file before writing any code. This is a NEW FEATURE added to the existing finance agent codebase. Do NOT break or rewrite existing finance functionality. Study the existing patterns in `core/`, `agents/`, `service.py`, and `ui/index.html` and follow them exactly.

---

## What We Are Adding

A second workflow called **Employee Onboarding Automation**. When a manager says something like *"Ankit Verma has been selected, start his onboarding"*, the system:

1. **Extracts employee details** from the manager's message using the LLM. If anything is missing (department, designation, start date), the agent asks follow-up questions in the chat.
2. **Provisions system accounts** (mock — inserts rows into DB for email, Slack, Jira, GitHub, etc. based on department/role).
3. **Composes a personalised welcome email** using the LLM, then shows it to the manager for review.
4. **The manager reviews the email** and either: hits **Send** (email is "sent" — logged to DB), hits **Revise** (provides feedback, LLM recomposes), or hits **Skip** (no email sent, proceed to next step).
5. **Schedules a kickoff meeting** by checking the manager's availability in `onboarding.manager_schedule`, presenting 3 free time slots for the manager to pick.
6. **Generates a personalised onboarding PDF** (reuses the existing coding agent + sandbox pipeline).
7. **Marks the onboarding as complete** in the database.

The manager interacts with this workflow through the **same chat interface** used for finance queries. The system detects onboarding intent from the message content.

---

## How It Integrates With the Existing System

### Intent Detection (the routing decision)

The existing `service.py` has a single `POST /api/query` endpoint. This stays. Add a routing layer:

```
User message arrives at /api/query
  → LLM or keyword check: is this an onboarding request or a finance query?
  → If onboarding → route to onboarding orchestrator
  → If finance → route to existing process_query() (unchanged)
```

The detection should be simple — check for keywords like "onboard", "selected", "new hire", "joining", "start onboarding" in the message. If matched, route to onboarding. No LLM call needed for routing.

### What Is NOT Changed

- `core/config.py` — unchanged (same .env, same config dataclass)
- `core/db.py` — the `ALLOWED_COLUMNS` dict gets new entries for onboarding tables, but existing entries and all functions stay unchanged
- `core/sandbox.py` — unchanged (reused for onboarding PDF generation)
- `agents/coding_agent.py` — unchanged (reused for onboarding PDF generation)
- `agents/prompts.py` — existing prompts stay unchanged, new onboarding prompts are ADDED
- `agents/finance_agent.py` — unchanged
- `core/orchestrator.py` — unchanged (the existing `process_query` function stays as-is)
- `main.py` — unchanged
- `setup.py` — gets a NEW function `setup_onboarding_tables()` added alongside the existing `validate_database()`. The existing validation logic is NOT modified.

### What Gets Added

```
agents/
├── onboarding_agent.py     ← NEW: orchestrates the onboarding pipeline
│                              (info extraction, account provisioning,
│                               email composition, calendar scheduling,
│                               doc generation, completion)

core/
├── onboarding_orchestrator.py  ← NEW: stateful pipeline coordinator
│                                  (manages the multi-step flow,
│                                   handles the human-in-the-loop email loop)

onboarding/                     ← NEW directory
├── __init__.py
├── provisioner.py              ← NEW: mock account provisioning logic
├── email_composer.py           ← NEW: LLM-powered email composition
├── calendar_scheduler.py       ← NEW: schedule lookup + slot suggestion
└── doc_generator.py            ← NEW: onboarding PDF specification builder
```

### What Gets Modified

- **`service.py`** — add new API endpoints for onboarding (see API section below)
- **`core/db.py`** — add new entries to `ALLOWED_COLUMNS` for onboarding tables
- **`core/schemas.py`** — add new Pydantic models for onboarding requests/responses
- **`setup.py`** — add `setup_onboarding_tables()` that creates the new schema + tables + mock data
- **`ui/index.html`** — the chat detects onboarding responses and renders the email review UI with Send/Revise/Skip buttons inline in the chat
- **`agents/prompts.py`** — add new prompts for onboarding (ONBOARDING_EXTRACT_PROMPT, ONBOARDING_EMAIL_PROMPT, ONBOARDING_DOC_PROMPT)

---

## Database Schema (New)

Create a new schema called `onboarding` in the same `postgres` database.

### Table: `onboarding.manager_schedule`

The manager's weekly recurring availability. Each row is a time block on a specific weekday.

```sql
CREATE SCHEMA IF NOT EXISTS onboarding;

CREATE TABLE onboarding.manager_schedule (
    schedule_id SERIAL PRIMARY KEY,
    manager_email VARCHAR(200) NOT NULL,
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),  -- 0=Monday, 6=Sunday
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    is_available BOOLEAN NOT NULL DEFAULT TRUE,  -- true=free, false=busy
    block_label VARCHAR(100),  -- e.g., "Team standup", "Lunch", "Focus time"
    CONSTRAINT valid_time_range CHECK (end_time > start_time)
);

CREATE INDEX idx_manager_schedule_email ON onboarding.manager_schedule(manager_email);
```

### Table: `onboarding.onboarding_records`

Tracks each onboarding through the pipeline.

```sql
CREATE TABLE onboarding.onboarding_records (
    onboarding_id SERIAL PRIMARY KEY,
    employee_name VARCHAR(200) NOT NULL,
    employee_email VARCHAR(200),
    department VARCHAR(100),
    designation VARCHAR(100),
    region VARCHAR(100),           -- Mumbai, Delhi, Kolkata, Bangalore, etc.
    manager_name VARCHAR(200),
    manager_email VARCHAR(200),
    buddy_name VARCHAR(200),
    buddy_email VARCHAR(200),
    start_date DATE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
        -- pending → info_collected → provisioned → email_reviewed → scheduled → doc_generated → complete
        -- can also be: failed
    current_step INTEGER NOT NULL DEFAULT 0,  -- 0=not started, 1-6=step number
    failed_at_step INTEGER,
    error_message TEXT,
    accounts_provisioned JSONB DEFAULT '[]'::jsonb,     -- [{"system": "email", "account_id": "..."}, ...]
    welcome_email_body TEXT,                             -- latest draft
    welcome_email_status VARCHAR(30) DEFAULT 'pending',  -- pending, sent, skipped
    welcome_email_sent_at TIMESTAMP,
    kickoff_meeting_time TIMESTAMP,
    kickoff_meeting_attendees JSONB DEFAULT '[]'::jsonb,
    onboarding_doc_path VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);

CREATE INDEX idx_onboarding_status ON onboarding.onboarding_records(status);
```

### Table: `onboarding.email_drafts`

Stores each revision of the welcome email for audit trail.

```sql
CREATE TABLE onboarding.email_drafts (
    draft_id SERIAL PRIMARY KEY,
    onboarding_id INTEGER REFERENCES onboarding.onboarding_records(onboarding_id),
    draft_number INTEGER NOT NULL DEFAULT 1,
    email_body TEXT NOT NULL,
    manager_feedback TEXT,          -- null for first draft, manager's revision notes for subsequent drafts
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_email_drafts_onboarding ON onboarding.email_drafts(onboarding_id);
```

### Table: `onboarding.system_accounts`

Tracks which system accounts were provisioned for each employee.

```sql
CREATE TABLE onboarding.system_accounts (
    account_id SERIAL PRIMARY KEY,
    onboarding_id INTEGER REFERENCES onboarding.onboarding_records(onboarding_id),
    system_name VARCHAR(100) NOT NULL,  -- email, slack, jira, github, erp, hubspot, figma, confluence
    account_identifier VARCHAR(200),     -- e.g., "ankit.verma@horizon.com"
    status VARCHAR(30) DEFAULT 'active', -- active, revoked
    provisioned_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_system_accounts_onboarding ON onboarding.system_accounts(onboarding_id);
```

---

## Mock Data for Testing

`setup.py` should insert this mock data into the onboarding tables:

### Manager Schedules (for 5 managers from hr.employees)

Pick 5 employees with designation "Lead", "Principal", or "Director" from `hr.employees`. For each, insert a weekly schedule with these patterns:

```
Monday:    09:00-09:30 busy (Team standup), 09:30-12:00 free, 12:00-13:00 busy (Lunch), 13:00-15:00 free, 15:00-16:00 busy (1:1s), 16:00-18:00 free
Tuesday:   09:00-12:00 free, 12:00-13:00 busy (Lunch), 13:00-18:00 free
Wednesday: 09:00-10:00 busy (All-hands), 10:00-12:00 free, 12:00-13:00 busy (Lunch), 13:00-18:00 free
Thursday:  09:00-12:00 free, 12:00-13:00 busy (Lunch), 13:00-15:00 free, 15:00-17:00 busy (Sprint review), 17:00-18:00 free
Friday:    09:00-12:00 free, 12:00-13:00 busy (Lunch), 13:00-16:00 free, 16:00-18:00 busy (Team social)
Saturday:  all busy
Sunday:    all busy
```

### Onboarding Records (15 records in various states)

- **5 completed** onboardings (status=complete, all steps done, completed_at set)
- **3 in-progress** (one at step 2 email_reviewed, one at step 3 scheduled, one at step 4 doc_generated)
- **2 failed** (one failed at step 2 with error "SMTP timeout", one failed at step 5 with error "PDF generation failed")
- **5 pending** (status=pending, current_step=0 — new hires waiting to be processed)

Use realistic Indian names across Mumbai, Delhi, Kolkata, Bangalore regions. Use departments matching the existing `hr.employees` table (engineering, data_science, design, finance_ops, hr_admin, marketing, product, sales).

### System Accounts (for completed and in-progress onboardings)

For each completed/in-progress onboarding, insert 3-6 system accounts based on department:
- **engineering**: email, slack, github, jira, confluence
- **data_science**: email, slack, github, jira, jupyter
- **design**: email, slack, figma, jira, confluence
- **marketing**: email, slack, hubspot, canva, analytics
- **sales**: email, slack, hubspot, crm, analytics
- **finance_ops**: email, slack, erp, jira
- **hr_admin**: email, slack, hrms, jira
- **product**: email, slack, jira, confluence, figma

### Email Drafts (for completed onboardings)

For each completed onboarding, insert 1-2 email drafts showing the revision history.

---

## API Endpoints (Added to service.py)

### `POST /api/query` (Modified)

The existing endpoint gets a routing check at the top. If the message matches onboarding keywords, route to the onboarding orchestrator. Otherwise, proceed with the existing `process_query()`.

The response format for onboarding steps is different from finance. It uses a new field `"type": "onboarding"` to tell the UI to render onboarding-specific components.

### `POST /api/onboarding/start`

Start a new onboarding from extracted info.

Request:
```json
{
    "employee_name": "Ankit Verma",
    "employee_email": "ankit.verma@horizon.com",
    "department": "engineering",
    "designation": "Senior Associate",
    "region": "Mumbai",
    "manager_email": "priya.mehta@horizon.com",
    "buddy_name": "Rohit Desai",
    "buddy_email": "rohit.desai@horizon.com",
    "start_date": "2026-04-15"
}
```

Response: same as `/api/query` but with `"type": "onboarding"` and step-specific data.

### `POST /api/onboarding/{onboarding_id}/email-action`

Handle the manager's decision on the welcome email.

Request:
```json
{
    "action": "send" | "revise" | "skip",
    "feedback": "Make it more casual and mention the team lunch on Friday"  // only for "revise"
}
```

Response: if "send" → returns confirmation + proceeds to calendar step. If "revise" → returns new email draft. If "skip" → proceeds to calendar step.

### `POST /api/onboarding/{onboarding_id}/select-slot`

Manager picks a meeting time slot.

Request:
```json
{
    "slot_index": 0  // index into the suggested slots array (0, 1, or 2)
}
```

Response: confirmation + proceeds to doc generation step.

### `GET /api/onboarding/dashboard`

Returns all onboarding records for the dashboard view.

Response:
```json
{
    "records": [
        {
            "onboarding_id": 1,
            "employee_name": "Ankit Verma",
            "department": "engineering",
            "status": "provisioned",
            "current_step": 2,
            "created_at": "2026-03-20T10:00:00",
            "start_date": "2026-04-15"
        }
    ],
    "stats": {
        "total": 15,
        "pending": 5,
        "in_progress": 3,
        "completed": 5,
        "failed": 2
    }
}
```

---

## Onboarding Pipeline Flow (Step by Step)

### Step 0: Intent Detection + Info Extraction

When the manager types "Ankit Verma has been selected for engineering, start his onboarding", the system:

1. Detects onboarding intent via keyword matching (no LLM needed for this)
2. Calls the LLM with `ONBOARDING_EXTRACT_PROMPT` to extract: employee_name, department, designation, region, start_date, buddy_name from the message
3. For any missing required fields (department, designation, start_date are required), the response asks the manager to provide them. The UI renders this as a normal chat message with the missing fields listed.
4. Once all required info is collected, the system looks up the manager's email from `hr.employees` (the logged-in user — for the prototype, use the first "Lead" or "Director" in the same department), generates the employee email as `firstname.lastname@horizon.com`, and creates the `onboarding_records` row with `status=pending`.

### Step 1: Account Provisioning

Based on the department, provision the appropriate system accounts. This is deterministic (no LLM needed):

```python
DEPARTMENT_SYSTEMS = {
    "engineering": ["email", "slack", "github", "jira", "confluence"],
    "data_science": ["email", "slack", "github", "jira", "jupyter"],
    "design": ["email", "slack", "figma", "jira", "confluence"],
    "marketing": ["email", "slack", "hubspot", "canva", "analytics"],
    "sales": ["email", "slack", "hubspot", "crm", "analytics"],
    "finance_ops": ["email", "slack", "erp", "jira"],
    "hr_admin": ["email", "slack", "hrms", "jira"],
    "product": ["email", "slack", "jira", "confluence", "figma"],
}
```

Insert rows into `onboarding.system_accounts`. Update `onboarding_records.status` to `provisioned`, `current_step` to 1, `accounts_provisioned` to the JSON list.

The response to the UI includes the list of provisioned accounts and immediately proceeds to email composition (Step 2).

### Step 2: Welcome Email Composition

Call the LLM with `ONBOARDING_EMAIL_PROMPT` and the employee details, provisioned accounts, manager name, buddy name, and start date. The LLM writes a warm, professional welcome email.

The response to the UI includes:
```json
{
    "type": "onboarding",
    "step": "email_review",
    "onboarding_id": 1,
    "email_draft": {
        "subject": "Welcome to Horizon, Ankit!",
        "body": "Dear Ankit,\n\nWe're thrilled to have you join..."
    },
    "draft_number": 1,
    "accounts_provisioned": ["email", "slack", "github", "jira", "confluence"]
}
```

The UI renders the email in a styled card with three buttons: **Send**, **Revise**, **Skip email**.

Save the draft to `onboarding.email_drafts`.

### Step 2b: Email Revision Loop

If the manager clicks **Revise** and provides feedback (e.g., "Make it shorter and mention the team lunch on Friday"), call the LLM again with the previous draft + the manager's feedback. Return the new draft. Save to `email_drafts` with incremented `draft_number` and the manager's feedback.

After 3 revisions, add a subtle note in the UI: "You can also type the email directly in the text box below."

If **Send**: update `welcome_email_status` to `sent`, `welcome_email_sent_at` to now. Log the email. Proceed to Step 3.

If **Skip**: update `welcome_email_status` to `skipped`. Proceed to Step 3.

### Step 3: Calendar Scheduling

Query `onboarding.manager_schedule` for the manager's email. Find the employee's `start_date`. Look for 3 free slots of at least 30 minutes on or after the start date (skip weekends, skip busy blocks).

The response includes 3 suggested slots:
```json
{
    "type": "onboarding",
    "step": "calendar_slots",
    "onboarding_id": 1,
    "slots": [
        {"index": 0, "date": "2026-04-15", "day": "Wednesday", "start": "09:30", "end": "10:00"},
        {"index": 1, "date": "2026-04-15", "day": "Wednesday", "start": "10:00", "end": "10:30"},
        {"index": 2, "date": "2026-04-15", "day": "Wednesday", "start": "13:00", "end": "13:30"}
    ]
}
```

The UI renders the 3 slots as clickable cards. The manager clicks one. The system updates `kickoff_meeting_time` and proceeds to Step 4.

### Step 4: Onboarding Document Generation

This reuses the EXISTING coding agent pipeline. The LLM writes a document specification (using `ONBOARDING_DOC_PROMPT`) with:
- Title page: "Welcome to Horizon — Onboarding Guide for [Name]"
- Employee details: name, department, designation, start date, office location
- Team info: manager name, buddy name
- Provisioned accounts: table of system name + account identifier
- First-week schedule: day-by-day plan (derived from the department — engineering gets "Day 1: setup, Day 2: codebase walkthrough, Day 3: first task")
- Key contacts: manager, buddy, HR contact, IT support
- Company policies summary: brief placeholder text

The spec is passed to the existing `coding_agent.generate()` and `sandbox.execute()` — no new code needed for the actual PDF generation.

Update `onboarding_doc_path` with the generated file path.

### Step 5: Mark Complete

Update `status` to `complete`, `completed_at` to now. The response confirms completion.

---

## LLM Prompts (Added to agents/prompts.py)

### ONBOARDING_EXTRACT_PROMPT

```
You are an HR assistant AI for Horizon. Extract employee onboarding details from the manager's message.

Output ONLY valid JSON. No markdown, no explanation.

Extract these fields (use null for anything not mentioned):
{
  "employee_name": "Full Name",
  "department": "engineering|data_science|design|finance_ops|hr_admin|marketing|product|sales",
  "designation": "Intern|Junior Associate|Associate|Senior Associate|Lead|Principal|Director",
  "region": "Mumbai|Delhi|Bangalore|Hyderabad|Chennai|Pune|Kolkata",
  "start_date": "YYYY-MM-DD",
  "buddy_name": "Full Name or null"
}

If the department is not mentioned, try to infer from context (e.g., "developer" → engineering, "designer" → design).
If designation is not mentioned, default to null.
The current date is {current_date}.
If start date is not mentioned, default to null.
```

### ONBOARDING_EMAIL_PROMPT

```
You are an HR assistant AI for Horizon. Write a professional, warm welcome email for a new employee.

The email should:
1. Welcome them by name
2. Mention their department, role, and start date
3. Introduce their manager and buddy by name
4. List the system accounts that have been provisioned for them
5. Mention the kickoff meeting will be scheduled separately
6. Be warm and enthusiastic but professional
7. Be 150-250 words long

Output ONLY the email body text (no subject line — that is generated separately). No JSON, no markdown fences.
```

### ONBOARDING_EMAIL_REVISE_PROMPT

```
You are an HR assistant AI for Horizon. The manager wants to revise the welcome email based on their feedback.

Previous email draft:
{previous_draft}

Manager's feedback:
{feedback}

Rewrite the email incorporating the manager's feedback. Keep the core information (name, department, accounts) but adjust tone, content, and structure as requested.

Output ONLY the revised email body text. No JSON, no markdown fences.
```

### ONBOARDING_DOC_PROMPT

```
You are a business analyst AI for Horizon. Create coding_instructions for a personalised onboarding PDF document.

Output ONLY valid JSON matching the existing coding_instructions schema used by the finance agent.

The document should include these sections:
1. title_page: "Welcome to Horizon — Onboarding Guide" with employee name and start date
2. paragraph: Welcome message (2-3 sentences)
3. table: Employee details (name, department, designation, region, start date, manager, buddy)
4. table: Provisioned accounts (system name, account identifier)
5. table: First-week schedule (Day 1-5, each with 2-3 activities appropriate for the department)
6. table: Key contacts (manager, buddy, HR, IT support — use placeholder emails for HR and IT)
7. paragraph: Brief company policies note

Use the same coding_instructions JSON format as the finance agent analysis output.
```

---

## UI Changes (in ui/index.html)

### Onboarding Response Rendering

When the API response has `"type": "onboarding"`, the UI renders onboarding-specific components instead of the finance result cards. Add these rendering functions:

**`renderOnboardingStep(data)`** — dispatches to step-specific renderers based on `data.step`:

- `"info_needed"` → render a message asking for missing fields
- `"provisioned"` → render a card showing provisioned accounts with checkmarks
- `"email_review"` → render the email in a styled card with **Send**, **Revise**, and **Skip email** buttons
- `"email_revised"` → same as email_review but with a note "Draft #N — revised based on your feedback"
- `"email_sent"` / `"email_skipped"` → confirmation message
- `"calendar_slots"` → render 3 clickable time slot cards
- `"slot_confirmed"` → confirmation message with meeting time
- `"doc_generated"` → render PDF preview/download (reuse existing file rendering)
- `"complete"` → success message with summary

**Email Review Card HTML Structure:**

```html
<div class="card onboarding-email-card">
    <h2>Welcome Email Draft</h2>
    <div class="email-preview">
        <div class="email-subject"><strong>Subject:</strong> Welcome to Horizon, Ankit!</div>
        <div class="email-body">{rendered email body}</div>
    </div>
    <div class="email-actions">
        <button class="btn btn-send" onclick="emailAction({onboarding_id}, 'send')">Send Email</button>
        <button class="btn btn-revise" onclick="showReviseInput({onboarding_id})">Revise</button>
        <button class="btn btn-skip" onclick="emailAction({onboarding_id}, 'skip')">Skip email</button>
    </div>
    <div class="revise-input" id="revise-input-{onboarding_id}" style="display:none">
        <textarea placeholder="What should be changed?"></textarea>
        <button onclick="submitRevision({onboarding_id})">Submit Revision</button>
    </div>
</div>
```

**Calendar Slot Cards:**

```html
<div class="card">
    <h2>Schedule Kickoff Meeting</h2>
    <p>Pick a time for the kickoff meeting with the new hire:</p>
    <div class="slot-cards">
        <div class="slot-card" onclick="selectSlot({onboarding_id}, 0)">
            <div class="slot-day">Wednesday, Apr 15</div>
            <div class="slot-time">9:30 AM — 10:00 AM</div>
        </div>
        <!-- ... 2 more slots ... -->
    </div>
</div>
```

### JavaScript Functions to Add

```javascript
async function emailAction(onboardingId, action, feedback = null) {
    const body = { action };
    if (feedback) body.feedback = feedback;
    const resp = await fetch(`/api/onboarding/${onboardingId}/email-action`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    const data = await resp.json();
    renderOnboardingStep(data);
}

function showReviseInput(onboardingId) {
    document.getElementById(`revise-input-${onboardingId}`).style.display = 'block';
}

async function submitRevision(onboardingId) {
    const textarea = document.querySelector(`#revise-input-${onboardingId} textarea`);
    const feedback = textarea.value.trim();
    if (!feedback) return;
    await emailAction(onboardingId, 'revise', feedback);
}

async function selectSlot(onboardingId, slotIndex) {
    const resp = await fetch(`/api/onboarding/${onboardingId}/select-slot`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ slot_index: slotIndex }),
    });
    const data = await resp.json();
    renderOnboardingStep(data);
}
```

---

## Whitelist Updates (core/db.py)

Add these entries to `ALLOWED_COLUMNS`:

```python
# ── onboarding schema ──
"onboarding.manager_schedule": [
    "schedule_id", "manager_email", "day_of_week", "start_time", "end_time",
    "is_available", "block_label",
],
"onboarding.onboarding_records": [
    "onboarding_id", "employee_name", "employee_email", "department",
    "designation", "region", "manager_name", "manager_email", "buddy_name",
    "buddy_email", "start_date", "status", "current_step", "failed_at_step",
    "error_message", "accounts_provisioned", "welcome_email_body",
    "welcome_email_status", "welcome_email_sent_at", "kickoff_meeting_time",
    "kickoff_meeting_attendees", "onboarding_doc_path", "created_at", "completed_at",
],
"onboarding.email_drafts": [
    "draft_id", "onboarding_id", "draft_number", "email_body",
    "manager_feedback", "created_at",
],
"onboarding.system_accounts": [
    "account_id", "onboarding_id", "system_name", "account_identifier",
    "status", "provisioned_at",
],
```

---

## setup.py Changes

Add a new function `setup_onboarding_tables()` that:

1. Connects to the same postgres database (using the same .env credentials)
2. Creates the `onboarding` schema: `CREATE SCHEMA IF NOT EXISTS onboarding;`
3. Creates all 4 tables listed above
4. Inserts the mock data (manager schedules, 15 onboarding records, system accounts, email drafts)
5. Prints a summary

Call this function from `main()` AFTER the existing `validate_database()`:

```python
def main():
    print("=" * 50)
    print("  Finance Agent — Setup & Validation")
    print("=" * 50)

    install_dependencies()
    validate_database()
    setup_onboarding_tables()  # ← NEW
    ensure_generated_dir()

    print("\n" + "=" * 50)
    print("  Setup Complete!")
    print("=" * 50)
    print("\nRun 'python main.py' to start the server.")
```

The onboarding setup should be IDEMPOTENT — use `IF NOT EXISTS` for schema and tables, and check if mock data already exists before inserting (e.g., `SELECT COUNT(*) FROM onboarding.onboarding_records` — if > 0, skip seeding).

---

## Environment

Same `.env` file as the existing project. No new environment variables needed.

```
OPENROUTER_API_KEY=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
OPENROUTER_MODEL=qwen/qwen3.5-27b
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=postgres
POSTGRES_PASSWORD=JMD333
POSTGRES_DB=postgres
```

Note: the existing project uses database name `postgres` (not `finance_agent`), as confirmed by the existing `CLAUDE.md` and `.env`.

---

## Critical Rules

1. **Do NOT break existing finance functionality.** The finance query pipeline must continue to work exactly as before. Test both workflows after making changes.
2. **Reuse existing patterns.** LLM calls should use the same `_call_llm` pattern from `agents/finance_agent.py`. PDF generation should use the same `coding_agent.generate()` + `sandbox.execute()` flow.
3. **The onboarding flow is STATEFUL.** Each step reads from and writes to `onboarding.onboarding_records`. If the server restarts mid-flow, the manager should be able to resume from where they left off by referencing the onboarding_id.
4. **Human-in-the-loop is mandatory for emails.** The agent NEVER sends an email without the manager clicking "Send". The "Send" action in the prototype logs the email to `email_drafts` with a `sent_at` timestamp — no real SMTP needed yet.
5. **Calendar slots are deterministic.** No LLM needed. Query `manager_schedule`, find free blocks ≥ 30 minutes on/after `start_date`, return the first 3. If no slots available in the first 5 business days, expand the search window.
6. **The UI stays as a single HTML file.** No build step, no React, no npm. Add new CSS and JS inline in the existing `ui/index.html`.
7. **Direct DB writes for onboarding.** Unlike the finance pipeline which only reads from DB, the onboarding pipeline WRITES to `onboarding.onboarding_records`, `onboarding.system_accounts`, and `onboarding.email_drafts`. Use `psycopg2` directly (with parameterized queries) for these writes — the existing `execute_query()` function is read-only and should stay that way. Add a new `execute_write()` or similar utility in `core/db.py` for INSERT/UPDATE operations.
8. **Keyword-based routing, not LLM-based.** Detecting whether a message is an onboarding request or a finance query should use keyword matching, not an LLM call. This keeps routing fast and free.
9. **Strip `<think>` blocks and markdown fences** from all LLM responses, same as the existing finance agent does.
10. **The email compose prompt output is PLAIN TEXT, not JSON.** Unlike finance agent prompts which return JSON, the email compose prompt returns the raw email body text. Parse accordingly.
