# Public definitions v2

Amounts are integer CNY. net_revenue_cny is computed per row as booked_revenue_cny-refund_cny; profit=sum(net_revenue_cny)-sum(cost_cny); margin_pct=100*profit/revenue, rounded to four decimals. Risk uses the UNROUNDED ratio profit/revenue < 0.20. Never use booked revenue as net revenue.
