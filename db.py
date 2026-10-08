"""Thin DB layer: SQLite by default, MySQL (mysql.connector, as in rail.py) via env vars."""
import os, sqlite3
BACKEND = os.getenv("DB_BACKEND", "sqlite")  # "sqlite" | "mysql"
AI = "INTEGER PRIMARY KEY AUTOINCREMENT" if BACKEND == "sqlite" else "INT PRIMARY KEY AUTO_INCREMENT"
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS users(id {AI}, name VARCHAR(80), email VARCHAR(120) UNIQUE, pw_hash VARCHAR(255));
CREATE TABLE IF NOT EXISTS trains(number VARCHAR(5) PRIMARY KEY, name VARCHAR(80), dep_time VARCHAR(5),
  popularity FLOAT, avg_delay FLOAT, delay_sd FLOAT);
CREATE TABLE IF NOT EXISTS stops(id {AI}, train_no VARCHAR(5), seq INT, code VARCHAR(5), name VARCHAR(60),
  arr_min INT, dep_min INT, km INT);
CREATE TABLE IF NOT EXISTS inventory(id {AI}, train_no VARCHAR(5), cls VARCHAR(2), coaches INT, per_coach INT, demand FLOAT);
CREATE TABLE IF NOT EXISTS bookings(id {AI}, pnr CHAR(10) UNIQUE, user_id INT, train_no VARCHAR(5),
  journey_date VARCHAR(10), from_code VARCHAR(5), to_code VARCHAR(5), cls VARCHAR(2), fare FLOAT, created_at VARCHAR(19));
CREATE TABLE IF NOT EXISTS passengers(id {AI}, booking_id INT, name VARCHAR(80), age INT, gender CHAR(1),
  train_no VARCHAR(5), journey_date VARCHAR(10), cls VARCHAR(2), seat_idx INT NULL, coach VARCHAR(4) NULL,
  seat_no INT NULL, berth VARCHAR(20) NULL, status VARCHAR(4), wl_no INT NULL,
  UNIQUE(train_no, journey_date, cls, seat_idx));
"""

class DB:
    def __init__(self):
        if BACKEND == "mysql":
            import mysql.connector
            self.c = mysql.connector.connect(host=os.getenv("DB_HOST", "localhost"), user=os.getenv("DB_USER", "root"),
                password=os.getenv("DB_PASSWORD", ""), database=os.getenv("DB_NAME", "railmind"))
        else:
            self.c = sqlite3.connect(os.getenv("DB_PATH", "railmind.db"), timeout=15)
            self.c.row_factory = sqlite3.Row
    def q(self, sql, args=()):
        """Run a query; returns list of dicts. Use ? placeholders for both backends (parameterised = no SQL injection)."""
        if BACKEND == "mysql":
            cur = self.c.cursor(dictionary=True); cur.execute(sql.replace("?", "%s"), args)
            rows = cur.fetchall() if cur.with_rows else []
        else:
            cur = self.c.execute(sql, args); rows = [dict(r) for r in cur.fetchall()]
        self.lastrowid = cur.lastrowid
        return rows
    def one(self, sql, args=()):
        r = self.q(sql, args); return r[0] if r else None
    def commit(self): self.c.commit()
    def rollback(self): self.c.rollback()
    def close(self): self.c.close()
    def init_schema(self):
        for stmt in SCHEMA.split(";"):
            if stmt.strip(): self.q(stmt)
        self.commit()
