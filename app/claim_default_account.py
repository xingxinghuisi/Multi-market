"""One-time interactive claim of an existing default workspace; never stores plaintext."""

from getpass import getpass

from sqlalchemy import select

from auth_api import password_hash
from database import Base, SessionLocal, engine
from models import User, UserCredential, UserSession


def main():
    Base.metadata.create_all(engine, tables=[UserCredential.__table__, UserSession.__table__], checkfirst=True)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "default"))
        if user is None:
            raise SystemExit("Existing default workspace was not found.")
        if db.get(UserCredential, user.id) is not None:
            raise SystemExit("Default workspace has already been claimed.")
        password = getpass("Set a password for the existing default workspace: ")
        confirm = getpass("Confirm password: ")
        if len(password) < 12 or len(password) > 128 or password != confirm:
            raise SystemExit("Password must be 12–128 characters and both entries must match.")
        db.add(UserCredential(user_id=user.id, password_hash=password_hash(password)))
        db.commit()
    print("Existing workspace claimed. Sign in as 'default'.")


if __name__ == "__main__":
    main()
