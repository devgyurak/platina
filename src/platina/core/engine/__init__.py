"""Execution engine: a generator that yields Commands and receives Replies, including retry and
backoff (design section 10.5). It never performs I/O itself; the runners do.
"""
