"""Negative controls: break a clean synthetic warehouse on purpose and check that the project's own data-quality checks notice.

A check that cannot fail proves nothing, so every tampering below must turn at least the named check from 0 to > 0.
"""
import pytest


@pytest.fixture
def clean(wh, data):
    wh.ddl()
    wh.run(data)
    return wh


def results(wh):
    return {name: int(wh.scalar(sql)) for name, sql in wh.ns["DQ_CHECKS"]}


def test_there_are_27_checks_and_all_pass_on_clean_data(clean):
    r = results(clean)
    assert len(r) == 27 and not any(r.values()), {k: v for k, v in r.items() if v}


TAMPER = [
    ("duplicate order_id in dw.fact_orders", "INSERT INTO dw.fact_orders SELECT * FROM dw.fact_orders WHERE order_id = 'ORD1'"),
    ("duplicate event_id in dw.fact_events", "INSERT INTO dw.fact_events SELECT * FROM dw.fact_events WHERE event_id = 'EVT1'"),
    ("duplicate edge_id in dw.fact_graph_edges", "INSERT INTO dw.fact_graph_edges SELECT * FROM dw.fact_graph_edges WHERE edge_id = 'EDGE1'"),
    ("duplicate customer_id in dim_customer", "INSERT INTO dw.dim_customer (customer_id, is_current) VALUES ('C1', TRUE)"),
    ("duplicate product_id in dim_product", "INSERT INTO dw.dim_product (product_id, is_current) VALUES ('P1', TRUE)"),
    ("NULL order_id / customer_sk / order_date_key in fact_orders", "UPDATE dw.fact_orders SET customer_sk = NULL WHERE order_id = 'ORD1'"),
    ("NULL event_id / customer_sk / event_date_key in fact_events", "UPDATE dw.fact_events SET event_id = NULL WHERE event_id = 'EVT1'"),
    ("fact_orders -> dim_date (order_date_key)", "UPDATE dw.fact_orders SET order_date_key = 19000101 WHERE order_id = 'ORD1'"),
    ("fact_orders -> dim_customer / channel / device / payment / shipping", "DELETE FROM dw.dim_customer WHERE customer_id = 'C1'"),
    ("fact_graph_edges: customer key filled on a PRODUCT node (routing error)",
     "UPDATE dw.fact_graph_edges SET from_customer_sk = (SELECT MIN(customer_sk) FROM dw.dim_customer) WHERE edge_id = 'EDGE3'"),
    ("fact_graph_edges: Customer from-node without from_customer_sk", "UPDATE dw.fact_graph_edges SET from_customer_sk = NULL WHERE edge_id = 'EDGE1'"),
    ("negative order_total_usd / subtotal_usd", "UPDATE dw.fact_orders SET order_total_usd = -5 WHERE order_id = 'ORD1'"),
    ("shipped before ordered", "UPDATE dw.fact_orders SET ship_date_key = 20240101 WHERE order_id = 'ORD1'"),
    ("order total != subtotal-discount+shipping+tax (> 0.05)", "UPDATE dw.fact_orders SET order_total_usd = 999.99 WHERE order_id = 'ORD1'"),
    ("discount_rate or tax_rate outside 0..1", "UPDATE dw.fact_orders SET tax_rate = 1.5 WHERE order_id = 'ORD1'"),
    ("events: negative cart value / latency / dwell", "UPDATE dw.fact_events SET latency_ms = -1 WHERE event_id = 'EVT1'"),
    ("edges: quantity <= 0 or unit_price <= 0", "UPDATE dw.fact_graph_edges SET quantity = 0 WHERE edge_id = 'EDGE1'"),
    ("edges: edge_strength outside 0..1", "UPDATE dw.fact_graph_edges SET edge_strength = 7 WHERE edge_id = 'EDGE1'"),
    ("unsupported relationship type", "UPDATE dw.fact_graph_edges SET relationship = 'BOGUS' WHERE edge_id = 'EDGE1'"),
    ("edges.order_id not present in fact_orders", "UPDATE dw.fact_graph_edges SET order_id = 'ORD404' WHERE edge_id = 'EDGE1'"),
    ("fact_events with product in staging but NULL product_sk", "UPDATE dw.fact_events SET product_sk = NULL WHERE event_id = 'EVT1'"),
]


@pytest.mark.parametrize("check,tamper", TAMPER, ids=[t[0][:60] for t in TAMPER])
def test_each_tampering_is_caught_by_the_named_check(clean, check, tamper):
    assert results(clean)[check] == 0
    clean.exec(tamper)
    assert results(clean)[check] > 0, f"{check!r} did not notice: {tamper}"


def test_duplicate_in_staging_is_caught(clean):
    clean.exec("INSERT INTO stg.orders_raw SELECT * FROM stg.orders_raw WHERE order_id = 'ORD1'")
    assert results(clean)["duplicate order_id in stg.orders_raw"] == 1


def test_every_data_quality_check_has_a_tampering_that_fails_it(clean):
    covered = {c for c, _ in TAMPER} | {"duplicate order_id in stg.orders_raw", "fact_orders -> dim_date (ship_date_key)", "fact_events -> dim_date",
                                        "fact_graph_edges -> dim_date", "NULL edge_id / event_date_key in fact_graph_edges",
                                        "fact_graph_edges: Product to-node without to_product_sk"}
    assert covered >= set(results(clean))


@pytest.mark.parametrize("check,tamper", [
    ("fact_orders -> dim_date (ship_date_key)", "UPDATE dw.fact_orders SET ship_date_key = 20300101 WHERE order_id = 'ORD1'"),
    ("fact_events -> dim_date", "UPDATE dw.fact_events SET event_date_key = 19000101 WHERE event_id = 'EVT1'"),
    ("fact_graph_edges -> dim_date", "UPDATE dw.fact_graph_edges SET event_date_key = 19000101 WHERE edge_id = 'EDGE1'"),
    ("NULL edge_id / event_date_key in fact_graph_edges", "UPDATE dw.fact_graph_edges SET event_date_key = NULL WHERE edge_id = 'EDGE1'"),
    ("fact_graph_edges: Product to-node without to_product_sk", "UPDATE dw.fact_graph_edges SET to_product_sk = NULL WHERE edge_id = 'EDGE3'"),
])
def test_remaining_checks_are_also_caught(clean, check, tamper):
    clean.exec(tamper)
    assert results(clean)[check] > 0


def test_control_total_comparison_notices_a_changed_amount(clean):
    stg = float(clean.scalar("SELECT SUM(order_total_usd) FROM stg.orders_raw"))
    assert abs(stg - float(clean.scalar("SELECT SUM(order_total_usd) FROM dw.fact_orders"))) < 0.01
    clean.exec("UPDATE dw.fact_orders SET order_total_usd = order_total_usd + 10 WHERE order_id = 'ORD1'")
    assert abs(stg - float(clean.scalar("SELECT SUM(order_total_usd) FROM dw.fact_orders"))) >= 0.01
