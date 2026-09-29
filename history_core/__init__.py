"""Local history parsing and indexing without the Web server lifecycle."""

from .reader import HistoryReader

__all__ = ["HistoryReader", "query_activity"]

from .activity import query_activity
