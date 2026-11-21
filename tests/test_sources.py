"""Source-system loaders. PostgreSQL runs against the throw-away server; Cassandra and Neo4j are tested only for the validation
that happens BEFORE a connection is opened (no Cassandra/Neo4j service is started by the test suite)."""
import os
import re
import uuid

import pandas as pd
import psycopg2
import pytest

from pgserver import dsn_with
from synth import Dataset, raw_edge, raw_event, raw_order


@pytest.fixture
def pgdb(ns, pgsrv):
    """Point the notebook's PG_* settings at a fresh database of the throw-away server."""
    db = "src_" + uuid.uuid4().hex[:8]
    admin = psycopg2.connect(dsn_with(pgsrv.dsn, "postgres"))
    admin.autocommit = True
    admin.cursor().execute(f"CREATE DATABASE {db}")
    admin.close()
    params = dict(re.findall(r"(\w+)=(\S+)", pgsrv.dsn))
    saved = {k: ns.get(k) for k in ("PG_HOST", "PG_PORT", "PG_DB", "PG_USER", "PG_PW")}
    ns.update(PG_HOST=params.get("host", "localhost"), PG_PORT=int(params.get("port", 5432)), PG_DB=db, PG_USER=params.get("user", "postgres"),
              PG_PW=params.get("password", ""))
    yield db
    ns.update(saved)
    admin = psycopg2.connect(dsn_with(pgsrv.dsn, "postgres"))
    admin.autocommit = True
    admin.cursor().execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
    admin.close()


def orders_frame(ns, rows):
    return pd.DataFrame(rows)


def raw_total(ns, order_id):
    c = ns["pg_connect"]()
    try:
        with c.cursor() as cur:
            cur.execute("SELECT order_total_usd FROM raw.orders WHERE order_id = %s", (order_id,))
            row = cur.fetchone()
            return None if row is None else row[0]
    finally:
        c.close()


# ---------------------------------------------------------------- PostgreSQL
def test_new_orders_are_loaded(ns, pgdb):
    assert ns["pg_load_orders"](pd.DataFrame(Dataset().orders)) == 2


def test_repeated_identical_load_does_not_duplicate_or_rewrite(ns, pgdb):
    df = pd.DataFrame(Dataset().orders)
    ns["pg_load_orders"](df)
    c = ns["pg_connect"]()
    with c.cursor() as cur:
        cur.execute("SELECT xmin::text, order_id FROM raw.orders ORDER BY order_id")
        before = cur.fetchall()
    c.close()
    assert ns["pg_load_orders"](df) == 2
    c = ns["pg_connect"]()
    with c.cursor() as cur:
        cur.execute("SELECT xmin::text, order_id FROM raw.orders ORDER BY order_id")
        assert cur.fetchall() == before                              # unchanged rows are not rewritten
    c.close()


def test_corrected_order_reaches_the_source_database(ns, pgdb):
    d = Dataset()
    ns["pg_load_orders"](pd.DataFrame(d.orders))
    assert float(raw_total(ns, "ORD1")) == 102.2
    d.order("ORD1")["order_total_usd"] = 92.2
    assert ns["pg_load_orders"](pd.DataFrame(d.orders)) == 2
    assert float(raw_total(ns, "ORD1")) == 92.2


def test_a_correction_can_set_a_value_to_null(ns, pgdb):
    d = Dataset()
    ns["pg_load_orders"](pd.DataFrame(d.orders))
    d.order("ORD1")["campaign"] = None
    ns["pg_load_orders"](pd.DataFrame(d.orders))
    c = ns["pg_connect"]()
    with c.cursor() as cur:
        cur.execute("SELECT campaign FROM raw.orders WHERE order_id = 'ORD1'")
        assert cur.fetchone()[0] is None
    c.close()


def test_order_missing_from_the_new_csv_is_not_deleted(ns, pgdb):
    d = Dataset()
    ns["pg_load_orders"](pd.DataFrame(d.orders))
    assert ns["pg_load_orders"](pd.DataFrame(d.orders[:1])) == 2     # documented limitation: no delete propagation
    assert raw_total(ns, "ORD2") is not None


