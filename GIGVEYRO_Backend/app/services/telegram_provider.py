from abc import ABC, abstractmethod
from typing import NamedTuple


class TelegramMessage(NamedTuple):
    chat_id: int
    text: str
    parse_mode: str | None = "HTML"


class TelegramProvider(ABC):
    @abstractmethod
    async def send_message(self, chat_id: int, text: str) -> bool:
        """Send message via Telegram provider."""
        pass


class MockTelegramProvider(TelegramProvider):
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail
        self.sent_messages: list[TelegramMessage] = []

    async def send_message(self, chat_id: int, text: str) -> bool:
        if self.should_fail:
            raise RuntimeError("Mock Telegram Provider API Failure")
        self.sent_messages.append(TelegramMessage(chat_id=chat_id, text=text))
        return True

    def clear(self) -> None:
        self.sent_messages.clear()
