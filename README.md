# Sales Enablement Pro

An AI deal room that turns a sales rep's own uploaded artifacts — meeting notes,
company profiles, RFPs — into a **source-backed action plan**: a situation
summary, sequenced next steps, and a checklist of action items, where every
claim links back to the exact passage in the rep's own documents that justifies
it.

**Live app:** <https://sales-enablement-web.onrender.com>
Demo login — `demo@salesenablement.pro` / `demo12345` (comes with a seeded deal).
A second account, `rival@salesenablement.pro` / `demo12345`, sees none of it — log
in as it to confirm data stays private per user.

> **Problem.** A rep's context about a deal is scattered across notes, PDFs, and
> memory. After every customer conversation they have to re-read all of it to
> answer one question — *what do I actually do next?* — and that synthesis is
> slow, manual, and often skipped. Deals stall not because they were lost, but
> because a follow-up was missed. This app does the synthesis, and shows its
> sources so the rep can trust and verify it.

**Target user:** individual B2B sales reps working several deals at once, without
a dedicated enablement team or a well-maintained CRM.

---

## Features

- Email/password auth. Users only ever see their own data.
- Deals as the protected, user-owned resource, with full CRUD.
- Document upload (PDF / TXT / MD) with an ingestion pipeline: extract → chunk →
  embed → index.
- **RAG action plans** generated from *only that deal's* documents, with a
  citation on every step and item that resolves to the quoted source passage.
- A **weak-context gate**: when the documents cannot support a plan, the app
  refuses and says what to upload, rather than inventing one.
- Editable action items — check off, edit, delete, add your own — so the AI's
  output becomes the rep's working checklist.
- **Deck export** — turn a plan into a downloadable PowerPoint. Uses the
  Presenton API when enabled, with a built-in `python-pptx` generator as a free,
  offline fallback so the feature always works.

