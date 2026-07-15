"""Seed a demo account with a realistic deal and its source documents.

Run:  python seed.py           (idempotent — re-running resets the demo data)

The documents below are synthetic but deliberately dense: they carry specific,
checkable facts (a hard deadline, a named economic buyer, an unanswered
technical question, a competitor) so that a generated plan can be judged on
whether it actually surfaced them, rather than on whether it reads fluently.

Two accounts are created on purpose. The second one exists so a reviewer can log
in as it and confirm the first account's deals are invisible.
"""

import sys

from app import create_app
from app.extensions import db
from app.models import Deal, User
from app.services.embeddings import EmbeddingError
from app.services.ingestion import ingest_document

DEMO_EMAIL = "demo@salesenablement.pro"
DEMO_PASSWORD = "demo12345"
SECOND_EMAIL = "rival@salesenablement.pro"

DISCOVERY_CALL = """Discovery call - Acme Corp - July 10, 2026

Attendees: Rita Chen (VP Engineering, Acme), Dan Ortiz (CFO, Acme, joined for the
last 15 minutes), Priya Raman (our AE), Tom Whitfield (our SE).

Current state
Acme runs our competitor Contoso's platform today. That contract expires on
September 30 and Rita was explicit that they will not renew it. The migration
window is therefore tight and they need a signed agreement before the end of
August to leave time for implementation.

Blockers
Rita confirmed the security questionnaire must be returned by August 1. If it
misses that date, procurement will not advance the deal to legal review this
quarter, and the whole thing slips to Q4.

Dan Ortiz is the economic buyer and holds final sign-off. He asked two specific
questions we did not fully answer: whether we have a SOC2 Type II report (we do,
dated March 2026) and whether we support SSO through Okta. We owe him a definite
answer on Okta - Tom thinks yes but was not certain on the SCIM provisioning
piece.

Commitments we made
1. Return the completed security questionnaire by August 1.
2. Send the SOC2 Type II report.
3. Send a revised pricing sheet reflecting the 18% multi-year discount Dan asked
   about, by Friday July 17.

Competition
Rita mentioned, unprompted, that Initech has already submitted their RFP
response. She would not say more, but the implication was that we are behind on
paperwork.

Next meeting
Not yet scheduled. Rita suggested the week of July 21 and asked that Dan be
included.
"""

COMPANY_PROFILE = """Acme Corp - account profile

Industry: industrial manufacturing, mid-market. Roughly 1,400 employees across
four sites in the US and one in Germany.

Technology footprint
Okta for identity. Workday for HR. A homegrown MES on the factory floor that
their engineering team is protective of. Currently on Contoso's platform, which
they adopted three years ago and have been vocally unhappy with since a major
outage in January 2026.

Stakeholders
- Rita Chen, VP Engineering. Technical champion. Cares about migration risk and
  about her team not absorbing the integration work.
- Dan Ortiz, CFO. Economic buyer. Joined 8 months ago from a PE-backed company
  and is visibly focused on cost discipline. Asks for multi-year discounts.
- Marcus Webb, Director of IT Security. Not yet engaged, but owns the security
  questionnaire process. Nothing moves through procurement without his sign-off.

Buying process
Procurement requires a completed security questionnaire before legal review.
Legal review historically takes three weeks at Acme. Contract value is expected
to land around $50,000 ARR for the initial term.
"""

RFP_EXTRACT = """Acme Corp - Vendor RFP (extract) - Section 4: Security and Compliance

4.1 Vendors must provide a current SOC2 Type II attestation report, issued within
the last twelve months. Bridge letters are not accepted in place of a report.

4.2 Vendors must describe their data retention policy, including the maximum
period customer data is retained after contract termination, and the process by
which a customer may request deletion.

4.3 Vendors must state their breach notification timeline. Acme requires
notification within 72 hours of a confirmed breach affecting customer data.

4.4 Vendors must support single sign-on via SAML 2.0. Vendors should state
whether they additionally support SCIM user provisioning. Acme's identity
provider is Okta.

4.5 Vendors must disclose all subprocessors with access to customer data,
including the jurisdiction in which each operates.

Section 7: Timeline
Responses to this RFP, including the completed security questionnaire in
Appendix B, are due by August 1, 2026. Late responses will not be evaluated.
Acme intends to select a vendor by August 22 and to have a signed agreement in
place before September 30.
"""

DOCUMENTS = [
    ("discovery-call-2026-07-10.txt", DISCOVERY_CALL, "meeting_note"),
    ("acme-account-profile.txt", COMPANY_PROFILE, "company_info"),
    ("acme-rfp-section-4.txt", RFP_EXTRACT, "rfp"),
]


def reset_user(email, name, password):
    existing = db.session.query(User).filter_by(email=email).one_or_none()
    if existing:
        # Cascades take the old demo deals, documents, chunks, and plans with it.
        db.session.delete(existing)
        db.session.commit()

    user = User(email=email, name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def main():
    app = create_app()
    with app.app_context():
        db.create_all()

        demo = reset_user(DEMO_EMAIL, "Priya Raman", DEMO_PASSWORD)
        # A second account with no data of its own. A reviewer can sign in as
        # this one and confirm the demo account's deals are nowhere to be seen.
        reset_user(SECOND_EMAIL, "Rival Rep", DEMO_PASSWORD)

        deal = Deal(
            user_id=demo.id,
            name="Platform Renewal",
            company="Acme Corp",
            stage="discovery",
            value=50000,
        )
        db.session.add(deal)
        db.session.commit()

        print(f"Seeding {len(DOCUMENTS)} documents (this calls the embedding API)…")
        for filename, content, doc_type in DOCUMENTS:
            try:
                document = ingest_document(deal, filename, content.encode(), doc_type)
            except EmbeddingError as err:
                print(f"  ✗ {filename}: {err}", file=sys.stderr)
                print(
                    "\nSeeding failed. Check GOOGLE_API_KEY. A newly issued key can "
                    "return intermittent 403s for a few minutes until it propagates.",
                    file=sys.stderr,
                )
                sys.exit(1)
            print(f"  ✓ {filename} — {len(document.chunks)} passages indexed")

        print(
            f"\nDone.\n"
            f"  Demo login:  {DEMO_EMAIL} / {DEMO_PASSWORD}\n"
            f"  Second user: {SECOND_EMAIL} / {DEMO_PASSWORD}  (sees none of the above)\n"
            f"\nOpen the deal and click Generate action plan."
        )


if __name__ == "__main__":
    main()
