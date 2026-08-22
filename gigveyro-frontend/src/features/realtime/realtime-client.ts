import { realtimeEventNames, type RealtimeEventName } from "./event-map";

export interface RealtimeEvent {
  version: 1;
  id: string;
  event: RealtimeEventName;
  entity_id: string;
  occurred_at: string;
  data: Record<string, unknown>;
}

export interface RealtimeTicket {
  ticket: string;
  expires_in: number;
  websocket_path: string;
}

interface RealtimeSocket {
  onopen: ((event: Event) => void) | null;
  onmessage: ((message: MessageEvent<string>) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  send(data: string): void;
  close(code?: number, reason?: string): void;
}

interface RealtimeClientOptions {
  getTicket: () => Promise<RealtimeTicket>;
  createSocket: (url: string, protocols: string[]) => RealtimeSocket;
  resolveUrl: (path: string) => string;
  onEvent: (event: RealtimeEvent) => void;
  schedule?: (callback: () => void, delay: number) => ReturnType<typeof setTimeout>;
  cancelSchedule?: (timer: ReturnType<typeof setTimeout>) => void;
  random?: () => number;
}

const protocol = "gigveyro.realtime.v1";
const knownEvents = new Set<string>(realtimeEventNames);

function parseEvent(value: unknown): RealtimeEvent | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<RealtimeEvent>;
  if (
    candidate.version !== 1 ||
    typeof candidate.id !== "string" ||
    typeof candidate.entity_id !== "string" ||
    typeof candidate.occurred_at !== "string" ||
    typeof candidate.event !== "string" ||
    !knownEvents.has(candidate.event)
  ) return null;
  return candidate as RealtimeEvent;
}

export function resolveRealtimeUrl(path: string) {
  const configured = process.env.NEXT_PUBLIC_REALTIME_URL?.trim();
  if (configured) return configured;
  const url = new URL(path, window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export class RealtimeClient {
  private generation = 0;
  private attempt = 0;
  private socket: RealtimeSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private seenEventIds = new Set<string>();

  constructor(private options: RealtimeClientOptions) {}

  start() {
    const generation = ++this.generation;
    this.attempt = 0;
    void this.connect(generation);
  }

  stop() {
    this.generation += 1;
    if (this.reconnectTimer !== null) {
      (this.options.cancelSchedule ?? clearTimeout)(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const socket = this.socket;
    this.socket = null;
    socket?.close(1000, "session ended");
    this.seenEventIds.clear();
  }

  private async connect(generation: number) {
    try {
      const ticket = await this.options.getTicket();
      if (generation !== this.generation) return;
      const socket = this.options.createSocket(
        this.options.resolveUrl(ticket.websocket_path),
        [protocol, `gigveyro.ticket.${ticket.ticket}`],
      );
      this.socket = socket;
      socket.onopen = () => {
        if (generation === this.generation && socket === this.socket) this.attempt = 0;
      };
      socket.onmessage = (message) => {
        if (generation !== this.generation || socket !== this.socket) return;
        let payload: unknown;
        try { payload = JSON.parse(message.data); } catch { return; }
        if ((payload as { type?: string })?.type === "ping") {
          socket.send(JSON.stringify({ type: "pong" }));
          return;
        }
        const event = parseEvent(payload);
        if (!event || this.seenEventIds.has(event.id)) return;
        this.seenEventIds.add(event.id);
        if (this.seenEventIds.size > 500) {
          const oldest = this.seenEventIds.values().next().value;
          if (oldest) this.seenEventIds.delete(oldest);
        }
        this.options.onEvent(event);
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (generation !== this.generation || socket !== this.socket) return;
        this.socket = null;
        this.scheduleReconnect(generation);
      };
    } catch {
      if (generation === this.generation) this.scheduleReconnect(generation);
    }
  }

  private scheduleReconnect(generation: number) {
    if (this.reconnectTimer !== null) return;
    const base = Math.min(30_000, 1_000 * 2 ** this.attempt++);
    const jitter = 0.8 + (this.options.random ?? Math.random)() * 0.4;
    const schedule = this.options.schedule ?? setTimeout;
    this.reconnectTimer = schedule(() => {
      this.reconnectTimer = null;
      if (generation === this.generation) void this.connect(generation);
    }, Math.round(base * jitter));
  }
}
