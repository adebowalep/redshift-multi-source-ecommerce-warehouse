import json, sys, uuid
sys.path.insert(0, "tests")
import psycopg2
from nbload import load_notebook
from pgserver import TempPostgres
from fake_redshift import PgDataApi
from synth import Dataset, raw_order, raw_edge
old = json.load(open("evidence/starter.executed-2026-11-12.ipynb"))
src = next("".join(c["source"]) for c in old["cells"] if c["cell_type"] == "code" and "Step 3: Populating dimension tables" in "".join(c["source"]))
old_ns = {"List": __import__("typing").List}; exec(src.split("with stage(")[0], old_ns)
ns = load_notebook(); srv = TempPostgres().start()
def run(order_rows, edge_rows):
    db = "t_" + uuid.uuid4().hex[:8]; a = psycopg2.connect(srv.dsn); a.autocommit = True; a.cursor().execute(f"CREATE DATABASE {db}")
    ns["rsd"] = PgDataApi(srv.dsn, dbname=db); ns["NAMING"]["public_fallback"] = False; ns["TQDM"] = False
    for s in ns["DDL_STATEMENTS"]: ns["rs_exec"](s)
    d = Dataset(); d.orders = order_rows; d.edges = edge_rows; d.events = []
    o, e, g = d.frames()
    import pandas as pd
    for t, spec, fr, nm in [("stg.orders_raw", ns["ORDERS_COLSPEC"], o, "orders"), ("stg.edges_raw", ns["EDGES_COLSPEC"], g, "edges")]:
        ns["rs_batch_insert"](t, spec, ns["conform"](fr, spec, nm))
    ns["rs_exec"](old_ns["SQL_DIM_CUSTOMER"]); ns["rs_exec"](old_ns["SQL_DIM_PRODUCT"])
    c = ns["rs_df"]("SELECT country, state FROM dw.dim_customer WHERE customer_id='C9'").iloc[0].tolist()
    p = ns["rs_df"]("SELECT price_bucket, current_unit_price_usd FROM dw.dim_product WHERE product_id='P9'").iloc[0].tolist()
    return c, p
o = [raw_order(order_id="ORD10", customer_id="C9", country="US", state="CA", order_datetime="2025-02-01 10:00:00"),
     raw_order(order_id="ORD11", customer_id="C9", country="DE", state="BE", order_datetime="2025-02-01 10:00:00")]
e = [raw_edge(edge_id="EDGE10", to_node_id="P9", product_id="P9", unit_price_usd=10.0, price_bucket="low", timestamp="2025-03-01 10:00:00"),
     raw_edge(edge_id="EDGE11", to_node_id="P9", product_id="P9", unit_price_usd=99.0, price_bucket="high", timestamp="2025-03-01 10:00:00")]
print("T1 original SQL, insertion order A:", run(o, e))
print("T1 original SQL, insertion order B:", run(o[::-1], e[::-1]))
srv.stop()
