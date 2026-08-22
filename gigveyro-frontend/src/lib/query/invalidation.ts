export type QueryInvalidationPattern = string;

type Subscriber = {
  key: string;
  refetch: () => void;
};

function matches(pattern: QueryInvalidationPattern, key: string) {
  return pattern.endsWith("*") ? key.startsWith(pattern.slice(0, -1)) : key === pattern;
}

export class QueryInvalidationBus {
  private subscribers = new Set<Subscriber>();

  subscribe(key: string, refetch: () => void) {
    const subscriber = { key, refetch };
    this.subscribers.add(subscriber);
    return () => this.subscribers.delete(subscriber);
  }

  invalidate(patterns: readonly QueryInvalidationPattern[]) {
    const callbacks = new Set<() => void>();
    for (const subscriber of this.subscribers) {
      if (patterns.some((pattern) => matches(pattern, subscriber.key))) {
        callbacks.add(subscriber.refetch);
      }
    }
    callbacks.forEach((refetch) => refetch());
    return callbacks.size;
  }
}

export const queryInvalidation = new QueryInvalidationBus();
