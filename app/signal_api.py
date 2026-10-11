"""Private, read-only status; subscription mutations reuse /api/subscriptions."""
from fastapi import Depends
from sqlalchemy import select

from gemini_service import budget_owner, configuration, usage_summary
from models import AlertSubscription
from signal_models import TechnicalState


def install_signal_routes(app, get_db, get_user):
    @app.get("/api/signals")
    def signals(db=Depends(get_db)):
        user = get_user(db)
        owner = budget_owner(db)
        status = configuration()
        status["budget_owner"] = bool(owner and owner.id == user.id)
        status["usage"] = usage_summary(db) if status["budget_owner"] else None
        rows = db.execute(select(TechnicalState).join(AlertSubscription).where(
            AlertSubscription.user_id == user.id)).scalars().all()
        return {"gemini": status, "states": [{"subscription_id": row.subscription_id,
            "updated_at": row.updated_at, "snapshot": row.snapshot} for row in rows]}
