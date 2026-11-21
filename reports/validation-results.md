# Validation Results

## Reconciliation
| Dataset | Source CSV | Source DB | Extracted | Transformed | Staging | Final Fact | Status |
|---|---|---|---|---|---|---|---|
| Orders | 2500 | 2500 | 2500 | 2500 | 2500 | 2500 | PASS (no record lost or added) |
| Events | 2500 | 2500 | 2500 | 2500 | 2500 | 2500 | PASS (no record lost or added) |
| Graph edges | 2500 | 2500 | 2500 | 2500 | 2500 | 2500 | PASS (no record lost or added) |

## Control totals
| control total | CSV | staging | fact | match |
|---|---|---|---|---|
| orders: SUM(order_total_usd) | 1039417.69 | 1039417.69 | 1039417.69 | True |
| orders: COUNT(DISTINCT customer_id) | 2460.0 | 2460.0 | 2460.0 | True |
| events: SUM(cart_value_usd) | 164886.52 | 164886.52 | 164886.52 | True |
| events: COUNT(DISTINCT product_id) | 1276.0 | 1276.0 | 1276.0 | True |
| edges: SUM(unit_price_usd*quantity) | 506521.31 | 506521.31 | 506521.31 | True |

## Data-quality checks
| check | offending rows | result |
|---|---|---|
| duplicate order_id in stg.orders_raw | 0 | PASS |
| duplicate order_id in dw.fact_orders | 0 | PASS |
| duplicate event_id in dw.fact_events | 0 | PASS |
| duplicate edge_id in dw.fact_graph_edges | 0 | PASS |
| duplicate customer_id in dim_customer | 0 | PASS |
| duplicate product_id in dim_product | 0 | PASS |
| NULL order_id / customer_sk / order_date_key in fact_orders | 0 | PASS |
| NULL event_id / customer_sk / event_date_key in fact_events | 0 | PASS |
| NULL edge_id / event_date_key in fact_graph_edges | 0 | PASS |
| fact_orders -> dim_date (order_date_key) | 0 | PASS |
| fact_orders -> dim_date (ship_date_key) | 0 | PASS |
| fact_events -> dim_date | 0 | PASS |
| fact_graph_edges -> dim_date | 0 | PASS |
| fact_orders -> dim_customer / channel / device / payment / shipping | 0 | PASS |
| fact_events with product in staging but NULL product_sk | 0 | PASS |
| fact_graph_edges: Customer from-node without from_customer_sk | 0 | PASS |
| fact_graph_edges: Product to-node without to_product_sk | 0 | PASS |
| fact_graph_edges: customer key filled on a PRODUCT node (routing error) | 0 | PASS |
| negative order_total_usd / subtotal_usd | 0 | PASS |
| shipped before ordered | 0 | PASS |
| discount_rate or tax_rate outside 0..1 | 0 | PASS |
| order total != subtotal-discount+shipping+tax (> 0.05) | 0 | PASS |
| events: negative cart value / latency / dwell | 0 | PASS |
| edges: quantity <= 0 or unit_price <= 0 | 0 | PASS |
| edges: edge_strength outside 0..1 | 0 | PASS |
| unsupported relationship type | 0 | PASS |
| edges.order_id not present in fact_orders | 0 | PASS |

## Row counts
| table_name | n |
|---|---|
| public.dw_dim_ab_variant | 2 |
| public.dw_dim_browser | 5 |
| public.dw_dim_campaign | 6 |
| public.dw_dim_channel | 5 |
| public.dw_dim_customer | 7057 |
| public.dw_dim_date | 552 |
| public.dw_dim_device | 3 |
| public.dw_dim_os | 5 |
| public.dw_dim_payment_method | 5 |
| public.dw_dim_product | 3360 |
| public.dw_dim_referrer | 6 |
| public.dw_dim_shipping_method | 3 |
| public.dw_fact_events | 2500 |
| public.dw_fact_graph_edges | 2500 |
| public.dw_fact_orders | 2500 |
| public.stg_edges_raw | 2500 |
| public.stg_events_raw | 2500 |
| public.stg_orders_raw | 2500 |

