import type { ValidationIssue } from "@/lib/api/types";

interface ErrorPayload { detail?: string | ValidationIssue[] | { code?: string }; message?: string }

const FALLBACK_MESSAGES: Record<number, string> = {
  400: "Проверьте введённые данные.",
  401: "Сессия истекла. Войдите снова.",
  403: "У вас нет доступа к этому действию.",
  404: "Запрошенные данные не найдены.",
  409: "Операция конфликтует с текущим состоянием.",
  422: "Некоторые поля заполнены неверно.",
  429: "Слишком много запросов. Попробуйте немного позже.",
  500: "Сервис временно недоступен.",
};

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly issues: ValidationIssue[] = [],
    public readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function apiErrorFromPayload(status: number, payload: unknown): ApiError {
  const value = payload && typeof payload === "object" ? (payload as ErrorPayload) : {};
  const issues = Array.isArray(value.detail) ? value.detail : [];
  const code = value.detail && typeof value.detail === "object" && !Array.isArray(value.detail)
    ? value.detail.code
    : undefined;
  const detail = typeof value.detail === "string" ? value.detail : value.message;
  return new ApiError(status, detail || code || FALLBACK_MESSAGES[status] || "Не удалось выполнить запрос.", issues, code);
}
