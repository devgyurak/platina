"""[repro] is the `==` rejection on fail_findings.py:40 the column-to-column one, or the `| None` mismatch?"""

from domain import Order, OrderStatus, Wallet
from lib import Load

same_t = Load.when(Order.status == OrderStatus.PENDING, match=Wallet.user_id == Wallet.user_id)
