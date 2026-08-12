import argparse
import asyncio
import json

from sqlalchemy import func, select

from app.core.database import session_scope
from app.core.security import normalize_email
from app.models import User
from app.services.admin_metrics import audit_admin
from app.services.email import send_transactional_email
from app.services.operations import backup_manifest, migrate_local_to_s3, production_readiness, staging_smoke, test_database, test_redis, test_storage, verify_storage
from app.services.workspace_lifecycle import process_due_deletions


def output(value: dict) -> int:
    print(json.dumps(value, indent=2, default=str)); return 0 if value.get("status", "pass") != "fail" else 1


def set_system_admin(email: str, enabled: bool) -> int:
    with session_scope() as session:
        user = session.scalar(select(User).where(User.normalized_email == normalize_email(email)))
        if not user: print(f"Account not found: {email}"); return 1
        if not enabled and user.is_system_admin:
            count = int(session.scalar(select(func.count()).select_from(User).where(User.is_system_admin.is_(True), User.is_active.is_(True))) or 0)
            if count <= 1: print("Refusing to remove the last active system administrator."); return 2
        user.is_system_admin = enabled; audit_admin(session, None, "cli_grant_admin" if enabled else "cli_revoke_admin", "user", user.id, None, {"actor": "local_cli"})
        print(f"System administrator {'granted to' if enabled else 'removed from'} {user.email}."); return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DataPilot operational commands"); sub = parser.add_subparsers(dest="command", required=True)
    for name in ("make-system-admin", "remove-system-admin", "test-email"): command = sub.add_parser(name); command.add_argument("email")
    migration = sub.add_parser("migrate-storage"); migration.add_argument("--from", dest="source", default="local", choices=["local"]); migration.add_argument("--to", dest="target", default="s3", choices=["s3"]); migration.add_argument("--dry-run", action="store_true")
    for name in ("verify-storage", "test-database", "test-redis", "test-storage", "test-sentry", "staging-smoke", "production-readiness", "backup-manifest", "process-deletions"): sub.add_parser(name)
    args = parser.parse_args()
    if args.command in {"make-system-admin", "remove-system-admin"}: return set_system_admin(args.email, args.command == "make-system-admin")
    if args.command == "test-database": return output(test_database())
    if args.command == "test-redis": return output(test_redis())
    if args.command == "test-storage": return output(test_storage())
    if args.command == "verify-storage": return output(verify_storage())
    if args.command == "migrate-storage": return output(migrate_local_to_s3(args.dry_run))
    if args.command == "backup-manifest": return output(backup_manifest())
    if args.command == "process-deletions": return output({"status": "pass", **process_due_deletions()})
    if args.command == "production-readiness": return output(production_readiness())
    if args.command == "test-email": return output({"status": asyncio.run(send_transactional_email(args.email, "DataPilot staging email test", "This is a safe DataPilot email-provider validation.", "staging_test")).status})
    if args.command == "test-sentry":
        from app.core.config import get_settings
        if not get_settings().sentry_dsn: return output({"status": "skip", "reason": "SENTRY_DSN is not configured"})
        import sentry_sdk; sentry_sdk.capture_message("DataPilot safe staging validation"); return output({"status": "pass"})
    if args.command == "staging-smoke": return output(staging_smoke())
    return 1


if __name__ == "__main__": raise SystemExit(main())
