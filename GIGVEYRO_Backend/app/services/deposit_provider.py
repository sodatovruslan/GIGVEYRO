from abc import ABC, abstractmethod

from app.core.config import settings


class CryptoDepositProvider(ABC):
    """DepositService only depends on this abstraction, and only for the
    one thing it actually needs at intent-creation time: the current
    platform deposit address. It has no knowledge of Wallet/Ledger.

    Observed on-chain events (a transaction detected, its confirmation
    count) are NOT pulled through this interface in Stage 8. There is no
    background listener yet, so those events are pushed in by a caller
    (the DEV-only simulate endpoint today; a real chain-watching worker in
    a later stage) straight into DepositService.ingest_transaction_event().
    Both callers feed the exact same method, so swapping the mock push
    source for a real listener never touches DepositService.
    """

    @abstractmethod
    def get_deposit_address(self) -> str:
        """The platform's single shared deposit address for this asset/network."""


class MockTRC20DepositProvider(CryptoDepositProvider):
    """Development/test provider - NOT connected to any real blockchain."""

    def get_deposit_address(self) -> str:
        return settings.USDT_TRC20_DEPOSIT_ADDRESS
