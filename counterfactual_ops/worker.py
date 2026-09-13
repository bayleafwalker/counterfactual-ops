"""Disposable worker. Only the experiment runner invokes this process.

Logical time makes retention boundaries deterministic; it models neither clock
skew nor asynchronous expiration. The effect has deliberately no unique key:
the assertion must detect duplicates independently of the dedup mechanism.
"""
import os
import sqlite3
import sys


def execute(path, implementation, fault, now, retention):
    db = sqlite3.connect(path)
    db.execute("PRAGMA synchronous=FULL")
    if db.execute("SELECT 1 FROM completed WHERE job='job-1' AND expires > ?", (now,)).fetchone():
        db.close()
        return
    db.execute("DELETE FROM completed WHERE expires <= ?", (now,))
    db.commit()
    db.execute("INSERT INTO effects(job, amount) VALUES ('job-1', 100)")
    if implementation == "split":
        db.commit()
    if fault == "after_effect":
        os._exit(73)
    db.execute("INSERT INTO completed VALUES ('job-1', ?)", (now + retention,))
    db.commit()
    if fault == "after_commit":
        os._exit(73)
    db.close()


if __name__ == "__main__":
    execute(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]))
