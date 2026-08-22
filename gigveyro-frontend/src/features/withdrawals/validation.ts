export type WithdrawalField = "amount" | "destination_type" | "destination" | "comment";
export type WithdrawalFieldErrors = Partial<Record<WithdrawalField, string>>;

export function mapWithdrawalFieldErrors(error: unknown, messages: { invalidAmount: string; invalidDestination: string; invalidTrc20: string; invalidComment: string }): WithdrawalFieldErrors {
  if (!error || typeof error !== "object" || !("message" in error)) return {};
  const apiError = error as { message: string; issues?: Array<{ loc?: Array<string | number> }> };
  const result: WithdrawalFieldErrors = {};
  for (const issue of apiError.issues || []) {
    const field = issue.loc?.at(-1);
    if (field === "amount") result.amount = messages.invalidAmount;
    if (field === "destination" || field === "destination_type") result[field] = messages.invalidDestination;
    if (field === "comment") result.comment = messages.invalidComment;
  }
  if (/invalid TRC20 address length/i.test(apiError.message)) result.destination = messages.invalidTrc20;
  if (/destination cannot be empty/i.test(apiError.message)) result.destination = messages.invalidDestination;
  if (/amount must be a positive/i.test(apiError.message)) result.amount = messages.invalidAmount;
  return result;
}
