"""Functional core: no I/O, no event loop, no clock, no threads (design section 10.1).

Everything here is pure and immutable so it can be tested without a database. The guards
(tools/guards/archlint.py, A101/A105/A106) and import-linter enforce it.
"""
