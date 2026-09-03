from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.core.config import settings
from app.enums.deposit import DepositNetwork


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
    provider: str = "mock"
    event_index: int = 0
    block_number: int | None = None
    is_finalized: bool = True

    @property
    def provider_event_id(self) -> str:
        return f"{self.provider}:{self.tx_hash}:{self.event_index}"


class CryptoDepositProvider(ABC):
    last_scan_upper_timestamp_ms: int | None = None

    @abstractmethod
    def get_deposit_address(self) -> str:
        """The platform's single shared deposit address for this asset/network."""

    @abstractmethod
    async def fetch_recent_transactions(
        self, address: str, *, min_timestamp_ms: int | None = None
    ) -> list[OnChainTransactionDTO]:
        """Read-only blockchain scanner method to fetch recent TRC20 transfers."""

    async def aclose(self) -> None:
        """Close provider-owned network resources, if any."""
        return None


class MockTRC20DepositProvider(CryptoDepositProvider):
    def __init__(self):
        self._simulated_txs: list[OnChainTransactionDTO] = []

    def get_deposit_address(self) -> str:
        return settings.USDT_TRC20_DEPOSIT_ADDRESS

    def add_simulated_tx(self, tx: OnChainTransactionDTO) -> None:
        self._simulated_txs.append(tx)

    async def fetch_recent_transactions(
        self, address: str, *, min_timestamp_ms: int | None = None
    ) -> list[OnChainTransactionDTO]:
        del min_timestamp_ms
        return [tx for tx in self._simulated_txs if tx.to_address == address]
