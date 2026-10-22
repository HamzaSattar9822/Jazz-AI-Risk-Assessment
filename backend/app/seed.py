from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.security import hash_password

DEMO_PASSWORD = "JazzDemo-2026"

DEMO_USERS = [
    {
        "email": "ayesha.khan@jazz.example",
        "name": "Ayesha Khan",
        "business_unit": "Technology",
        "role": "requester",
    },
    {
        "email": "rahim.qureshi@jazz.example",
        "name": "Rahim Qureshi",
        "business_unit": "Compliance",
        "role": "reviewer",
    },
    {
        "email": "sana.malik@jazz.example",
        "name": "Sana Malik",
        "business_unit": "Legal",
        "role": "governance",
    },
]


def seed_users(db: Session) -> None:
    existing = db.scalar(select(User.id).limit(1))
    if existing is not None:
        return
    password_hash = hash_password(DEMO_PASSWORD)
    for row in DEMO_USERS:
        db.add(User(password_hash=password_hash, **row))
    db.commit()