---

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | React 19, React Router, Vite |
| Backend | Flask, SQLAlchemy, Flask-Migrate, Flask-Login |
| Auth | Flask-Login sessions **and** signed bearer tokens (see [Auth flow](#auth-flow)) |
| Database | PostgreSQL (SQLite for local dev) |
| Vector store | Chroma (rebuilt from Postgres at startup) |
| Embeddings + generation | Google Gemini via `langchain-google-genai` |
| Deck export | Presenton hosted API, with a `python-pptx` fallback |
| Hosting | Render (API web service + static site + Postgres) |

---

## Repository layout

```
server/      Flask API — app factory, models, blueprints, RAG/deck services, tests
client/      React app — pages, auth context, API client
render.yaml  Render blueprint for both services + database
```

---

## Local setup

### Prerequisites
- Python 3.12 (not 3.14 — `chromadb` and `psycopg2` have no wheels for it yet)
- Node 18+
- A Google AI Studio API key: <https://aistudio.google.com/apikey>

### Backend

```bash
cd server
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env         # then fill in GOOGLE_API_KEY
# generate a SECRET_KEY:
python -c "import secrets; print(secrets.token_hex(32))"

flask db upgrade             # create the SQLite schema
python seed.py               # demo account + a realistic seeded deal
python wsgi.py               # serves on http://localhost:5555
```

### Frontend

```bash
cd client
npm install
npm run dev                  # serves on http://localhost:5173
```

Vite proxies `/api` to the Flask server, so in development the browser sees a
single origin. Open <http://localhost:5173>.

### Demo login

```
demo@salesenablement.pro / demo12345      (has the seeded Acme Corp deal)
rival@salesenablement.pro / demo12345     (a second account — sees none of it)
```

Sign in as the demo user, open the deal, and click **Generate action plan**. Log
in as the second account to confirm the first user's data is invisible.

---

## Required environment variables

Backend (`server/.env`):

| Variable | Required | Purpose |
|---|---|---|
| `SECRET_KEY` | yes | Signs session cookies **and** bearer tokens |
| `FLASK_ENV` | yes | `development` or `production` (controls cookie security) |
| `DATABASE_URL` | prod | Postgres URL in prod; defaults to SQLite locally |
| `FRONTEND_ORIGIN` | prod | Frontend origin allowed to send credentialed CORS requests |
| `GOOGLE_API_KEY` | yes | Gemini embeddings + generation |
| `PRESENTON_API_KEY` | no | Deck export via Presenton; omit to use the built-in generator |
| `PRESENTON_LIVE` | no | `1` to call Presenton for real; `0` (default) uses `python-pptx` |
| `RETRIEVAL_MIN_SCORE` | no | Weak-context cosine floor (default `0.60`, see below) |

Frontend: `VITE_API_URL` — the deployed API origin, baked in at build time.
Unset in dev, where the Vite proxy handles it.

Secrets are never committed. `.env` is gitignored; `.env.example` documents every
key with placeholders.

---

## API routes

All routes are under `/api`. Every route except signup, login, and health
requires authentication (a session cookie or a bearer token). Records are always
scoped to the authenticated user; touching another user's record returns 404.

**Auth**
| Method | Path | Description |
|---|---|---|
| POST | `/api/signup` | Create an account; returns the user and a bearer token |
| POST | `/api/login` | Authenticate; returns the user and a bearer token |
| DELETE | `/api/logout` | End the session |
| GET | `/api/me` | Current user — the session/token check |

**Deals** (the protected, user-owned resource)
| Method | Path | Description |
|---|---|---|
| GET | `/api/deals` | List the current user's deals |
| POST | `/api/deals` | Create a deal |
| GET | `/api/deals/:id` | Get one deal |
| PATCH | `/api/deals/:id` | Update a deal |
| DELETE | `/api/deals/:id` | Delete a deal (cascades to its documents, plans, decks) |

**Documents**
| Method | Path | Description |
|---|---|---|
| GET | `/api/deals/:id/documents` | List a deal's uploaded documents |
| POST | `/api/deals/:id/documents` | Upload a document; runs the ingestion pipeline |
| DELETE | `/api/documents/:id` | Delete a document and its chunks |

**Action plans (AI/RAG)**
| Method | Path | Description |
|---|---|---|
| POST | `/api/deals/:id/action-plans` | Generate a source-backed plan from the deal's documents |
| GET | `/api/deals/:id/action-plans` | List a deal's plans |
| GET | `/api/action-plans/:id` | Get one plan with its items and citations |
| DELETE | `/api/action-plans/:id` | Delete a plan |

**Action items**
| Method | Path | Description |
|---|---|---|
| POST | `/api/action-plans/:id/items` | Add the rep's own item to a plan |
| PATCH | `/api/action-items/:id` | Edit an item / check it off |
| DELETE | `/api/action-items/:id` | Delete an item |

**Decks**
| Method | Path | Description |
|---|---|---|
| POST | `/api/action-plans/:id/deck` | Generate a `.pptx` deck from a plan |
| GET | `/api/action-plans/:id/decks` | List a plan's decks |
| GET | `/api/decks/:id/download` | Download the `.pptx` (ownership-checked stream) |
| DELETE | `/api/decks/:id` | Delete a deck |

---

## Running the tests

```bash
cd server
python -m pytest        # 100 tests, fully offline
```

The suite runs with no network — embeddings and the LLM are stubbed, so no API
key is needed and nothing spends quota (verified with sockets blocked). It covers
auth (session **and** token), cross-user authorization (a second user is denied
on every verb), the ingestion pipeline, the RAG flow, the weak-context gate, the
generation timeout budget, deck export, and the production cookie/CORS config.

---

## How it works

### Data model

```
User ─< Deal ─< Document ─< DocumentChunk
         │                        │
         └─< ActionPlan ─< ActionItem
                   ├─< Citation >── DocumentChunk
                   └─< Deck
```

Eight models (seven beyond `User`). `Document`/`DocumentChunk` are the knowledge
base; `ActionPlan`/`ActionItem` are the persistent AI artifact; `Citation` is the
join that makes the output source-backed — it ties a generated item to the exact
chunk that produced it; `Deck` stores an exported `.pptx`. Deleting a deal
cascades to everything beneath it.

### Auth flow

Passwords are bcrypt-hashed. `POST /api/signup` and `POST /api/login` authenticate
and return both a **session cookie** and a **signed bearer token**; `GET /api/me`
checks either; `DELETE /api/logout` ends the session. Login and signup return the
same vague failure for an unknown email as for a wrong password, so neither can be
used to enumerate accounts.

**Why both a cookie and a token** (a scope change from the pitch — see
[Scope changes](#scope-changes)): the frontend and API are deployed as separate
Render services on different subdomains, and `onrender.com` is on the Public
Suffix List, so browsers treat the two as *cross-site*. A cross-site session
cookie is a third-party cookie, which modern browsers block — so the cookie alone
cannot keep a user logged in on the deployed app. The signed token (issued with
`itsdangerous`, verified by a Flask-Login `request_loader`) travels in an
`Authorization: Bearer` header, which no cookie policy blocks. The cookie still
works same-origin, which is what local development and the test suite use, so
`current_user` and `@login_required` are unchanged across every route.

**Authorization.** Every user-owned record is fetched with ownership in the
`WHERE` clause (`filter_by(id=…, user_id=current_user.id)`), never
fetched-then-checked. A record owned by someone else returns **404, not 403** — a
403 would confirm the record exists and let an attacker probe IDs.

### RAG workflow

1. **Ingest.** Extracted text is chunked (~800 chars), each chunk embedded with
   `gemini-embedding-001` (truncated to 768 dims and re-normalized), and written
   to Postgres *and* the Chroma index with `{user_id, deal_id}` metadata.
2. **Retrieve.** The query is embedded and similarity-searched in Chroma,
   filtered to this user and this deal. Retrieved chunks are re-checked against
   SQL ownership before anything reaches a prompt — one bug in a vector filter
   must not leak another rep's documents.
3. **Gate.** If nothing clears the relevance floor, the app returns
   `insufficient_context` and never calls the model.
4. **Generate.** The chunks become numbered sources in the prompt; Gemini returns
   structured JSON (summary, steps, items, and the source numbers for each). If
   the primary model is overloaded the request falls back to a second model.
   Invented citations — a source number that does not exist — are dropped.
5. **Persist.** The plan, its items, and a `Citation` per source are saved, so the
   citation a user clicks resolves to the exact passage the model was shown.

Generation runs under a hard wall-clock budget on a worker thread (see
[production notes](#production-notes-free-tier)).

### Deck export

A plan can be exported to a `.pptx`. With `PRESENTON_LIVE=1` and a key set, the
Presenton hosted API generates a designed deck; otherwise a built-in `python-pptx`
generator assembles one locally — free, offline, and always available, so a
Presenton outage or an empty credit balance never breaks the feature. Either way
the file's bytes are stored in Postgres and served through an ownership-checked
download route; Presenton's own download URL (a public, unauthenticated bucket) is
never handed to the browser.

### The relevance floor

`RETRIEVAL_MIN_SCORE` is `0.60`, calibrated against `gemini-embedding-001`, whose
vectors are not zero-centered — real deal content scores 0.62–0.68 against a
planning query while a banana bread recipe still scores ~0.51. **Lowering this
does not make the app more permissive; it disables the weak-context gate.** If the
embedding model changes, this must be re-measured.

---

## Deployment (Render)

The repo includes `render.yaml`, a Blueprint that provisions all three services.

1. Push to GitHub, then in Render: **New → Blueprint**, pointed at the repo. It
   creates the API web service, the static site, and the Postgres instance.
2. Set `GOOGLE_API_KEY` on the API service (marked `sync: false`, so it is
   prompted for, never committed). `PRESENTON_API_KEY` is optional — without it
   deck export uses the built-in generator.
3. **Seed the demo account.** Render's free tier has no shell, so run the seed
   from your machine against the production database: copy the Postgres
   *External Database URL* from the dashboard and run
   `DATABASE_URL='<that-url>' python seed.py` locally (append `?sslmode=require`
   if it complains about SSL).

**Notes from deploying this app** (things the blueprint doesn't do on its own):

- `onrender.com` subdomains are globally unique, so a taken name gets a random
  suffix (our API landed at `sales-enablement-api-axkw.onrender.com`). Because of
  that, the blueprint's cross-service `fromService` references didn't resolve, and
  `FRONTEND_ORIGIN` (on the API) and `VITE_API_URL` (on the web build) are pinned
  to literal URLs in `render.yaml` instead. Update them if a service is renamed.
- `VITE_API_URL` is baked into the frontend at build time, so changing it requires
  a **rebuild** of the static site, not just a restart.

### Production notes (free tier)

- **Cold starts.** Free web services sleep after ~15 minutes idle; the first
  request then waits ~50 seconds while the instance wakes.
- **Generation budget.** The Gemini client does not honor a client-side timeout,
  so plan generation runs on a worker thread under a 45-second wall-clock budget.
  If the model is slow (common when Gemini is under load, and slower from a
  free-tier instance), the request returns a clean *"AI service is slow, try
  again"* rather than hanging — so the service stays healthy and you retry. On a
  good attempt, generation takes ~10–20 seconds.
- **Ephemeral vector index.** Free instances cannot mount a disk, so Chroma's
  directory is wiped on every restart. This is by design: Postgres stores each
  chunk *and its embedding vector*, and the index is rebuilt from the database at
  startup. Losing the index costs a few seconds of boot time, never data.
- **Postgres expiry.** Render's free Postgres expires ~30 days after creation.

---

## Example tasks to try

- Generate a plan for the seeded Acme deal and confirm every item cites a source.
- Click a citation number to jump to the quoted passage it came from.
- Export the plan to a PowerPoint and open it.
- Create an empty deal and try to generate a plan — the app refuses and explains.
- Upload an off-topic document (a recipe) and try again — it still refuses.
- Log in as the second account and confirm the Acme deal is nowhere to be seen.

---

## Scope changes

The pitch specified session-cookie authentication, and the app still uses it —
same-origin, in local development and the test suite. But the deployed app runs
the frontend and API as two separate Render services on different subdomains,
which browsers treat as cross-site, so the session cookie is a blocked
third-party cookie in production. Rather than collapse the two into one origin,
the app **adds** signed bearer tokens for the cross-origin case (kept alongside
the cookie, not replacing it). This was a reasonable, intentional response to a
real deployment constraint, and it strengthened the auth story rather than
weakening it.

Deck export, listed as a stretch goal, is included — with a built-in `python-pptx`
fallback added so the feature does not depend on a paid, credit-metered vendor.

---

## Known limitations

- The relevance floor separates on-topic from off-topic content by a narrow
  margin (~0.03 in cosine similarity). Obviously-unrelated content is refused
  reliably, but off-topic content *near* the sales domain can slip through.
- Text-based PDFs only. Scanned/image PDFs are rejected (no OCR).
- On the free tier, a slow Gemini response returns a "try again" rather than a
  plan; generation is not guaranteed to succeed on the first attempt under load.
- Generated Presenton decks are hosted on the vendor's public bucket at an
  unlisted URL; the app proxies downloads through an ownership-checked route, but
  the underlying object is not access-controlled by the vendor. (The built-in
  generator has no such exposure.)

## Future improvements

- A semantic second gate (an explicit model judgment) to tighten weak-context
  detection.
- Move generation to a background job with polling, so it is never bounded by an
  HTTP request timeout.
- OCR for scanned documents.
- Free-form Q&A against a deal's documents, reusing the retrieval layer.
- Regenerate a plan while preserving already-completed action items.
