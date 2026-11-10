"""
Create a default recruiter account for the dashboard.
Usage:  cd backend && python ../scripts/create_recruiter.py
"""
import sys
import argparse
import getpass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="recruiter@company.com")
    args = parser.parse_args()

    password = getpass.getpass("New recruiter password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if len(password) < 12:
        parser.error("Password must be at least 12 characters.")
    if password != confirmation:
        parser.error("Passwords do not match.")

    from app.database.connection import SessionLocal, engine
    from app.database.base import Base
    import app.database.models
    from app.database.repositories.user_repository import UserRepository

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        repo = UserRepository(db)
        existing = repo.get_by_email(args.email)
        if existing:
            print(f"Recruiter already exists: {args.email}  role={existing.role}")
            return
        user = repo.create_user(email=args.email, password=password, role="recruiter")
        print(f"Created: {user.email}  role={user.role}")
    except Exception as e:
        print(f"Error: {e}"); sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()
