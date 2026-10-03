"""SQLite + SQLAlchemy 2.x: engine, session factory, ORM models and CRUD helpers."""
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (DateTime, Float, ForeignKey, Integer, String, Text, create_engine,
                        event, func, select)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column, relationship,
                            sessionmaker)

from app import config


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    eng = create_engine(url, connect_args=connect_args)
    if url.startswith("sqlite"):
        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")  # enforce ON DELETE CASCADE
            cur.execute("PRAGMA journal_mode=WAL")  # readers don't block the writer
            cur.execute("PRAGMA busy_timeout=10000")
            cur.close()
    return eng


engine = make_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    goal: Mapped[str] = mapped_column(String(200), nullable=False)
    intensity: Mapped[str] = mapped_column(String(10), nullable=False)
    experience: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    plans: Mapped[list["Plan"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True,
        order_by="Plan.version",
    )


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    nutrition_tip: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="demo")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    user: Mapped[User] = relationship(back_populates="plans")

    @property
    def plan(self) -> dict:
        return json.loads(self.plan_json)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "plan": self.plan,
            "feedback": self.feedback,
            "nutrition_tip": self.nutrition_tip,
            "source": self.source,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


# ---------------------------- CRUD helpers ----------------------------

def save_user(name: str, age: int, weight_kg: float, goal: str, intensity: str,
              experience: str) -> int:
    """Always creates a new user; returns the server-generated id."""
    with SessionLocal() as db:
        user = User(name=name, age=age, weight_kg=weight_kg, goal=goal,
                    intensity=intensity, experience=experience)
        db.add(user)
        db.commit()
        return user.id


def get_user(user_id: int) -> Optional[User]:
    with SessionLocal() as db:
        return db.get(User, user_id)


def _next_version(db, user_id: int) -> int:
    current = db.scalar(select(func.max(Plan.version)).where(Plan.user_id == user_id))
    return (current or 0) + 1


def save_plan(user_id: int, plan: dict, nutrition_tip: Optional[str], source: str,
              feedback: Optional[str] = None) -> int:
    """Insert a plan row at the next version number; returns the version."""
    with SessionLocal() as db:
        version = _next_version(db, user_id)
        db.add(Plan(user_id=user_id, version=version, plan_json=json.dumps(plan),
                    feedback=feedback, nutrition_tip=nutrition_tip, source=source))
        db.commit()
        return version


def update_plan(user_id: int, plan: dict, feedback: str, nutrition_tip: Optional[str],
                source: str) -> int:
    """Revisions never overwrite: a NEW version row is inserted."""
    return save_plan(user_id, plan, nutrition_tip, source, feedback=feedback)


def get_latest_plan(user_id: int) -> Optional[Plan]:
    with SessionLocal() as db:
        return db.scalar(select(Plan).where(Plan.user_id == user_id)
                         .order_by(Plan.version.desc()).limit(1))


def get_original_plan(user_id: int) -> Optional[Plan]:
    with SessionLocal() as db:
        return db.scalar(select(Plan).where(Plan.user_id == user_id)
                         .order_by(Plan.version.asc()).limit(1))


def get_plan_version(user_id: int, version: int) -> Optional[Plan]:
    with SessionLocal() as db:
        return db.scalar(select(Plan).where(Plan.user_id == user_id, Plan.version == version))


def get_plan_history(user_id: int) -> list[Plan]:
    with SessionLocal() as db:
        return list(db.scalars(select(Plan).where(Plan.user_id == user_id)
                               .order_by(Plan.version.asc())))


def get_all_users() -> list[dict]:
    """Users with version count, original and latest plan (for the admin dashboard)."""
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.id.desc())).all()
        out = []
        for u in users:
            plans = list(u.plans)
            out.append({
                "user": u,
                "versions": len(plans),
                "original": plans[0] if plans else None,
                "latest": plans[-1] if plans else None,
            })
        return out


def delete_user(user_id: int) -> bool:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return False
        db.delete(user)
        db.commit()
        return True


def db_ok() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(select(1))
        return True
    except Exception:
        return False
