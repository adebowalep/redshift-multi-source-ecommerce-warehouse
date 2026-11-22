"""Reproduce suspected defects of the ORIGINAL notebook (evidence/starter.executed-2026-11-12.ipynb) on a PostgreSQL emulation."""
import json, re, sys, uuid
sys.path.insert(0, "tests")
import psycopg2
from nbload import load_notebook
from pgserver import TempPostgres
from fake_redshift import PgDataApi
from synth import Dataset

old = json.load(open("evidence/starter.executed-2026-11-12.ipynb"))
def cell(marker):
    return next("".join(c["source"]) for c in old["cells"] if c["cell_type"] == "code" and marker in "".join(c["source"]))
dims_src, facts_src, ddlrun_src = cell("Step 3: Populating dimension tables"), cell("Step 4: Populating fact tables"), cell("Step 1: Executing DDL")
# only the SQL constants (everything before the first 'with stage(')
old_ns = {"List": __import__("typing").List}
exec(dims_src.split("with stage(")[0], old_ns)
exec(facts_src.split("with stage(")[0], old_ns)

ns = load_notebook()
srv = TempPostgres().start()
db = "t_" + uuid.uuid4().hex[:8]
a = psycopg2.connect(srv.dsn); a.autocommit = True; a.cursor().execute(f"CREATE DATABASE {db}")
api = PgDataApi(srv.dsn, dbname=db); ns["rsd"] = api; ns["NAMING"]["public_fallback"] = False; ns["TQDM"] = False
def x(sql): return ns["rs_exec"](sql)
def n(sql): return ns["rs_scalar"](sql)

# --- R1: the original DDL step drops populated tables on every run
for s in ns["DDL_STATEMENTS"]: x(s)
data = Dataset(); o, e, g = data.frames()
for t, spec, fr, nm in [("stg.orders_raw", ns["ORDERS_COLSPEC"], o, "orders"), ("stg.events_raw", ns["EVENTS_COLSPEC"], e, "events"), ("stg.edges_raw", ns["EDGES_COLSPEC"], g, "edges")]:
    ns["rs_batch_insert"](t, spec, ns["conform"](fr, spec, nm))
x(old_ns["SQL_DIM_DATE"]); x(old_ns["SQL_DIM_CUSTOMER"]); x(old_ns["SQL_DIM_PRODUCT"]); [x(old_ns["sql_simple_dim"](t, c, s)) for t, c, s in old_ns["SIMPLE_DIMS"]]
x(old_ns["SQL_FACT_ORDERS"])
print("R1 before DDL re-run: dw.fact_orders rows =", n("SELECT COUNT(*) FROM dw.fact_orders"))
for s in ns["DDL_STATEMENTS"]: x(s)        # what the original DDL cell does on a second 'Run All'
print("R1 after  DDL re-run: dw.fact_orders rows =", n("SELECT COUNT(*) FROM dw.fact_orders"), "(populated table was dropped and re-created empty)")

# --- R2: corrected order total never reaches the fact (NOT EXISTS) 
data = Dataset(); o, e, g = data.frames()
for t, spec, fr, nm in [("stg.orders_raw", ns["ORDERS_COLSPEC"], o, "orders"), ("stg.events_raw", ns["EVENTS_COLSPEC"], e, "events"), ("stg.edges_raw", ns["EDGES_COLSPEC"], g, "edges")]:
    ns["rs_batch_insert"](t, spec, ns["conform"](fr, spec, nm))
x(old_ns["SQL_DIM_DATE"]); x(old_ns["SQL_DIM_CUSTOMER"]); x(old_ns["SQL_DIM_PRODUCT"]); [x(old_ns["sql_simple_dim"](t, c, s)) for t, c, s in old_ns["SIMPLE_DIMS"]]
x(old_ns["SQL_FACT_ORDERS"])
before = n("SELECT order_total_usd FROM dw.fact_orders WHERE order_id='ORD1'")
data.order("ORD1")["order_total_usd"] = 92.2        # source corrected 102.2 -> 92.2
o, e, g = data.frames()
ns["rs_batch_insert"]("stg.orders_raw", ns["ORDERS_COLSPEC"], ns["conform"](o, ns["ORDERS_COLSPEC"], "orders"))
x(old_ns["SQL_FACT_ORDERS"])
print("R2 fact order_total_usd for ORD1: before correction =", before, "| staging now =", n("SELECT order_total_usd FROM stg.orders_raw WHERE order_id='ORD1'"),
      "| fact after re-run =", n("SELECT order_total_usd FROM dw.fact_orders WHERE order_id='ORD1'"))

# --- R3: PostgreSQL ingestion with ON CONFLICT DO NOTHING ignores the correction
conn = psycopg2.connect(srv.dsn, dbname=db); conn.autocommit = True
import os
old_pg = cell("# ========= PostgreSQL Functions")
pg_ns = dict(ns); pg_ns["PG_HOST"] = srv.sock; pg_ns["PG_PORT"] = 54399; pg_ns["PG_DB"] = db; pg_ns["PG_USER"] = "tester"; pg_ns["PG_PW"] = ""
exec(old_pg, pg_ns)
d2 = Dataset(); o2, _, _ = d2.frames()
old_fn = pg_ns["pg_load_orders"]
import psycopg2 as _p
_orig = _p.connect
_p.connect = lambda **kw: _orig(host=srv.sock, port=54399, user="tester", dbname=db)
old_fn(o2)
d2.order("ORD1")["order_total_usd"] = 92.2
o2, _, _ = d2.frames(); old_fn(o2)
cur = conn.cursor(); cur.execute("SELECT order_total_usd FROM raw.orders WHERE order_id='ORD1'")
print("R3 raw.orders ORD1 total after the CSV was corrected to 92.2 and re-loaded (old ON CONFLICT DO NOTHING):", cur.fetchone()[0])
srv.stop()
