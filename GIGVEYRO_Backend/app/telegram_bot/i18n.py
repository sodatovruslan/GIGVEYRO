from app.enums.notification import NotificationType

SUPPORTED_LANGUAGES = {"ru", "en", "tg"}

_MESSAGES = {
    "ru": {
        "welcome": "Добро пожаловать в GIGVEYRO. Подключите Telegram в веб-кабинете.",
        "linked": "Telegram успешно подключён.",
        "invalid_link": "Ссылка недействительна или истекла. Создайте новую в кабинете.",
        "unlinked": "Telegram не подключён. Используйте ссылку из веб-кабинета.",
        "blocked": "Доступ временно недоступен. Обратитесь в поддержку.",
        "rate_limited": "Слишком много запросов. Попробуйте позже.",
        "help": "Команды: /status /notifications /settings /language /unlink",
        "status": "Роль: {role}\nНепрочитанные уведомления: {unread}",
        "settings": "Язык: {language}\nДоставка: {delivery}",
        "enabled": "включена",
        "disabled": "выключена",
        "language_help": "Выберите: /language ru, /language en или /language tg",
        "language_changed": "Язык изменён.",
        "unlink_confirm": "Для отключения отправьте /unlink confirm.",
        "unlinked_ok": "Telegram отключён. История уведомлений сохранена.",
        "unknown": "Неизвестная или недоступная команда. Используйте /help.",
        "none": "Нет данных.",
        "notifications": "Последние уведомления:\n{items}",
        "balance": "Доступно: {available} USDT",
        "deals": "Активные сделки: {count}",
        "withdrawals": "Ожидающие выводы: {count}",
        "risk": "Статус риска казначейства: {status}",
        "payouts": "Выплаты, требующие внимания: {count}",
        "appeals": "Открытые апелляции: {count}",
        "details": "Откройте GIGVEYRO для безопасного просмотра деталей.",
        "open_web": "Открыть в GIGVEYRO",
    },
    "en": {
        "welcome": "Welcome to GIGVEYRO. Connect Telegram in the authenticated web cabinet.",
        "linked": "Telegram connected successfully.",
        "invalid_link": "This link is invalid or expired. Generate a new one in the cabinet.",
        "unlinked": "Telegram is not connected. Use the link from the web cabinet.",
        "blocked": "Access is temporarily unavailable. Contact support.",
        "rate_limited": "Too many requests. Try again later.",
        "help": "Commands: /status /notifications /settings /language /unlink",
        "status": "Role: {role}\nUnread notifications: {unread}",
        "settings": "Language: {language}\nDelivery: {delivery}",
        "enabled": "enabled",
        "disabled": "disabled",
        "language_help": "Choose /language ru, /language en, or /language tg",
        "language_changed": "Language changed.",
        "unlink_confirm": "Send /unlink confirm to disconnect.",
        "unlinked_ok": "Telegram disconnected. Notification history was preserved.",
        "unknown": "Unknown or unavailable command. Use /help.",
        "none": "No data.",
        "notifications": "Latest notifications:\n{items}",
        "balance": "Available: {available} USDT",
        "deals": "Active deals: {count}",
        "withdrawals": "Pending withdrawals: {count}",
        "risk": "Treasury risk status: {status}",
        "payouts": "Payouts requiring attention: {count}",
        "appeals": "Open appeals: {count}",
        "details": "Open GIGVEYRO to view details securely.",
        "open_web": "Open in GIGVEYRO",
    },
    "tg": {
        "welcome": "Хуш омадед ба GIGVEYRO. Telegram-ро дар кабинети веб пайваст кунед.",
        "linked": "Telegram бомуваффақият пайваст шуд.",
        "invalid_link": "Пайванд нодуруст ё муҳлаташ гузаштааст. Дар кабинет пайванди нав созед.",
        "unlinked": "Telegram пайваст нест. Пайвандро аз кабинети веб истифода баред.",
        "blocked": "Дастрасӣ муваққатан дастнорас аст. Ба дастгирӣ муроҷиат кунед.",
        "rate_limited": "Дархостҳо хеле зиёданд. Баъдтар кӯшиш кунед.",
        "help": "Фармонҳо: /status /notifications /settings /language /unlink",
        "status": "Нақш: {role}\nОгоҳиҳои нохонда: {unread}",
        "settings": "Забон: {language}\nИрсол: {delivery}",
        "enabled": "фаъол",
        "disabled": "ғайрифаъол",
        "language_help": "/language ru, /language en ё /language tg-ро интихоб кунед",
        "language_changed": "Забон иваз шуд.",
        "unlink_confirm": "Барои қатъ кардан /unlink confirm фиристед.",
        "unlinked_ok": "Telegram қатъ шуд. Таърихи огоҳиҳо нигоҳ дошта шуд.",
        "unknown": "Фармон номаълум ё дастнорас аст. /help-ро истифода баред.",
        "none": "Маълумот нест.",
        "notifications": "Огоҳиҳои охирин:\n{items}",
        "balance": "Дастрас: {available} USDT",
        "deals": "Муомилаҳои фаъол: {count}",
        "withdrawals": "Бардоштҳои интизор: {count}",
        "risk": "Вазъи хавфи хазина: {status}",
        "payouts": "Пардохтҳои ниёзманди таваҷҷуҳ: {count}",
        "appeals": "Шикоятҳои кушода: {count}",
        "details": "Барои дидани бехатари тафсилот GIGVEYRO-ро кушоед.",
        "open_web": "Дар GIGVEYRO кушодан",
    },
}

