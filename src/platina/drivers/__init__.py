"""Shell: the driver contract and the SQLSTATE mapping, without psycopg (ADR-0012).

``interface`` holds the capability Protocols, the statement shape and the replies; ``errors`` maps
a driver fault onto the exception hierarchy. ``platina.drivers.psycopg`` is the only package that
imports psycopg (guard A102).
"""
