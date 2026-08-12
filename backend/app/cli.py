import argparse

from sqlalchemy import func, select

from app.core.database import session_scope
from app.core.security import normalize_email
from app.models import User
from app.services.admin_metrics import audit_admin


def set_system_admin(email: str, enabled: bool) -> int:
    with session_scope() as session:
        user = session.scalar(select(User).where(User.normalized_email == normalize_email(email)))
        if not user:
            print(f"Account not found: {email}"); return 1
        if not enabled and user.is_system_admin:
            count = int(session.scalar(select(func.count()).select_from(User).where(User.is_system_admin.is_(True), User.is_active.is_(True))) or 0)
            if count <= 1:
                print("Refusing to remove the last active system administrator."); return 2
        user.is_system_admin = enabled
        audit_admin(session, None, "cli_grant_admin" if enabled else "cli_revoke_admin", "user", user.id, None, {"actor": "local_cli"})
        print(f"System administrator {'granted to' if enabled else 'removed from'} {user.email}.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DataPilot operational commands")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("make-system-admin", "remove-system-admin"):
        command = sub.add_parser(name); command.add_argument("email")
    args = parser.parse_args()
    return set_system_admin(args.email, args.command == "make-system-admin")


if __name__ == "__main__": raise SystemExit(main())
