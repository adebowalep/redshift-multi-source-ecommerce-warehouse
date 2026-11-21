import re
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fake_redshift import PgDataApi  # noqa: E402
from nbload import load_notebook  # noqa: E402
from pgserver import TempPostgres, dsn_with  # noqa: E402
from synth import Dataset  # noqa: E402


@pytest.fixture(scope="session")
def ns():
    """Namespace holding the notebook's importable cells (functions, SQL, column specs)."""
    return load_notebook()


@pytest.fixture(scope="session")
def pgsrv():
    srv = TempPostgres().start()
    if srv is None:
        pytest.skip("no PostgreSQL available (set TEST_PG_DSN or install initdb/pg_ctl)")
    yield srv
    srv.stop()


class Warehouse:
    """A throw-away database + the notebook's Redshift helper functions pointed at it (PostgreSQL emulation of the Data API)."""

    def __init__(self, ns, api, db):
        self.ns, self.api, self.db = ns, api, db

    # ---- thin wrappers around the notebook's own helpers ----
    def exec(self, sql):
        return self.ns["rs_exec"](sql)

    def df(self, sql):
        return self.ns["rs_df"](sql)

    def scalar(self, sql):
        return self.ns["rs_scalar"](sql)

    def count(self, table):
        return int(self.scalar(f"SELECT COUNT(*) FROM {table}"))

    @property
    def fallback(self):
        return self.ns["NAMING"]["public_fallback"]

    def ddl(self, mode="INITIALIZE", confirm=None, allowed=None):
        allowed = {self.db} if allowed is None else set(allowed)
        confirm = f"REBUILD {self.db}" if confirm is None else confirm
        return self.ns["execute_warehouse_ddl"](self.ns["DDL_STATEMENTS"], self.ns["DDL_TABLES"], mode, allowed, confirm, say=lambda *_: None)

    def stage(self, data: Dataset):
        ns = self.ns
        orders, events, edges = data.frames()
        frames = {"stg.orders_raw": (ns["ORDERS_COLSPEC"], ns["conform"](orders, ns["ORDERS_COLSPEC"], "orders")),
                  "stg.events_raw": (ns["EVENTS_COLSPEC"], ns["conform"](events, ns["EVENTS_COLSPEC"], "events")),
                  "stg.edges_raw": (ns["EDGES_COLSPEC"], ns["conform"](edges, ns["EDGES_COLSPEC"], "edges"))}
        for table, (spec, frame) in frames.items():
            ns["rs_batch_insert"](table, spec, frame)

    def load(self):
        for _, sql in self.ns["dimension_statements"]():
            self.exec(sql)
        for _, sql in self.ns["fact_statements"]():
            self.exec(sql)

    def run(self, data: Dataset):
        """One pipeline run on already-initialised tables: stage the data, then load dimensions and facts."""
        self.stage(data)
        self.load()


def _make_wh(ns, pgsrv, deny_create_schema=False):
    import psycopg2
    db = "t_" + uuid.uuid4().hex[:10]
    admin = psycopg2.connect(dsn_with(pgsrv.dsn, "postgres"))
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f"CREATE DATABASE {db}")
    admin.close()
    api = PgDataApi(pgsrv.dsn, dbname=db, deny_create_schema=deny_create_schema)
    ns["rsd"] = api
    ns["NAMING"]["public_fallback"] = False
    ns["TQDM"] = False
    ns["BATCH_SIZE"] = 1000
    return Warehouse(ns, api, db)


@pytest.fixture
def wh(ns, pgsrv):
    w = _make_wh(ns, pgsrv)
    yield w
    w.api.close()


@pytest.fixture
def wh_lab(ns, pgsrv):
    """Same, but CREATE SCHEMA is denied like for the Udacity lab user -> public.stg_* / public.dw_* naming."""
    w = _make_wh(ns, pgsrv, deny_create_schema=True)
    yield w
    w.api.close()


@pytest.fixture
def data():
    return Dataset()
