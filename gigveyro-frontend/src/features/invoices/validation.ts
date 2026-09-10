export type InvoiceField = "amount" | "description" | "external_reference";
export type InvoiceFieldErrors = Partial<Record<InvoiceField, string>>;

export function mapInvoiceFieldErrors(error: unknown, messages: { invalidAmount: string }): InvoiceFieldErrors {
  if (!error || typeof error !== "object" || !("message" in error)) return {};
  const apiError = error as { message: string; issues?: Array<{ loc?: Array<string | number> }> };
  const result: InvoiceFieldErrors = {};
  for (const issue of apiError.issues || []) {
    const field = issue.loc?.at(-1);
    if (field === "amount") result.amount = messages.invalidAmount;
  }
  if (/amount must be a positive/i.test(apiError.message)) result.amount = messages.invalidAmount;
  return result;
}

export function isInvoiceNotCancellable(error: unknown): boolean {
  if (!error || typeof error !== "object" || !("message" in error)) return false;
  const apiError = error as { message: string };
  return /only a pending invoice can be cancelled/i.test(apiError.message);
}
