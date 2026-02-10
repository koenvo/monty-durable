"""Database models for durable-monty."""

from datetime import datetime, timezone
from typing import Any
import json
import enum

from sqlalchemy import (
    Column,
    String,
    Integer,
    LargeBinary,
    DateTime,
    Text,
    ForeignKey,
    Index,
    create_engine,
    Enum,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class ExecutionStatus(str, enum.Enum):
    """Status of a workflow execution."""
    SCHEDULED = "scheduled"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


class CallStatus(str, enum.Enum):
    """Status of an external function call."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Execution(Base):
    """Workflow execution state."""

    __tablename__ = "executions"

    id = Column(String(36), primary_key=True)  # UUID as string
    code = Column(Text, nullable=False)
    external_functions = Column(Text, nullable=False)  # JSON list of function names
    state = Column(LargeBinary, nullable=True)  # MontyFutureSnapshot.dump()
    status = Column(Enum(ExecutionStatus), nullable=False)
    current_resume_group_id = Column(String(36), nullable=True)
    inputs = Column(Text, nullable=True)  # JSON string
    output = Column(Text, nullable=True)  # JSON string
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    calls = relationship("Call", back_populates="execution", cascade="all, delete-orphan")


class Call(Base):
    """Individual external function call."""

    __tablename__ = "calls"
    __table_args__ = (Index("idx_resume_group_status", "resume_group_id", "status"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(String(36), ForeignKey("executions.id", ondelete="CASCADE"), nullable=False)
    resume_group_id = Column(String(36), nullable=False)
    call_id = Column(Integer, nullable=False)  # Monty's internal call_id
    function_name = Column(String(100), nullable=False)
    args = Column(Text, nullable=False)  # JSON string
    kwargs = Column(Text, nullable=True)  # JSON string
    status = Column(Enum(CallStatus), nullable=False, default=CallStatus.PENDING)
    job_id = Column(String(100), nullable=True)  # External job ID (RQ/Modal/Lambda)
    result = Column(Text, nullable=True)  # JSON string
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)

    execution = relationship("Execution", back_populates="calls")


# JSON helpers
def to_json(obj: Any) -> str | None:
    """Convert Python object to JSON string."""
    return json.dumps(obj) if obj is not None else None


def from_json(s: str | None) -> Any:
    """Convert JSON string to Python object."""
    return json.loads(s) if s else None


# Database initialization
def init_db(connection_string: str = "sqlite:///durable_functions.db"):
    """
    Initialize database and create tables.

    Examples:
    - SQLite: "sqlite:///durable_functions.db"
    - Postgres: "postgresql://user:pass@localhost/dbname"
    - MySQL: "mysql+pymysql://user:pass@localhost/dbname"
    """
    engine = create_engine(connection_string)
    Base.metadata.create_all(engine)
    return engine