_NOTIFICATION_LABELS = {
    "ru": {
        NotificationType.DEAL_CREATED: "Новая сделка",
        NotificationType.DEAL_ACCEPTED: "Сделка принята",
        NotificationType.DEAL_PAID: "Оплата отмечена",
        NotificationType.DEAL_COMPLETED: "Сделка завершена",
        NotificationType.DEAL_CANCELLED: "Сделка отменена",
        NotificationType.APPEAL_OPENED: "Открыта апелляция",
        NotificationType.APPEAL_RESOLVED: "Апелляция решена",
        NotificationType.DEPOSIT_CONFIRMED: "Депозит подтверждён",
        NotificationType.WITHDRAWAL_STATUS_CHANGED: "Статус вывода изменён",
        NotificationType.PAYOUT_ACTION_REQUIRED: "Выплата требует внимания",
        NotificationType.SECURITY_EVENT: "Событие безопасности",
        NotificationType.FIAT_BALANCE_UPDATED: "Баланс обновлён",
        NotificationType.TREASURY_RISK_CHANGED: "Изменился риск казначейства",
    },
    "en": {},
    "tg": {},
}
_NOTIFICATION_LABELS["en"] = {
    item: item.value.replace("_", " ").title() for item in NotificationType
}
_NOTIFICATION_LABELS["tg"] = {
    NotificationType.DEAL_CREATED: "Муомилаи нав",
    NotificationType.DEAL_ACCEPTED: "Муомила қабул шуд",
    NotificationType.DEAL_PAID: "Пардохт қайд шуд",
    NotificationType.DEAL_COMPLETED: "Муомила анҷом ёфт",
    NotificationType.DEAL_CANCELLED: "Муомила бекор шуд",
    NotificationType.APPEAL_OPENED: "Шикоят кушода шуд",
    NotificationType.APPEAL_RESOLVED: "Шикоят ҳал шуд",
    NotificationType.DEPOSIT_CONFIRMED: "Амонат тасдиқ шуд",
    NotificationType.WITHDRAWAL_STATUS_CHANGED: "Вазъи бардошт иваз шуд",
    NotificationType.PAYOUT_ACTION_REQUIRED: "Пардохт таваҷҷуҳ мехоҳад",
    NotificationType.SECURITY_EVENT: "Рӯйдоди амниятӣ",
    NotificationType.FIAT_BALANCE_UPDATED: "Тавозун нав шуд",
    NotificationType.TREASURY_RISK_CHANGED: "Хавфи хазина тағйир ёфт",
}


def normalize_language(value: str | None) -> str:
    language = (value or "").lower().split("-")[0]
    return language if language in SUPPORTED_LANGUAGES else "ru"


def text(locale: str, key: str, **values: object) -> str:
    return _MESSAGES[normalize_language(locale)][key].format(**values)


def notification_label(language: str, notification_type: NotificationType) -> str:
    return _NOTIFICATION_LABELS[normalize_language(language)].get(
        notification_type, notification_type.value.replace("_", " ").title()
    )
