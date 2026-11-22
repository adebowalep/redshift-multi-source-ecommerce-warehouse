"""A disposable PostgreSQL for the tests.

Use TEST_PG_DSN (e.g. the GitHub Actions service container) when it is set; otherwise start a throw-away cluster with
initdb/pg_ctl from PATH (or the Homebrew locations). If neither is available the PostgreSQL-backed tests are skipped.
"""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_CANDIDATE_DIRS = ["/usr/local/opt/postgresql@17/bin", "/opt/homebrew/opt/postgresql@17/bin", "/usr/lib/postgresql/16/bin",
                   "/usr/lib/postgresql/15/bin", "/usr/lib/postgresql/14/bin"]


def _bin(name):
    found = shutil.which(name)
    if found:
        return found
    for d in _CANDIDATE_DIRS:
        p = Path(d) / name
        if p.exists():
            return str(p)
    return None


def dsn_with(dsn: str, dbname: str = None) -> str:
    """libpq key=value DSN with its dbname replaced (or removed): avoids a duplicated dbname keyword."""
    parts = [p for p in dsn.split() if not p.startswith("dbname=")]
    return " ".join(parts + ([f"dbname={dbname}"] if dbname else []))


class TempPostgres:
    def __init__(self):
        self.dir = None
        self.dsn = None

    def start(self):
        env_dsn = os.environ.get("TEST_PG_DSN")
        if env_dsn:
            self.dsn = env_dsn
            return self
        initdb, pg_ctl = _bin("initdb"), _bin("pg_ctl")
        if not (initdb and pg_ctl):
            return None
        self.dir = tempfile.mkdtemp(prefix="pgtest")
        data, sock = Path(self.dir) / "data", tempfile.mkdtemp(prefix="pgs")
        self.sock = sock
        env = {**os.environ, "LC_ALL": "en_US.UTF-8", "LANG": "en_US.UTF-8"}
        subprocess.run([initdb, "-D", str(data), "-U", "tester", "-A", "trust", "--no-sync"], check=True, capture_output=True, env=env)
        import socket
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            port = str(sk.getsockname()[1])               # a free port: no clash with a leftover server
        opts = f"-p {port} -c listen_addresses= -c unix_socket_directories={sock} -c fsync=off -c synchronous_commit=off"
        subprocess.run([pg_ctl, "-D", str(data), "-o", opts, "-w", "-l", str(Path(self.dir) / "log"), "start"], check=True,
                       capture_output=True, env=env)
        self._pg_ctl, self._data = pg_ctl, str(data)
        self.dsn = f"host={sock} port={port} user=tester dbname=postgres"
        return self

    def stop(self):
        if self.dir:
            subprocess.run([self._pg_ctl, "-D", self._data, "-m", "immediate", "stop"], capture_output=True)
            shutil.rmtree(self.dir, ignore_errors=True)
            shutil.rmtree(self.sock, ignore_errors=True)
