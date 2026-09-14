"""SQLAlchemy ORM models.

Tables are introduced in Prompt 1 (domain model + seed fixtures).
This module currently only exports the declarative Base so later
modules can import it without circular wiring.
"""

from app.db.engine import Base

__all__ = ["Base"]
