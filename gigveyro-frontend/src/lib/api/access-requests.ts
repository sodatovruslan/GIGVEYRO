import { apiFetch } from "@/lib/api/client";
import type { AccessRequestAck, AccessRequestInput } from "@/lib/api/types";

export const accessRequestApi = {
  submit: (input: AccessRequestInput) =>
    apiFetch<AccessRequestAck>("/access-requests", { method: "POST", body: input }),
};
