export type AppealField = "deal_id" | "message" | "owner_note";
export type AppealFieldErrors = Partial<Record<AppealField, string>>;

export function mapAppealFieldErrors(error: unknown, messages: { dealNotEligible: string; activeAppealExists: string; dealNotFound: string; invalidMessage: string; invalidOwnerNote: string }): AppealFieldErrors {
  if (!error || typeof error !== "object" || !("message" in error)) return {};
  const apiError = error as { message: string; issues?: Array<{ loc?: Array<string | number> }> };
  const result: AppealFieldErrors = {};
  for (const issue of apiError.issues || []) {
    const field = issue.loc?.at(-1);
    if (field === "message") result.message = messages.invalidMessage;
    if (field === "owner_note") result.owner_note = messages.invalidOwnerNote;
  }
  if (/cannot open appeal for deal in status/i.test(apiError.message)) result.deal_id = messages.dealNotEligible;
  if (/an active appeal already exists/i.test(apiError.message)) result.deal_id = messages.activeAppealExists;
  if (/deal not found/i.test(apiError.message)) result.deal_id = messages.dealNotFound;
  return result;
}
