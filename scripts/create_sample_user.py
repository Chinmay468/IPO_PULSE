"""
Create Sample User Account for IPO Pulse

Creates or updates a user account:
- Username: user
- Password: user123
"""

import argparse
import asyncio
import os
import sys

# Ensure project root in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.auth import hash_password_secure
from app.models.user import User


async def create_sample_user(db_url: str):
    print("=" * 70)
    print("CREATING SAMPLE USER FOR IPO PULSE")
    print("=" * 70)

    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with async_session() as session:
        username = "user"
        password_plain = "user123"
        hashed_pw = hash_password_secure(password_plain)

        stmt = select(User).where(User.username == username)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()

        if user:
            print(f"User '{username}' already exists (ID: {user.id}). Updating password & status...")
            user.hashed_password = hashed_pw
            user.is_active = True
            user.full_name = "Sample Investor"
            user.email = "user@example.com"
        else:
            print(f"Creating new user '{username}'...")
            user = User(
                username=username,
                hashed_password=hashed_pw,
                full_name="Sample Investor",
                email="user@example.com",
                is_active=True,
                is_superuser=False,
            )
            session.add(user)
            await session.flush()
            print(f"Created user '{username}' (ID: {user.id})")

        await session.commit()
        print("\nSUCCESS: Sample user initialized successfully!")
        print(f"Username : {username}")
        print(f"Password : {password_plain}")
        print("=" * 70)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create sample user")
    parser.add_argument("--db-url", type=str, default=None, help="Target SQLAlchemy DB connection URL")
    args = parser.parse_args()

    target_url = args.db_url or os.getenv("DATABASE_URL")
    if not target_url:
        from app.config import settings
        target_url = settings.DATABASE_URL

    asyncio.run(create_sample_user(target_url))
