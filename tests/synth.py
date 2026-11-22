"""Small synthetic data sets (no real customer data) for the regression tests."""
import copy

import pandas as pd


def raw_order(**kw):
    row = dict(order_id="ORD1", customer_id="C1", order_datetime="2025-01-10 10:00:00", ship_datetime="2025-01-12 10:00:00",
               channel="web", device_type="ios", browser="safari", country="US", state="CA", payment_method="card", campaign="spring",
               primary_category="Books", num_distinct_items=2, subtotal_usd=100.0, discount_rate=0.1, discount_amount_usd=10.0,
               shipping_method="standard", shipping_cost_usd=5.0, tax_rate=0.08, tax_amount_usd=7.2, order_total_usd=102.2,
               order_weight_kg=1.5, delivery_days=2, on_time_delivery=True, authorization_approved=True, returned=False)
    row.update(kw)
    return row


def raw_event(**kw):
    row = dict(event_id="EVT1", customer_id="C1", session_id="S1", event_type="product_view", event_ts="2025-01-10 09:00:00",
               device_type="ios", browser="safari", os="ios", referrer="direct", country="US", state="CA", ab_variant="A",
               is_logged_in=True, page_depth=3, latency_ms=120, dwell_seconds=30, cart_value_usd=0.0, discount_rate=0.0,
               fraud_score=0.01, payment_outcome=None, sequence_num=1, product_id="P1", category="Books", promo_code="NONE")
    row.update(kw)
    return row


def raw_edge(**kw):
    row = dict(edge_id="EDGE1", from_node_id="C1", from_node_type="Customer", to_node_id="P1", to_node_type="Product",
               relationship="VIEWED", timestamp="2025-01-10 09:05:00", order_id=None, category="Books", customer_segment="Gold",
               edge_strength=0.5, price_bucket="low", region="WEST", state="CA", campaign="spring", same_household=False,
               prior_interactions=0, dwell_seconds=20, product_id="P1", unit_price_usd=19.99, quantity=1, returned_flag=False,
               auth_approved=True)
    row.update(kw)
    return row


class Dataset:
    """Three lists of raw rows with helpers to change them like a source system would."""

    def __init__(self):
        self.orders = [raw_order(),
                       raw_order(order_id="ORD2", customer_id="C2", channel="ios_app", order_datetime="2025-01-11 08:00:00",
                                 ship_datetime="2025-01-13 08:00:00", campaign=None, subtotal_usd=50.0, discount_amount_usd=0.0,
                                 discount_rate=0.0, shipping_cost_usd=0.0, tax_amount_usd=1.0, tax_rate=0.02, order_total_usd=51.0)]
        self.events = [raw_event(),
                       raw_event(event_id="EVT2", customer_id="C2", session_id="S2", event_type="add_to_cart", product_id="P2",
                                 category="Toys", event_ts="2025-01-11 07:00:00", ab_variant="B"),
                       raw_event(event_id="EVT3", customer_id="C1", event_type="page_view", product_id=None, category=None,
                                 event_ts="2025-01-10 09:30:00", sequence_num=2)]
        self.edges = [raw_edge(),
                      raw_edge(edge_id="EDGE2", from_node_id="C2", to_node_id="P2", relationship="PURCHASED", order_id="ORD2",
                               category="Toys", product_id="P2", quantity=2, unit_price_usd=25.0, timestamp="2025-01-11 08:05:00"),
                      raw_edge(edge_id="EDGE3", from_node_id="P1", from_node_type="Product", to_node_id="P2", to_node_type="Product",
                               relationship="ALSO_BOUGHT_WITH", product_id="P1", customer_segment=None, timestamp="2025-01-11 09:00:00"),
                      raw_edge(edge_id="EDGE4", from_node_id="C1", to_node_id="C2", to_node_type="Customer",
                               relationship="REFERRED_FRIEND", product_id=None, category=None, price_bucket=None, unit_price_usd=1.0,
                               timestamp="2025-01-12 09:00:00")]

    def copy(self):
        return copy.deepcopy(self)

    @staticmethod
    def _find(rows, key, value):
        return next(r for r in rows if r[key] == value)

    def order(self, order_id):
        return self._find(self.orders, "order_id", order_id)

    def event(self, event_id):
        return self._find(self.events, "event_id", event_id)

    def edge(self, edge_id):
        return self._find(self.edges, "edge_id", edge_id)

    def frames(self):
        return pd.DataFrame(self.orders), pd.DataFrame(self.events), pd.DataFrame(self.edges)
