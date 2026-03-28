from dataclasses import dataclass, field
import uuid
from typing import Literal, Self
from database_interface import Table, Column

@dataclass(slots=True)
class LimitOrder:
    trade_pair:       str
    side:             Literal["SELL", "BUY"]
    limit_price:      float
    post_only:        bool
    usd_order_size:   float           = None

    order_id:         str             = field(init=False, default=None)
    client_id:        str             = field(init=False, default=None)
    usd_after_fee:    str             = field(init=False, default=None)
    fee:              str             = field(init=False, default=None)
    usd_amount:       str             = field(init=False, default=None)
    crypto_amount:    str             = field(init=False, default=None)
    status:           str             = field(init=False, default=None)
    created:          str             = field(init=False, default=None)
    fill_time:        str             = field(init=False, default=None)

    repost_order_id:  str             = field(init=False, default=None)
    repost_side:      str             = field(init=False, default=None)
    repost_price:     str             = field(init=False, default=None)

    def __post_init__(self):
        self.client_id                = str(uuid.uuid4())

    @classmethod
    def from_tuple(cls, record:tuple) -> Self:
        order                         = cls(record[2], 
                                            record[3], 
                                            record[4], 
                                            record[5], 
                                            record[6])
        
        order.order_id                = record[0]
        order.client_id               = record[1]
        order.usd_after_fee           = record[7]
        order.fee                     = record[8]
        order.usd_amount              = record[9]
        order.crypto_amount           = record[10]
        order.status                  = record[11]
        order.created                 = record[12]
        order.fill_time               = record[13]
        order.repost_order_id         = record[14]
        order.repost_side             = record[15]
        order.repost_price            = record[16]

        return order

    @classmethod
    def from_api(cls, resp_payload:dict) -> Self:
        order                         = cls(resp_payload["product_id"], 
                                            resp_payload["side"], 
                                            resp_payload["order_configuration"]["limit_limit_gtc"]["limit_price"], 
                                            resp_payload["order_configuration"]["limit_limit_gtc"]["post_only"], 
                                            None)
        
        order.order_id                = resp_payload["order_id"]
        order.client_id               = resp_payload["client_order_id"]
        order.usd_after_fee           = resp_payload["total_value_after_fees"]
        order.fee                     = resp_payload["total_fees"]
        order.usd_amount              = resp_payload["filled_value"]
        order.crypto_amount           = resp_payload["filled_size"]
        order.status                  = resp_payload["status"]
        order.created                 = resp_payload["created_time"]
        order.fill_time               = resp_payload["last_fill_time"]

        return order


    def payload(self, precision:int) -> dict:
        return {"client_order_id":    self.client_id.__str__(), 
                "product_id":         self.trade_pair, 
                "side":               self.side, 
                "order_configuration": {"limit_limit_gtc": {"quote_size":   str(self.usd_order_size), 
                                                            "limit_price":  format(self.limit_price, f'.{precision}f'), 
                                                            "post_only":    self.post_only}}}

    def build_repost(self, trade_pair:str, usd_size:int, precision:float, rebuy_margin:float, resell_margin:float) -> Self:
        match self.side:
            case "BUY":
                resell_price          = round(self.limit_price * resell_margin, precision)
                return LimitOrder(trade_pair, "SELL", resell_price, True, usd_size)
            case "SELL":
                rebuy_price           = round(self.limit_price * rebuy_margin, precision)
                return LimitOrder(trade_pair, "BUY", rebuy_price, True, usd_size)

    def posted_order(self, resp_paylod:dict) -> None:
        self.order_id                 = resp_paylod["success_response"]["order_id"]
    
    def update_status(self, resp_paylod:dict) -> None:
        self.usd_after_fee            = resp_paylod["total_value_after_fees"]
        self.fee                      = resp_paylod["total_fees"]
        self.usd_amount               = resp_paylod["filled_value"]
        self.crypto_amount            = resp_paylod["filled_size"]
        self.status                   = resp_paylod["status"]
        self.created                  = resp_paylod["created_time"]
        self.fill_time                = resp_paylod["last_fill_time"]

    def reposted_info(self, resp_paylod:dict) -> None:
        self.repost_order_id          = resp_paylod["success_response"]["order_id"]
        self.repost_side              = resp_paylod["success_response"]["side"]
        self.repost_price             = resp_paylod["order_configuration"]["limit_limit_gtc"]["limit_price"]

    def to_tuple(self) -> tuple:
        return (self.order_id, 
                self.client_id, 
                self.trade_pair, 
                self.side, 
                self.limit_price, 
                self.post_only, 
                self.usd_order_size, 
                self.usd_after_fee, 
                self.fee, 
                self.usd_amount, 
                self.crypto_amount, 
                self.status, 
                self.created, 
                self.fill_time, 
                self.repost_order_id, 
                self.repost_side, 
                self.repost_price)
    
    @staticmethod
    def table(name:str) -> Table:
        return Table(name, LimitOrder.schema())
    @staticmethod
    def schema() -> list[Column]:
        return [Column("order_id", "text").is_primary_key(), 
                Column("client_order_id", "text"), 
                Column("trade_pair", "text"), 
                Column("side", "text"), 
                Column("limit_price", "text"), 
                Column("post_only", "boolean"), 
                Column("usd_order_size", "text"), 
                Column("usd_after_fee", "text"), 
                Column("fees", "text"), 
                Column("usd_amount", "text"), 
                Column("crypto_amount", "text"), 
                Column("status", "text"), 
                Column("create_time", "timestamp with time zone"), 
                Column("fill_time", "timestamp with time zone"), 
                Column("reposted_order_id", "text"), 
                Column("reposted_side", "text"), 
                Column("reposted_at_price", "text")]

