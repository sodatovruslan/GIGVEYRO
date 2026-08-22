from app.realtime.broker import InMemoryRealtimeBroker
from app.services.realtime import RealtimeOutboxDispatcher

realtime_broker = InMemoryRealtimeBroker()
realtime_dispatcher = RealtimeOutboxDispatcher(realtime_broker)
