import uuid
from decimal import Decimal
from enum import Enum
from typing import Any

from app.enums.notification import NotificationMessageKey

NotificationParam = str | int | bool | None
NotificationParams = dict[str, NotificationParam]

_FORBIDDEN_PARAM_FRAGMENTS = {
    "address",
    "api_key",
    "chat_id",
    "destination",
    "password",
    "private_key",
    "recovery_code",
    "secret",
    "telegram_id",
    "token",
    "totp",
}


def normalize_notification_locale(locale: str | None) -> str:
    normalized = (locale or "ru").lower().split("-", maxsplit=1)[0]
    return normalized if normalized in {"ru", "en", "tg"} else "ru"


def normalize_message_params(params: dict[str, Any] | None) -> NotificationParams:
    normalized: NotificationParams = {}
    for key, value in (params or {}).items():
        lowered = key.lower()
        if any(fragment in lowered for fragment in _FORBIDDEN_PARAM_FRAGMENTS):
            raise ValueError(f"sensitive notification parameter is not allowed: {key}")
        if isinstance(value, Decimal):
            normalized[key] = format(value, "f")
        elif isinstance(value, uuid.UUID):
            normalized[key] = str(value)
        elif isinstance(value, Enum):
            normalized[key] = str(value.value)
        elif value is None or isinstance(value, (str, int, bool)):
            normalized[key] = value
        else:
            raise TypeError(f"unsupported notification parameter type for {key}")
    return normalized