def test_missing_primary_key_is_rejected_and_nothing_is_written(ns, pgdb):
    d = Dataset()
    ns["pg_load_orders"](pd.DataFrame(d.orders[:1]))
    bad = pd.DataFrame([raw_order(order_id="ORD5"), raw_order(order_id=None)])
    with pytest.raises(psycopg2.Error):
        ns["pg_load_orders"](bad)
    assert raw_total(ns, "ORD5") is None                              # the whole load rolled back
    assert float(raw_total(ns, "ORD1")) == 102.2


def test_duplicate_order_ids_inside_one_load_fail_loudly_instead_of_being_skipped(ns, pgdb):
    df = pd.DataFrame([raw_order(order_total_usd=1.0), raw_order(order_total_usd=2.0)])
    with pytest.raises(psycopg2.Error):                               # ON CONFLICT DO UPDATE cannot touch a row twice in one statement: fail loud (DO NOTHING used to skip silently)
        ns["pg_load_orders"](df)


def test_extract_returns_what_was_loaded(ns, pgdb):
    ns["pg_load_orders"](pd.DataFrame(Dataset().orders))
    out = ns["extract_from_pg"]()
    assert out.order_id.tolist() == ["ORD1", "ORD2"] and list(out.columns) == [c for c, _ in ns["ORDERS_COLSPEC"]]


# ---------------------------------------------------------------- Cassandra (validation before connecting)
def test_cassandra_rejects_null_primary_key_columns_before_connecting(ns):
    for col in ("event_id", "customer_id", "event_ts"):
        df = pd.DataFrame([raw_event(**{col: None})])
        with pytest.raises(ValueError, match=f"primary-key column {col}"):
            ns["cas_load_events"](df)


def test_cassandra_keyspace_name_is_validated(ns):
    saved = ns["CAS_KEYSPACE"]
    ns["CAS_KEYSPACE"] = "ecom; DROP KEYSPACE system"
    try:
        with pytest.raises(ValueError, match="unsafe keyspace"):
            ns["cas_connect"]()
    finally:
        ns["CAS_KEYSPACE"] = saved


# ---------------------------------------------------------------- Neo4j (validation before connecting)
@pytest.mark.parametrize("override,match", [
    (dict(relationship="LIKES"), "unsupported node types.*relationship types"),
    (dict(relationship="VIEWED]->() DETACH DELETE n //"), "unsupported"),
    (dict(from_node_type="Supplier"), "unsupported node types"),
    (dict(to_node_type="Customer) DETACH DELETE (n"), "unsupported node types"),
    (dict(from_node_id=None), "critical column|NULL"),
])
def test_neo4j_rejects_unsupported_labels_relationships_and_null_ids(ns, override, match):
    df = pd.DataFrame([raw_edge(**override)])
    if "from_node_id" in override:                                    # a NULL id is stopped earlier, by the transformation
        with pytest.raises(ValueError, match=match):
            ns["conform"](df, ns["EDGES_COLSPEC"], "edges")
    else:
        with pytest.raises(ValueError, match=match):
            ns["neo4j_load_edges"](df)


def test_neo4j_rejects_duplicate_edge_ids(ns):
    with pytest.raises(ValueError, match="edge_id must be present and unique"):
        ns["neo4j_load_edges"](pd.DataFrame([raw_edge(), raw_edge()]))


def test_neo4j_edge_properties_keep_timestamps_as_text_and_skip_nulls(ns):
    typed = ns["coerce_by_kind"](pd.DataFrame([raw_edge(order_id=None)]), ns["EDGES_COLSPEC"])
    props = ns["_edge_props"](typed.iloc[0].to_dict())
    assert props["timestamp"] == "2025-01-10 09:05:00" and "order_id" not in props and props["edge_id"] == "EDGE1"
    assert not {"from_node_id", "to_node_type", "relationship"} & set(props)      # structure is not stored as a property
