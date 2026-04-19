import requests
from requests import Response
import json, time
import jwt
from cryptography.hazmat.primitives import serialization
import secrets
from dataclasses import dataclass, field
from .order import LimitOrder

@dataclass(slots=True)
class Coinbase:
    key_name:   str
    key_secret: str
    
    base_url               = "api.coinbase.com"
    wallets_url            = "/api/v3/brokerage/accounts"
    orders_url             = "/api/v3/brokerage/orders"
    get_order_url          = "/api/v3/brokerage/orders/historical"
    list_orders_url        = "/api/v3/brokerage/orders/historical/batch"
    cancel_orders_url      = "/api/v3/brokerage/orders/batch_cancel"
    portfolios_url         = "/api/v3/brokerage/portfolios"
    get_product_url        = "/api/v3/brokerage/products"


    def create_token(self, uri:str) -> str:
        private_key_bytes  = self.key_secret.encode('utf-8')
        private_key        = serialization.load_pem_private_key(private_key_bytes, password=None)
        jwt_payload = {
            'sub': self.key_name,
            'iss': "cdp",
            'nbf': int(time.time()),
            'exp': int(time.time()) + 120,
            'uri': uri,
        }
        jwt_token = jwt.encode(
            jwt_payload,
            private_key,
            algorithm='ES256',
            headers={'kid': self.key_name, 'nonce': secrets.token_hex()},
        )
        return jwt_token
    
    def create_header(self, uri:str) -> dict:
        return {'Authorization': f'Bearer {self.create_token(uri)}', 
                'Content-Type': 'application/json'}

    def get_product(self, product_id:str) -> Response:
        header     = self.create_header(f"GET {self.base_url}{self.get_product_url}/{product_id}")
        return requests.get(f"https://{self.base_url}{self.get_product_url}/{product_id}", headers=header)

    def get_portfolios(self) -> requests.Response:
        header     = self.create_header(f"GET {self.base_url}{self.portfolios_url}")
        return requests.get(f"https://{self.base_url}{self.portfolios_url}", headers=header)
    
    def get_portfolio(self, portfolio_uuid:str) -> Response:
        header     = self.create_header(f"GET {self.base_url}{self.portfolios_url}/{portfolio_uuid}")
        return requests.get(f"https://{self.base_url}{self.portfolios_url}/{portfolio_uuid}", headers=header)
    
    def place_order(self, order:LimitOrder, precision:int) -> Response:
        header     = self.create_header(f"POST {self.base_url}{self.orders_url}")
        payload    = order.payload(precision)
        return requests.post(f"https://{self.base_url}{self.orders_url}", json=payload, headers=header)

    def get_order(self, order_id:str) -> Response:
        header     = self.create_header(f"GET {self.base_url}{self.orders_url}/{order_id}")
        return requests.get(f"http://{self.base_url}{self.orders_url}/{order_id}", headers=header)
    
    def get_orders(self, order_ids:list[str]=[], order_status:str=[], order_types:list[str]=[], order_side:str="") -> Response:
        payload                      = {}
        if order_ids:
            payload["order_ids"]     = order_ids
        if order_status:
            payload["order_status"]  = order_status
        if order_types:
            payload["order_types"]   = order_types
        if order_side:
            payload["order_side"]    = order_side

        header     = self.create_header(f"GET {self.base_url}{self.list_orders_url}")
        return requests.get(f"https://{self.base_url}{self.list_orders_url}", payload, headers=header)
    
    def cancel_orders(self, order_ids:list[str]) -> Response:
        header     = self.create_header(f"POST {self.base_url}{self.cancel_orders_url}")
        return requests.post(f"https://{self.base_url}{self.cancel_orders_url}", json={"order_ids": order_ids}, headers=header)
    
    def cancel_all_open_orders(self) -> Response:
        resp       = self.get_orders(order_status=["OPEN"])
        if resp.ok:
            orders = resp.json()
            resp   = self.cancel_orders([order["order_id"] for order in orders["orders"]])
        return resp