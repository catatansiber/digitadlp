import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .config import Settings
from .db import make_engine, make_session_factory
from .models import Role, Unit, User
from .security import hash_password


def create_admin(username: str, unit_name: str, full_name: str | None) -> int:
    settings = Settings.from_env(require_fernet=False)
    password = getpass.getpass("Kata sandi: ")
    if len(password) < 8:
        print("Kata sandi minimal 8 karakter.", file=sys.stderr)
        return 1
    if password != getpass.getpass("Ulangi kata sandi: "):
        print("Kata sandi tidak sama.", file=sys.stderr)
        return 1
    engine = make_engine(settings.database_url)
    with make_session_factory(engine)() as db:
        unit = db.scalar(select(Unit).where(Unit.name == unit_name))
        if unit is None:
            unit = Unit(name=unit_name)
            db.add(unit)
            db.flush()
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                full_name=full_name or username,
                role=Role.ADMIN,
                unit_id=unit.id,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            print(f"Nama pengguna '{username}' sudah dipakai.", file=sys.stderr)
            return 1
    print(f"Admin '{username}' dibuat di unit '{unit_name}'.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m digitadlp.app")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-admin", help="Buat akun Admin")
    p.add_argument("--username", required=True)
    p.add_argument("--unit", required=True, help="Nama unit kerja")
    p.add_argument("--full-name", default=None)
    args = parser.parse_args(argv)
    return create_admin(args.username, args.unit, args.full_name)


if __name__ == "__main__":
    sys.exit(main())
