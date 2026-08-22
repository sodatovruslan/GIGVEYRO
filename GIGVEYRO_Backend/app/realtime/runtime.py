from app.core.config import settings
from app.realtime.broker import InMemoryRealtimeBroker, RedisRealtimeBroker
from app.services.realtime import RealtimeOutboxDispatcher

if settings.REALTIME_BROKER == "redis":
    realtime_broker = RedisRealtimeBroker()
else:
    realtime_broker = InMemoryRealtimeBroker()

realtime_dispatcher = RealtimeOutboxDispatcher(realtime_broker)

