# Sales Enablement Pro

An AI deal room that turns a sales rep's own uploaded artifacts — meeting notes,
company profiles, RFPs — into a **source-backed action plan**: a situation
summary, sequenced next steps, and a checklist of action items, where every
claim links back to the exact passage in the rep's own documents that justifies
it.

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

- Email/password auth with sessions; users only ever see their own data.
- Deals as the protected, user-owned resource, with full CRUD.
- Document upload (PDF / TXT / MD) with an ingestion pipeline: extract → chunk →
  embed → index.
- **RAG action plans** generated from *only that deal's* documents, with a
  citation on every step and item.
- A **weak-context gate**: when the documents cannot support a plan, the app
  refuses and says what to upload, rather than inventing one.
- Editable action items — check off, edit, delete, add your own — so the AI's
  output becomes the rep's working checklist.
- Deck export via the Presenton API (stretch feature).

---

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | React 19, React Router, Vite |
| Backend | Flask, SQLAlchemy, Flask-Migrate, Flask-Login |
| Database | PostgreSQL (SQLite for local dev) |
| Vector store | Chroma (rebuilt from Postgres at startup) |
| Embeddings + generation | Google Gemini via `langchain-google-genai` |
| Deck export | Presenton hosted API |
| Hosting | Render (API + static site + Postgres) |

---

## Repository layout

```
server/    Flask API — app factory, models, blueprints, RAG services, tests
client/    React app — pages, auth context, API client
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

Vite proxies `/api` to the Flask server, so the browser sees one origin in
development and the session cookie is same-site. Open <http://localhost:5173>.

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

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session signing key |
| `FLASK_ENV` | `development` or `production` (controls cookie security) |
| `DATABASE_URL` | Postgres URL in prod; defaults to SQLite locally |
| `FRONTEND_ORIGIN` | React origin allowed to send credentialed requests |
| `GOOGLE_API_KEY` | Gemini embeddings + generation |
| `PRESENTON_API_KEY` | Deck export (stretch feature) |
| `PRESENTON_LIVE` | `1` to call Presenton for real; `0` to stub it |
| `RETRIEVAL_MIN_SCORE` | Weak-context cosine floor (see below) |

Frontend: `VITE_API_URL` — the deployed API origin (unset in dev; the proxy
handles it).

Secrets are never committed. `.env` is gitignored; `.env.example` documents
every key with placeholders.

---

## Running the tests

```bash
cd server
python -m pytest
```

The suite runs fully offline — embeddings and the LLM are stubbed, so no API key
or network is needed and nothing spends quota. It covers auth, cross-user
authorization (a second user is denied on every verb), the ingestion pipeline,
the RAG flow, the weak-context gate, and the production cookie/CORS config.

---

## Deployment (Render)

The repo includes `render.yaml`, a Blueprint that provisions all three pieces.

1. Push to GitHub.
2. In Render: **New → Blueprint**, pointed at the repo. It creates the API web
   service, the static site, and the Postgres instance.
3. Set the two secret env vars on the API service (marked `sync: false` in the
   blueprint, so they are prompted for, never committed):
   - `GOOGLE_API_KEY`
   - `PRESENTON_API_KEY`
4. The API runs `flask db upgrade` on start. To seed the demo account, run
   `python seed.py` once from the service shell (or a one-off job).

`FRONTEND_ORIGIN` and `VITE_API_URL` are wired between the two services
automatically by the blueprint.

### Production limitations (free tier)

- **Cold starts.** Free web services sleep after ~15 minutes idle; the first
  request then waits ~50 seconds while the instance wakes. A reviewer opening a
  cold URL should give it a moment.
- **Ephemeral vector index.** Free instances cannot mount a disk, so Chroma's
  directory is wiped on every restart. This is by design: Postgres stores each
  chunk *and its embedding vector*, and the index is rebuilt from the database
  at startup. Losing the index costs a few seconds of boot time, never data.
- **Postgres expiry.** Render's free Postgres expires ~30 days after creation.
- **Generation latency.** Plan generation is a synchronous LLM call (~15s
  locally, slower on a cold instance). The UI shows a loading state throughout.

---

## How it works

### Data model

```
User ─< Deal ─< Document ─< DocumentChunk
         │                        │
         └─< ActionPlan ─< ActionItem
                   │
                   └─< Citation >── DocumentChunk
```

Seven models. `Document`/`DocumentChunk` are the knowledge base;
`ActionPlan`/`ActionItem` are the persistent AI artifact; `Citation` is the join
that makes the output source-backed — it ties a generated item to the exact
chunk that produced it. Deleting a deal cascades to everything beneath it.

### Auth flow

Flask-Login session cookies, passwords bcrypt-hashed. `POST /api/signup` and
`POST /api/login` establish the session; `GET /api/me` checks it; `DELETE
/api/logout` ends it. In production the cookie is `HttpOnly; Secure;
SameSite=None` so it survives the cross-origin hop between the two Render
services. Login and signup return the same vague failure for an unknown email as
for a wrong password, so neither can be used to enumerate accounts.

Every user-owned record is fetched with ownership in the `WHERE` clause
(`filter_by(id=…, user_id=current_user.id)`), never fetched-then-checked. A
record owned by someone else returns **404, not 403** — a 403 would confirm the
record exists and let an attacker probe IDs.

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
4. **Generate.** The chunks become numbered sources in the prompt; Gemini
   returns structured JSON (summary, steps, items, and the source numbers for
   each). Invented citations — a source number that does not exist — are dropped.
5. **Persist.** The plan, its items, and a `Citation` per source are saved, so
   the citation a user clicks resolves to the exact passage the model was shown.

### The relevance floor

`RETRIEVAL_MIN_SCORE` is `0.60`, calibrated against `gemini-embedding-001`, whose
vectors are not zero-centered — real deal content scores 0.62–0.68 against a
planning query while a banana bread recipe still scores ~0.51. **Lowering this
does not make the app more permissive; it disables the weak-context gate.** If
the embedding model changes, this must be re-measured.

---

## Example tasks to try

- Generate a plan for the seeded Acme deal and confirm every item cites a source.
- Click a citation number to jump to the quoted passage it came from.
- Create an empty deal and try to generate a plan — the app refuses and explains.
- Upload an off-topic document (a recipe) and try again — it still refuses.
- Log in as the second account and confirm the Acme deal is nowhere to be seen.

---

## Known limitations

- The relevance floor separates on-topic from off-topic content by a narrow
  margin (~0.03 in cosine similarity). Obviously-unrelated content is refused
  reliably, but off-topic content *near* the sales domain can slip through.
- Text-based PDFs only. Scanned/image PDFs are rejected (no OCR).
- Generated Presenton decks are hosted on the vendor's public bucket at an
  unlisted URL; the app proxies downloads through an ownership-checked route,
  but the underlying object is not access-controlled by the vendor.

## Future improvements

- A semantic second gate (an explicit model judgment) to tighten weak-context
  detection.
- OCR for scanned documents.
- Free-form Q&A against a deal's documents, reusing the retrieval layer.
- Regenerate a plan while preserving already-completed action items.