_CATALOG: dict[str, dict[NotificationMessageKey, tuple[str, str]]] = {
    "en": {
        NotificationMessageKey.APPEAL_OPENED: (
            "Appeal opened",
            "An appeal was opened for deal {reference}.",
        ),
        NotificationMessageKey.APPEAL_RESOLVED: (
            "Appeal resolved",
            "The appeal for deal {reference} was resolved.",
        ),
        NotificationMessageKey.DEPOSIT_CREDITED: (
            "Deposit credited",
            "Deposit {reference} for {amount} {currency} was credited.",
        ),
        NotificationMessageKey.WITHDRAWAL_CANCELLED: (
            "Withdrawal cancelled",
            "Withdrawal {reference} was cancelled.",
        ),
        NotificationMessageKey.WITHDRAWAL_APPROVED: (
            "Withdrawal approved",
            "Withdrawal {reference} was approved.",
        ),
        NotificationMessageKey.WITHDRAWAL_REJECTED: (
            "Withdrawal rejected",
            "Withdrawal {reference} was rejected.",
        ),
        NotificationMessageKey.WITHDRAWAL_COMPLETED: (
            "Withdrawal completed",
            "Withdrawal {reference} was completed.",
        ),
        NotificationMessageKey.FIAT_BALANCE_UPDATED: (
            "Balance updated",
            "Your balance was updated by {amount} {currency}.",
        ),
        NotificationMessageKey.SECURITY_RECOVERY_USED: (
            "Recovery code used",
            "A recovery code was used to sign in to your account.",
        ),
        NotificationMessageKey.SECURITY_TWO_FACTOR_ENABLED: (
            "Two-factor authentication enabled",
            "Two-factor authentication was enabled on your account.",
        ),
        NotificationMessageKey.SECURITY_TWO_FACTOR_DISABLED: (
            "Two-factor authentication disabled",
            "Two-factor authentication was disabled on your account.",
        ),
        NotificationMessageKey.SECURITY_RECOVERY_REGENERATED: (
            "Recovery codes regenerated",
            "New recovery codes were generated. Previous codes no longer work.",
        ),
        NotificationMessageKey.SECURITY_PASSWORD_CHANGED: (
            "Password changed",
            "Your password was changed. Other active sessions were signed out.",
        ),
        NotificationMessageKey.SECURITY_LOGOUT_ALL: (
            "Other sessions signed out",
            "Other active sessions signed out: {count}.",
        ),
        NotificationMessageKey.SECURITY_SESSION_REVOKED: (
            "Session signed out",
            "An active session was signed out from your security settings.",
        ),
        NotificationMessageKey.PAYOUT_APPROVAL_REQUIRED: (
            "Payout requires approval",
            "Payout {reference} requires approval.",
        ),
        NotificationMessageKey.PAYOUT_EXECUTION_FAILED: (
            "Payout execution failed",
            "Payout {reference} could not be completed.",
        ),
        NotificationMessageKey.PAYOUT_RECONCILIATION_REQUIRED: (
            "Payout requires reconciliation",
            "Payout {reference} has an uncertain provider result.",
        ),
        NotificationMessageKey.TREASURY_WARNING: (
            "Treasury risk warning",
            "Treasury health requires attention.",
        ),
        NotificationMessageKey.TREASURY_CRITICAL: (
            "Critical treasury risk",
            "Treasury health is in a critical state.",
        ),
        NotificationMessageKey.TREASURY_STALE: (
            "Treasury data is stale",
            "Treasury data must be refreshed before making decisions.",
        ),
        NotificationMessageKey.ACCESS_REQUEST_SUBMITTED: (
            "New access request",
            "{full_name} ({contact}) wants to register on GigaPay. Note: {note}",
        ),
    },
    "ru": {
        NotificationMessageKey.APPEAL_OPENED: (
            "Открыта апелляция",
            "По сделке {reference} открыта апелляция.",
        ),
        NotificationMessageKey.APPEAL_RESOLVED: (
            "Апелляция разрешена",
            "Апелляция по сделке {reference} разрешена.",
        ),
        NotificationMessageKey.DEPOSIT_CREDITED: (
            "Депозит зачислен",
            "Депозит {reference} на сумму {amount} {currency} зачислен.",
        ),
        NotificationMessageKey.WITHDRAWAL_CANCELLED: (
            "Вывод отменён",
            "Вывод {reference} отменён.",
        ),
        NotificationMessageKey.WITHDRAWAL_APPROVED: ("Вывод одобрен", "Вывод {reference} одобрен."),
        NotificationMessageKey.WITHDRAWAL_REJECTED: (
            "Вывод отклонён",
            "Вывод {reference} отклонён.",
        ),
        NotificationMessageKey.WITHDRAWAL_COMPLETED: (
            "Вывод завершён",
            "Вывод {reference} завершён.",
        ),
        NotificationMessageKey.FIAT_BALANCE_UPDATED: (
            "Баланс обновлён",
            "Ваш баланс изменён на {amount} {currency}.",
        ),
        NotificationMessageKey.SECURITY_RECOVERY_USED: (
            "Использован резервный код",
            "Для входа в ваш аккаунт использован резервный код.",
        ),
        NotificationMessageKey.SECURITY_TWO_FACTOR_ENABLED: (
            "Двухфакторная аутентификация включена",
            "Для вашего аккаунта включена двухфакторная аутентификация.",
        ),
        NotificationMessageKey.SECURITY_TWO_FACTOR_DISABLED: (
            "Двухфакторная аутентификация отключена",
            "Для вашего аккаунта отключена двухфакторная аутентификация.",
        ),
        NotificationMessageKey.SECURITY_RECOVERY_REGENERATED: (
            "Резервные коды обновлены",
            "Созданы новые резервные коды. Предыдущие коды больше не работают.",
        ),
        NotificationMessageKey.SECURITY_PASSWORD_CHANGED: (
            "Пароль изменён",
            "Ваш пароль изменён. Другие активные сессии завершены.",
        ),
        NotificationMessageKey.SECURITY_LOGOUT_ALL: (
            "Другие сессии завершены",
            "Завершено других активных сессий: {count}.",
        ),
        NotificationMessageKey.SECURITY_SESSION_REVOKED: (
            "Сессия завершена",
            "Активная сессия завершена в настройках безопасности.",
        ),
        NotificationMessageKey.PAYOUT_APPROVAL_REQUIRED: (
            "Выплата требует одобрения",
            "Выплата {reference} ожидает одобрения.",
        ),
        NotificationMessageKey.PAYOUT_EXECUTION_FAILED: (
            "Ошибка выполнения выплаты",
            "Не удалось завершить выплату {reference}.",
        ),
        NotificationMessageKey.PAYOUT_RECONCILIATION_REQUIRED: (
            "Требуется сверка выплаты",
            "Результат выплаты {reference} у провайдера не определён.",
        ),
        NotificationMessageKey.TREASURY_WARNING: (
            "Предупреждение по казначейству",
            "Состояние казначейства требует внимания.",
        ),
        NotificationMessageKey.TREASURY_CRITICAL: (
            "Критический риск казначейства",
            "Состояние казначейства критическое.",
        ),
        NotificationMessageKey.TREASURY_STALE: (
            "Данные казначейства устарели",
            "Перед принятием решений обновите данные казначейства.",
        ),
        NotificationMessageKey.ACCESS_REQUEST_SUBMITTED: (
            "Новая заявка на регистрацию",
            "{full_name} ({contact}) хочет зарегистрироваться в GigaPay. Заметка: {note}",
        ),
    },
    "tg": {
        NotificationMessageKey.APPEAL_OPENED: (
            "Шикоят кушода шуд",
            "Барои муомилаи {reference} шикоят кушода шуд.",
        ),
        NotificationMessageKey.APPEAL_RESOLVED: (
            "Шикоят ҳал шуд",
            "Шикояти муомилаи {reference} ҳал шуд.",
        ),
        NotificationMessageKey.DEPOSIT_CREDITED: (
            "Амонат ворид шуд",
            "Амонати {reference} ба маблағи {amount} {currency} ворид шуд.",
        ),
        NotificationMessageKey.WITHDRAWAL_CANCELLED: (
            "Бардошт бекор шуд",
            "Бардошти {reference} бекор шуд.",
        ),
        NotificationMessageKey.WITHDRAWAL_APPROVED: (
            "Бардошт тасдиқ шуд",
            "Бардошти {reference} тасдиқ шуд.",
        ),
        NotificationMessageKey.WITHDRAWAL_REJECTED: (
            "Бардошт рад шуд",
            "Бардошти {reference} рад шуд.",
        ),
        NotificationMessageKey.WITHDRAWAL_COMPLETED: (
            "Бардошт анҷом ёфт",
            "Бардошти {reference} анҷом ёфт.",
        ),
        NotificationMessageKey.FIAT_BALANCE_UPDATED: (
            "Тавозун нав шуд",
            "Тавозуни шумо ба {amount} {currency} тағйир дода шуд.",
        ),
        NotificationMessageKey.SECURITY_RECOVERY_USED: (
            "Рамзи захиравӣ истифода шуд",
            "Барои воридшавӣ ба ҳисоби шумо рамзи захиравӣ истифода шуд.",
        ),
        NotificationMessageKey.SECURITY_TWO_FACTOR_ENABLED: (
            "Санҷиши дуфакторӣ фаъол шуд",
            "Барои ҳисоби шумо санҷиши дуфакторӣ фаъол карда шуд.",
        ),
        NotificationMessageKey.SECURITY_TWO_FACTOR_DISABLED: (
            "Санҷиши дуфакторӣ ғайрифаъол шуд",
            "Барои ҳисоби шумо санҷиши дуфакторӣ ғайрифаъол карда шуд.",
        ),
        NotificationMessageKey.SECURITY_RECOVERY_REGENERATED: (
            "Рамзҳои захиравӣ нав шуданд",
            "Рамзҳои нави захиравӣ сохта шуданд. Рамзҳои пешина дигар кор намекунанд.",
        ),
        NotificationMessageKey.SECURITY_PASSWORD_CHANGED: (
            "Парол иваз шуд",
            "Пароли шумо иваз шуд. Сессияҳои дигари фаъол қатъ шуданд.",
        ),
        NotificationMessageKey.SECURITY_LOGOUT_ALL: (
            "Сессияҳои дигар қатъ шуданд",
            "Сессияҳои дигари қатъшуда: {count}.",
        ),
        NotificationMessageKey.SECURITY_SESSION_REVOKED: (
            "Сессия қатъ шуд",
            "Сессияи фаъол аз танзимоти амниятӣ қатъ карда шуд.",
        ),
        NotificationMessageKey.PAYOUT_APPROVAL_REQUIRED: (
            "Пардохт тасдиқ мехоҳад",
            "Пардохти {reference} тасдиқро интизор аст.",
        ),
        NotificationMessageKey.PAYOUT_EXECUTION_FAILED: (
            "Пардохт иҷро нашуд",
            "Пардохти {reference} анҷом дода нашуд.",
        ),
        NotificationMessageKey.PAYOUT_RECONCILIATION_REQUIRED: (
            "Санҷиши пардохт лозим аст",
            "Натиҷаи пардохти {reference} дар провайдер номуайян аст.",
        ),
        NotificationMessageKey.TREASURY_WARNING: (
            "Огоҳии хазина",
            "Вазъи хазина таваҷҷуҳ мехоҳад.",
        ),
        NotificationMessageKey.TREASURY_CRITICAL: (
            "Хавфи ҷиддии хазина",
            "Вазъи хазина ҷиддӣ аст.",
        ),
        NotificationMessageKey.TREASURY_STALE: (
            "Маълумоти хазина куҳна шудааст",
            "Пеш аз қабули қарор маълумоти хазинаро нав кунед.",
        ),
        NotificationMessageKey.ACCESS_REQUEST_SUBMITTED: (
            "Дархости нави бақайдгирӣ",
            "{full_name} ({contact}) мехоҳад дар GigaPay бақайд гирад. Қайд: {note}",
        ),
    },
}


def notification_message_catalog() -> dict[str, dict[NotificationMessageKey, tuple[str, str]]]:
    return _CATALOG


def render_notification_message(
    locale: str,
    message_key: str | None,
    params: dict[str, Any] | None,
    *,
    fallback_title: str,
    fallback_message: str,
) -> tuple[str, str]:
    try:
        key = NotificationMessageKey(message_key) if message_key else None
    except ValueError:
        key = None
    template = _CATALOG[normalize_notification_locale(locale)].get(key) if key else None
    if template is None:
        return fallback_title, fallback_message
    values = normalize_message_params(params)
    try:
        return template[0].format_map(values), template[1].format_map(values)
    except KeyError:
        return fallback_title or template[0], fallback_message or template[1]
