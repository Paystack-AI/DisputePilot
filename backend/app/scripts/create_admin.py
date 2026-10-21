"""Create or reset a separate admin account.

Run from backend/:
    python -m app.scripts.create_admin --email admin@example.com --name "Admin"
"""

import argparse
import asyncio
import getpass

from app.api.models.admins import Admin
from app.api.repo.admins import AdminAccountRepository
from app.core.security import Security
from app.database.session import async_session


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or reset a DisputePilot admin account")
    parser.add_argument("--email", required=True, help="admin email")
    parser.add_argument("--name", default=None, help="display name")
    return parser.parse_args()


def _password() -> str:
    password: str = getpass.getpass("Password: ")
    if len(password) < 8:
        raise SystemExit("Password must be at least 8 characters.")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match.")
    return password


async def _run(email: str, name: str | None, password: str) -> None:
    email = email.strip().lower()
    security = Security()
    hashed_password: str = await security.hash_password(password)

    async with async_session() as session:
        repo = AdminAccountRepository(async_session=session)
        admin: Admin | None = await repo.get_by_email(email)

        if admin:
            admin.name = name or admin.name
            admin.hashed_password = hashed_password
            admin.is_active = True
            action = "updated"
        else:
            admin = Admin(
                email=email,
                name=name,
                hashed_password=hashed_password,
                is_active=True,
            )
            session.add(admin)
            action = "created"

        await session.commit()
        await session.refresh(admin)
        print(f"Admin {action}: {admin.email} ({admin.id})")


def main() -> None:
    args = _arguments()
    asyncio.run(_run(args.email, args.name, _password()))


if __name__ == "__main__":
    main()
