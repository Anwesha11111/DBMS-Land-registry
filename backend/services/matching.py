# backend/services/matching.py
"""
Matching Engine for Land Exchange.
Implements price-time priority matching with zero commission.
DECISION 3: Match when best Bid >= Ask. Trade price = price of the earlier (resting) order.
Only matches if plot is Clear. Self-trades are strictly prevented.
Hands matched trade directly to Two-Phase Commit settlement.
"""
import uuid
import datetime
import logging
from typing import Dict, Any, Optional
from backend.db.connection import get_pg_connection, is_mock_mode
from backend.db.mock_store import mock_db
from backend.services.settlement import settle_trade_2pc
from backend.services.audit import log_audit_event

logger = logging.getLogger(__name__)

def attempt_match_for_plot(plot_id: str) -> Optional[Dict[str, Any]]:
    """
    Evaluates order book for a plot and matches orders if best Bid >= Ask.
    Guarantees atomic row-locking to prevent concurrent double-matches.
    """
    if is_mock_mode():
        # Mock mode matching
        plot_reg = None
        for r in mock_db.registry.values():
            if r["plot_id"] == plot_id:
                plot_reg = r
                break
        if not plot_reg or plot_reg["legal_status"] != "Clear":
            return None

        # Find open Ask
        open_asks = [
            o for o in mock_db.order_book.values()
            if o["plot_id"] == plot_id and o["order_type"] == "ASK" and o["status"] == "Open"
        ]
        if not open_asks:
            return None
        active_ask = open_asks[0]

        # Find open Bids sorted by price desc, timestamp asc
        open_bids = [
            o for o in mock_db.order_book.values()
            if o["plot_id"] == plot_id and o["order_type"] == "BID" and o["status"] == "Open"
        ]
        if not open_bids:
            return None

        # Sort: highest price first, then earliest timestamp
        open_bids.sort(key=lambda b: (-float(b["price"]), b["order_timestamp"]))
        best_bid = open_bids[0]

        # Prevent self-trade
        if best_bid["trader_id"] == active_ask["trader_id"]:
            return None

        # Check match condition: best Bid >= Ask
        if float(best_bid["price"]) < float(active_ask["price"]):
            return None

        # Trade price = resting order price (earlier order's price)
        if best_bid["order_timestamp"] < active_ask["order_timestamp"]:
            trade_price = float(best_bid["price"])
        else:
            trade_price = float(active_ask["price"])

        trade_id = f"trd_{uuid.uuid4().hex[:12]}"
        gid = f"tx_{trade_id}"

        trade_record = {
            "trade_id": trade_id,
            "bid_order_id": best_bid["order_id"],
            "ask_order_id": active_ask["order_id"],
            "plot_id": plot_id,
            "price": trade_price,
            "status": "Pending",
            "gid": gid,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        mock_db.trades[trade_id] = trade_record

        # Hand to 2PC Settlement
        settle_result = settle_trade_2pc(
            trade_id=trade_id,
            buyer_id=best_bid["trader_id"],
            seller_id=active_ask["trader_id"],
            plot_id=plot_id,
            price=trade_price,
            bid_order_id=best_bid["order_id"],
            ask_order_id=active_ask["order_id"],
            seller_signature=active_ask.get("signature"),
            buyer_signature=best_bid.get("signature")
        )

        return {
            "matched": True,
            "trade_id": trade_id,
            "trade_price": trade_price,
            "settlement": settle_result
        }

    # PostgreSQL live matching with row locking
    try:
        with get_pg_connection() as conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                # Confirm plot status is Clear
                cur.execute(
                    "SELECT legal_status, current_owner_id FROM registry_entry WHERE plot_id = %s FOR UPDATE;",
                    (plot_id,)
                )
                reg_row = cur.fetchone()
                if not reg_row or reg_row[0] != 'Clear':
                    conn.rollback()
                    return None
                current_owner = reg_row[1]

                # Lock the Open Ask for this plot
                cur.execute(
                    """
                    SELECT order_id, trader_id, price, order_timestamp, signature
                    FROM order_book
                    WHERE plot_id = %s AND order_type = 'ASK' AND status = 'Open'
                    FOR UPDATE
                    LIMIT 1;
                    """,
                    (plot_id,)
                )
                ask_row = cur.fetchone()
                if not ask_row:
                    conn.rollback()
                    return None

                ask_id, ask_trader, ask_price, ask_time, ask_sig = (
                    ask_row[0], ask_row[1], float(ask_row[2]), ask_row[3], ask_row[4]
                )

                # Lock the best Open Bid (price DESC, order_timestamp ASC)
                cur.execute(
                    """
                    SELECT order_id, trader_id, price, order_timestamp, signature
                    FROM order_book
                    WHERE plot_id = %s AND order_type = 'BID' AND status = 'Open' AND trader_id != %s
                    ORDER BY price DESC, order_timestamp ASC
                    FOR UPDATE
                    LIMIT 1;
                    """,
                    (plot_id, ask_trader)
                )
                bid_row = cur.fetchone()
                if not bid_row:
                    conn.rollback()
                    return None

                bid_id, bid_trader, bid_price, bid_time, bid_sig = (
                    bid_row[0], bid_row[1], float(bid_row[2]), bid_row[3], bid_row[4]
                )

                # Match condition: Bid >= Ask
                if bid_price < ask_price:
                    conn.rollback()
                    return None

                # DECISION 3: Trade price = price of the earlier (resting) order
                trade_price = bid_price if bid_time < ask_time else ask_price

                trade_id = f"trd_{uuid.uuid4().hex[:12]}"
                gid = f"tx_{trade_id}"

                cur.execute(
                    """
                    INSERT INTO trade (trade_id, bid_order_id, ask_order_id, plot_id, price, status, gid)
                    VALUES (%s, %s, %s, %s, %s, 'Pending', %s);
                    """,
                    (trade_id, bid_id, ask_id, plot_id, trade_price, gid)
                )
            conn.commit()

        # Hand over to 2PC Settlement
        settle_result = settle_trade_2pc(
            trade_id=trade_id,
            buyer_id=bid_trader,
            seller_id=ask_trader,
            plot_id=plot_id,
            price=trade_price,
            bid_order_id=bid_id,
            ask_order_id=ask_id,
            seller_signature=ask_sig,
            buyer_signature=bid_sig
        )

        return {
            "matched": True,
            "trade_id": trade_id,
            "trade_price": trade_price,
            "settlement": settle_result
        }

    except Exception as e:
        logger.error(f"Error executing matching engine on plot {plot_id}: {e}")
        return None
