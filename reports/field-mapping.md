# Source-to-Target Field Mapping

| Source System | Source Field | Source Type | Transformation | Target Table (dw.) | Target Column |
|---|---|---|---|---|---|
| PostgreSQL | order_id | object | trim, upper-case, validate ^ORD\d+$, must be unique | fact_orders | order_id |
| PostgreSQL | customer_id | object | trim, upper-case, validate ^C\d+$ (conformed key shared by all 3 sources) | dim_customer | customer_id |
| PostgreSQL | customer_id | object | surrogate-key lookup (current row) | fact_orders | customer_sk |
| PostgreSQL | order_datetime | object | parse timestamp; derive YYYYMMDD | fact_orders | order_date_key (-> dim_date.date_key) |
| PostgreSQL | ship_datetime | object | parse timestamp; derive YYYYMMDD | fact_orders | ship_date_key (-> dim_date.date_key) |
| PostgreSQL | order_datetime/ship_datetime | - | distinct dates | dim_date | date_actual, year, quarter, month, day, week_of_year, day_of_week, is_weekend |
| PostgreSQL | channel | object | trim, lower-case; distinct -> surrogate key | dim_channel / fact_orders | channel / channel_sk |
| PostgreSQL | device_type | object | trim, lower-case; distinct -> surrogate key | dim_device / fact_orders | device_type / device_sk |
| PostgreSQL | browser | object | trim; distinct -> surrogate key | dim_browser / fact_orders | browser / browser_sk |
| PostgreSQL | country, state | - | trim, upper-case; customer geography (orders take precedence over events) | dim_customer | country, state |
| PostgreSQL | payment_method | object | trim, lower-case; distinct -> surrogate key | dim_payment_method / fact_orders | payment_method / payment_method_sk |
| PostgreSQL | campaign | object | trim; NULL stays NULL; distinct -> surrogate key | dim_campaign / fact_orders | campaign / campaign_sk |
| PostgreSQL | shipping_method | object | trim, lower-case; distinct -> surrogate key | dim_shipping_method / fact_orders | shipping_method / shipping_method_sk |
| PostgreSQL | primary_category | object | trim (degenerate attribute) | fact_orders | primary_category |
| PostgreSQL | num_distinct_items | int64 | numeric/boolean conversion; rounded to DDL precision | fact_orders | num_distinct_items |
| PostgreSQL | subtotal_usd | float64 | numeric/boolean conversion; rounded to DDL precision | fact_orders | subtotal_usd |
| PostgreSQL | discount_rate | float64 | numeric/boolean conversion; rounded to DDL precision | fact_orders | discount_rate |
| PostgreSQL | discount_amount_usd | float64 | numeric/boolean conversion; rounded to DDL precision | fact_orders | discount_amount_usd |
| PostgreSQL | shipping_cost_usd | float64 | numeric/boolean conversion; rounded to DDL precision | fact_orders | shipping_cost_usd |
| PostgreSQL | tax_rate | float64 | numeric/boolean conversion; rounded to DDL precision | fact_orders | tax_rate |
| PostgreSQL | tax_amount_usd | float64 | numeric/boolean conversion; rounded to DDL precision | fact_orders | tax_amount_usd |
| PostgreSQL | order_total_usd | float64 | numeric/boolean conversion; rounded to DDL precision | fact_orders | order_total_usd |
| PostgreSQL | order_weight_kg | float64 | numeric/boolean conversion; rounded to DDL precision | fact_orders | order_weight_kg |
| PostgreSQL | delivery_days | int64 | numeric/boolean conversion; rounded to DDL precision | fact_orders | delivery_days |
| PostgreSQL | on_time_delivery | bool | numeric/boolean conversion; rounded to DDL precision | fact_orders | on_time_delivery |
| PostgreSQL | authorization_approved | bool | numeric/boolean conversion; rounded to DDL precision | fact_orders | authorization_approved |
| PostgreSQL | returned | bool | numeric/boolean conversion; rounded to DDL precision | fact_orders | returned |
| Cassandra | event_id | object | trim, upper-case, validate ^EVT\d+$, unique | fact_events | event_id |
| Cassandra | customer_id | object | trim, upper-case, validate ^C\d+$ | dim_customer | customer_id |
| Cassandra | customer_id | object | surrogate-key lookup | fact_events | customer_sk |
| Cassandra | session_id | object | trim, upper-case | fact_events | session_id |
| Cassandra | event_type | object | trim, lower-case | fact_events | event_type |
| Cassandra | event_ts | object | parse timestamp; derive YYYYMMDD | fact_events | event_date_key (-> dim_date.date_key) |
| Cassandra | device_type | object | trim, lower-case; distinct -> surrogate key | dim_device / fact_events | device_type / device_sk |
| Cassandra | browser | object | trim; distinct -> surrogate key | dim_browser / fact_events | browser / browser_sk |
| Cassandra | os | object | trim; distinct -> surrogate key | dim_os / fact_events | os / os_sk |
| Cassandra | referrer | object | trim, lower-case; distinct -> surrogate key | dim_referrer / fact_events | referrer / referrer_sk |
| Cassandra | country, state | - | fallback customer geography when no order exists | dim_customer | country, state |
| Cassandra | ab_variant | object | trim, upper-case; distinct -> surrogate key | dim_ab_variant / fact_events | ab_variant / ab_variant_sk |
| Cassandra | is_logged_in | bool | boolean conversion; latest event per customer | dim_customer | is_logged_in |
| Cassandra | product_id | object | trim, upper-case, validate ^P\d+$; surrogate-key lookup (NULL when event has no product) | dim_product / fact_events | product_id / product_sk |
| Cassandra | category | object | trim; latest per product | dim_product / fact_events | category / category |
| Cassandra | page_depth | int64 | numeric conversion / lower-case (payment_outcome) / upper-case (promo_code) | fact_events | page_depth |
| Cassandra | latency_ms | int64 | numeric conversion / lower-case (payment_outcome) / upper-case (promo_code) | fact_events | latency_ms |
| Cassandra | dwell_seconds | int64 | numeric conversion / lower-case (payment_outcome) / upper-case (promo_code) | fact_events | dwell_seconds |
| Cassandra | cart_value_usd | float64 | numeric conversion / lower-case (payment_outcome) / upper-case (promo_code) | fact_events | cart_value_usd |
| Cassandra | discount_rate | float64 | numeric conversion / lower-case (payment_outcome) / upper-case (promo_code) | fact_events | discount_rate |
| Cassandra | fraud_score | float64 | numeric conversion / lower-case (payment_outcome) / upper-case (promo_code) | fact_events | fraud_score |
| Cassandra | payment_outcome | object | numeric conversion / lower-case (payment_outcome) / upper-case (promo_code) | fact_events | payment_outcome |
| Cassandra | sequence_num | int64 | numeric conversion / lower-case (payment_outcome) / upper-case (promo_code) | fact_events | sequence_num |
| Cassandra | promo_code | object | numeric conversion / lower-case (payment_outcome) / upper-case (promo_code) | fact_events | promo_code |
| Neo4j | edge_id | object | relationship property; trim, upper-case, validate ^EDGE\d+$, unique | fact_graph_edges | edge_id |
| Neo4j | from_node_id + from_node_type | - | type=Customer -> customer_sk lookup; type=Product -> product_sk lookup | fact_graph_edges | from_customer_sk / from_product_sk |
| Neo4j | to_node_id + to_node_type | - | type=Customer -> customer_sk lookup; type=Product -> product_sk lookup | fact_graph_edges | to_customer_sk / to_product_sk |
| Neo4j | from_node_id / to_node_id (Customer nodes) | - | distinct customer ids | dim_customer | customer_id |
| Neo4j | from_node_id / to_node_id / product_id (Product nodes) | - | distinct product ids | dim_product | product_id |
| Neo4j | relationship | object | upper-case, whitelisted relationship type | fact_graph_edges | relationship |
| Neo4j | timestamp | object | parse timestamp; derive YYYYMMDD | fact_graph_edges | event_date_key (-> dim_date.date_key) |
| Neo4j | order_id | object | trim, upper-case; NULL when no order (kept as degenerate key) | fact_graph_edges | order_id |
| Neo4j | category | object | trim | fact_graph_edges / dim_product | category |
| Neo4j | customer_segment | object | trim; latest per customer (Customer source nodes) | dim_customer / fact_graph_edges | customer_segment |
| Neo4j | price_bucket | object | trim; latest per product | dim_product / fact_graph_edges | price_bucket |
| Neo4j | unit_price_usd | float64 | numeric conversion; latest per product -> current_unit_price_usd | dim_product / fact_graph_edges | current_unit_price_usd / unit_price_usd |
| Neo4j | campaign | object | trim; distinct -> surrogate key | dim_campaign / fact_graph_edges | campaign / campaign_sk |
| Neo4j | edge_strength | float64 | type conversion | fact_graph_edges | edge_strength |
| Neo4j | region | object | type conversion | fact_graph_edges | region |
| Neo4j | state | object | type conversion | fact_graph_edges | state |
| Neo4j | prior_interactions | int64 | type conversion | fact_graph_edges | prior_interactions |
| Neo4j | dwell_seconds | int64 | type conversion | fact_graph_edges | dwell_seconds |
| Neo4j | quantity | int64 | type conversion | fact_graph_edges | quantity |
| Neo4j | returned_flag | bool | type conversion | fact_graph_edges | returned_flag |
| Neo4j | auth_approved | bool | type conversion | fact_graph_edges | auth_approved |
| Neo4j | same_household | bool | boolean conversion | stg.edges_raw only | same_household (not carried into the fact: no DDL column) |
