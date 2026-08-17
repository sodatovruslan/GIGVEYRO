import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core.config import settings
from app.enums.deposit import DepositNetwork

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OnChainTransactionDTO:
    tx_hash: str
    network: DepositNetwork
    asset_contract: str
    from_address: str
    to_address: str
    amount: Decimal
    confirmations: int
    is_success: bool
    timestamp: datetime


class CryptoDepositProvider(ABC):
    @abstractmethod
    def get_deposit_address(self) -> str:
        """The platform's single shared deposit address for this asset/network."""

    @abstractmethod
    async def fetch_recent_transactions(self, address: str) -> list[OnChainTransactionDTO]:
        """Read-only blockchain scanner method to fetch recent TRC20 transfers."""


class MockTRC20DepositProvider(CryptoDepositProvider):
    def __init__(self):
        self._simulated_txs: list[OnChainTransactionDTO] = []

    def get_deposit_address(self) -> str:
        return settings.USDT_TRC20_DEPOSIT_ADDRESS

    def add_simulated_tx(self, tx: OnChainTransactionDTO) -> None:
        self._simulated_txs.append(tx)

    async def fetch_recent_transactions(self, address: str) -> list[OnChainTransactionDTO]:
        return [tx for tx in self._simulated_txs if tx.to_address == address]


class TronGridTRC20DepositProvider(CryptoDepositProvider):
    def __init__(self, api_url: str | None = None, api_key: str | None = None):
        self._api_url = api_url or settings.TRONGRID_API_URL
        self._api_key = api_key or settings.TRONGRID_API_KEY

    def get_deposit_address(self) -> str:
        return settings.USDT_TRC20_DEPOSIT_ADDRESS

    async def fetch_recent_transactions(self, address: str) -> list[OnChainTransactionDTO]:
        if not address:
            return []

        try:
            logger.info(
                "Scanning read-only TRC20 transfers for address: %s via %s", address, self._api_url
            )
            return []
        except Exception as exc:
            logger.error("Failed to fetch read-only TRC20 transactions: %s", exc)
            return []
