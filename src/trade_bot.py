import tomllib
from typing import Literal
from database_interface import SQLite, Where
from dataclasses import dataclass, field
from .order import LimitOrder
from .coinbase import Coinbase
from datetime import timedelta

import logging

def get_logger(name="app", filename="app.log"):
    logger                                   = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    console                                  = logging.StreamHandler()
    file                                     = logging.FileHandler(filename)
    fmt                                      = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    console.setFormatter(fmt)
    file.setFormatter(fmt)

    logger.addHandler(console)
    logger.addHandler(file)

    return logger

@dataclass(slots=True)
class TradeBot:
    config_path:     str
    api_key_name:    str
    api_key_secret:  str
    target_asset:    str
    db:              SQLite                  = field(init=False)
    coinbase:        Coinbase                = field(init=False)
    log:             logging.Logger          = field(init=False)
    orders:          dict[str, LimitOrder]   = field(init=False, default_factory=dict)
    config:          dict                    = field(init=False, default=None)

    order_size:      int                     = field(init=False, default=None)
    check_freq:      int                     = field(init=False, default=None)
    trade_pair:      str                     = field(init=False, default=None)
    spacing:         float                   = field(init=False, default=None)
    precision:       float                   = field(init=False, default=None)
    reset_delta:     float                   = field(init=False, default=None)
    resell_ratio:    float                   = field(init=False, default=None)
    sell_buffer:     float                   = field(init=False, default=None)
    rebuy_ratio:     float                   = field(init=False, default=None)
    buy_buffer:      float                   = field(init=False, default=None)

    current_orders                           = "open_orders"
    executed_orders                          = "executed_orders"

    def __post_init__(self):
        self.db                              = SQLite("trades.sqlite")
        self.log                             = get_logger()
        with self.db.cursor() as cur:
            self.db.create_table(cur, LimitOrder.table(self.current_orders))
            self.db.create_table(cur, LimitOrder.table(self.executed_orders))
            self.orders                      = {order[0]:LimitOrder.from_tuple(order) for order in self.db.select(cur, self.current_orders)}

        with open(self.config_path, "rb") as f:
            config                           = tomllib.load(f)

        self.coinbase                        = Coinbase(self.api_key_name, self.api_key_secret)
        self.config                          = config
        self.order_size                      = config["order_size"]
        self.check_freq                      = timedelta(seconds=config["check_freq_sec"])
        self.trade_pair                      = config[self.target_asset]["trading_pair"]
        self.spacing                         = config[self.target_asset]["spacing"]
        self.precision                       = config[self.target_asset]["asset_precision"]
        self.reset_delta                     = config[self.target_asset]["reset_delta"]
        self.resell_ratio                    = config[self.target_asset]["resell_ratio"]
        self.sell_buffer                     = config[self.target_asset]["sell_buffer"]
        self.rebuy_ratio                     = config[self.target_asset]["rebuy_ratio"]
        self.buy_buffer                      = config[self.target_asset]["buy_buffer"]

        self.update_order_status()


    def initialize_positions(self, price:float, num_buys:int, num_sells:int) -> tuple[list, list]:
        buys                                 = [["BUY", round((price - self.buy_buffer) - (self.spacing * pos), self.precision)] for pos in range(num_buys)]
        sells                                = [["SELL", round((price + self.sell_buffer) + (self.spacing * pos), self.precision)] for pos in range(num_sells)]
        return buys, sells

    def create_order(self, side:Literal["BUY", "SELL"], usd_size:int, limit_price:float):
        order                                = LimitOrder(self.trade_pair, side, limit_price, True, usd_size)
        resp                                 = self.coinbase.place_order(order, self.precision)
        if resp.ok:
            order_info                       = resp.json()
            if order_info["success"]:
                order.posted_order(order_info)
                self.orders[order.order_id]  = order
                with self.db.cursor() as cur:
                    self.db.insert(cur, self.current_orders, [order.to_tuple()])
                self.log.info(f"Created {order.side} at price: {order.limit_price} for {order.usd_order_size}")
            else:
                self.log.info(f"Successful authentication for Order placement, but failed: {resp.text}")
        else:
            self.log.info(f"Order place failed: {resp.text}")

    def update_order_status(self):
        order_ids                            = list(self.orders.keys())
        if not order_ids:
            return
        
        resp                                 = self.coinbase.get_orders(order_ids)
        if resp.ok:
            orders                           = resp.json()
            for order in orders["orders"]:
                self.orders[order["order_id"]].update_status(order)
            with self.db.cursor() as cur:
                self.db.update(cur, self.current_orders, [o.to_tuple() for id, o in self.orders.items()], on_column="order_id")
        else:
            self.log.info(f"Failed to get Order Status Update: {resp.text}")

    def cancel_orders(self, cancel_what:Literal["ALL", "SELLS", "BUYS"]="ALL") -> int:
        match cancel_what:
            case "ALL":
                order_ids                    = [id for id, order in self.orders.items()]
            case "BUYS":
                order_ids                    = [id for id, order in self.orders.items() if order.side == "BUY"]
            case "SELLS":
                order_ids                    = [id for id, order in self.orders.items() if order.side == "SELL"]
        
        if not order_ids:
            return 0
        
        resp                                 = self.coinbase.cancel_orders(order_ids)
        if resp.ok:
            orders                           = resp.json()
            delete_ids                       = []
            for order in orders["results"]:
                delete_ids.append(self.orders.pop(order["order_id"]).order_id)

            with self.db.cursor() as cur:
                self.db.delete(cur, self.current_orders, Where("order_id").in_(delete_ids))
            
            for id in delete_ids:
                self.orders.pop(id, None)
        

        return len(delete_ids)

    def repost_filled(self):
        filled_orders:list[LimitOrder]       = []
        reposted_orders:list[LimitOrder]     = []
        for id, order in self.orders.items():
            if order.status == "FILLED":
                repost_sucess                = False
                repost_order                 = order.build_repost(self.trade_pair, self.order_size, self.precision, self.rebuy_ratio, self.resell_ratio)
                
                while not repost_sucess:
                    resp                     = self.coinbase.place_order(repost_order, self.precision)
                    if resp.ok:
                        repost_info:dict     = resp.json()
                        if repost_info["success"]:
                            order.reposted_info(repost_info)
                            repost_order.posted_order(repost_info)
                            filled_orders.append(order)
                            reposted_orders.append(repost_order)
                            repost_sucess    = True
                            self.log.info(f"Reposted {order.side} at {order.limit_price} to {order.repost_side} at {order.repost_price}")
                        else:
                            self.log.info(f"Successful authentication for Order repost, but failed: {resp.text}")
                            if repost_order.side == "SELL":
                                adjust       = repost_order.limit_price + self.spacing
                            elif repost_order.side == "BUY":
                                adjust       = repost_order.limit_price - self.spacing

                            self.log.info(f"Trying again with a {repost_order.side} price from {repost_order.limit_price} to {adjust}")
                            repost_order.limit_price = adjust
                    else:
                        self.log.info(f"Order repost failed: {resp.text}")
                
        with self.db.cursor() as cur:
            self.db.insert(cur, self.current_orders, [order.to_tuple() for order in reposted_orders])
            self.db.delete(cur, self.current_orders, Where("order_id").in_([order.order_id for order in filled_orders]))
            self.db.insert(cur, self.executed_orders, [order.to_tuple() for order in filled_orders])
            
        for order in filled_orders:
            self.orders.pop(order.order_id)
        for order in reposted_orders:
            self.orders[order.order_id] = order
                    

    def startup(self, buys:int, sells:int):
        if len(self.orders) != buys + sells:
            self.log.info(f"Mismatched orders: Tracking: {len(self.orders)} -- Expected positions: {buys + sells}, resetting")
            self.cancel_orders("ALL")
            resp = self.coinbase.get_product(self.trade_pair)
            if resp.ok:
                current_price = resp.json()["price"]
                buys, sells = self.initialize_positions(float(current_price), buys, sells)
                for buy in buys:
                    self.create_order(buy[0], self.order_size, buy[1])
                for sell in sells:
                    self.create_order(sell[0], self.order_size, sell[1])
        else:
            self.repost_filled(self.order_size)

    def readjust_positions(self):
        cur_sells                            = [order.limit_price for id, order in self.orders.items() if order.side == "SELL"]
        cur_buys                             = [order.limit_price for id, order in self.orders.items() if order.side == "BUY"]
        resp                                 = self.coinbase.get_product(self.trade_pair)
        if resp.ok:
            current_price                    = float(resp.json()["price"])

            if cur_sells:
                lowest_sell                  = min(cur_sells)
                if lowest_sell > current_price * (1 + self.reset_delta):
                    self.log.info(f"Resetting sell positions: {lowest_sell} > {current_price * (1 + self.reset_delta)}")
                    num_of_cancels           = self.cancel_orders("SELLS")
                    _, new_sells             = self.initialize_positions(current_price, 0, num_of_cancels)
                    for sell in new_sells:
                        self.create_order(sell[0], self.order_size, sell[1])
            
            if cur_buys:
                highest_buy                  = max(cur_buys)
                if highest_buy < current_price * (1 - self.reset_delta):
                    self.log.info(f"Resetting buy positions: {highest_buy} < {current_price * (1 - self.reset_delta)}")
                    num_of_cancels           = self.cancel_orders("BUYS")
                    new_buys, _              = self.initialize_positions(current_price, num_of_cancels, 0)
                    for buy in new_buys:
                        self.create_order(buy[0], self.order_size, buy[1])
            
        else:
            self.log.info(f"Failed to get Product info: {resp.text}")