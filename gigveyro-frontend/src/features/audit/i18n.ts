export type AuditMessageKind = "actions" | "entities";

const safeSegment = /^[a-z][a-z0-9_]*$/;

export function auditMessagePath(kind: AuditMessageKind, backendValue: string) {
  const segments = backendValue.split(".");
  const expectedSegments = kind === "actions" ? 2 : 1;
  if (segments.length !== expectedSegments || segments.some((segment) => !safeSegment.test(segment))) return null;
  return `${kind}.${segments.join(".")}`;
}
