"""Create one staging tenant and OIDC-mapped users (issuer = mock IdP). Synthetic data is allowed in staging."""

import uuid

from sqlalchemy import select

from app.db import worker_session
from app.models import Membership, Tenant, User

with worker_session() as db:
    t = db.scalar(select(Tenant).where(Tenant.slug == "staging-newsroom"))
    if t is None:
        t = Tenant(id=uuid.uuid4(), slug="staging-newsroom", name="Staging Newsroom", plan_key="newsroom")
        db.add(t)
        db.flush()
    for sub, role, op in (("alice", "admin", True), ("bob", "viewer", False)):
        u = db.scalar(select(User).where(User.issuer == "http://localhost:9000", User.subject == sub))
        if u is None:
            u = User(issuer="http://localhost:9000", subject=sub, email=f"{sub}@staging.invalid", is_platform_operator=op)
            db.add(u)
            db.flush()
        if db.get(Membership, {"tenant_id": t.id, "user_id": u.id}) is None:
            db.add(Membership(tenant_id=t.id, user_id=u.id, role=role))
    db.commit()
print("staging tenant ready")
