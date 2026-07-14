from flask import abort
from flask_login import current_user

from .extensions import db


def owned_or_404(model, record_id, user_id=None):
    """Fetch a record that belongs to the current user, or abort with 404.

    Two decisions worth stating outright:

    1. Ownership is part of the *query*, not a check performed after loading the
       row. Fetch-then-compare is how authorization bugs get written: it only
       takes one forgotten `if` to leak a record.

    2. A record owned by someone else returns 404, not 403. A 403 would confirm
       that the record exists, letting anyone probe IDs to learn how many deals
       a rival has. "Not found" and "not yours" are indistinguishable from the
       outside, which is the point.
    """
    owner_id = user_id if user_id is not None else current_user.id
    record = (
        db.session.query(model).filter_by(id=record_id, user_id=owner_id).one_or_none()
    )
    if record is None:
        abort(404, description=f"{model.__name__} not found")
    return record
