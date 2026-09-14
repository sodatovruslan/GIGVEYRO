"""Inline-keyboard builders for the Telegram menu system.

Every callback_data value is a short, static, server-defined string plus at
most one page number or one UUID - never a trust boundary by itself. Every
handler that receives an id embedded here re-validates ownership against the
database before returning any data (see TelegramCommandService.handle_callback).
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.enums.account import UserRole
from app.telegram_bot.i18n import text

PAGE_SIZE = 8
NOOP = "noop"


def _btn(label: str, callback: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=label, callback_data=callback)


# Public alias - callers outside this module build ad-hoc rows (list items,
# detail-screen action buttons) with the same short-callback-data discipline.
button = _btn


def _rows_of_two(buttons: list[InlineKeyboardButton]) -> list[list[InlineKeyboardButton]]:
    return [buttons[index : index + 2] for index in range(0, len(buttons), 2)]


def nav_row(language: str, *, back: str | None = None) -> list[InlineKeyboardButton]:
    row = []
    if back:
        row.append(_btn(text(language, "btn_back"), back))
    row.append(_btn(text(language, "btn_home"), "home"))
    return row


def keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def with_nav(
    language: str,
    rows: list[list[InlineKeyboardButton]],
    *,
    back: str | None = None,
) -> InlineKeyboardMarkup:
    return keyboard([*rows, nav_row(language, back=back)])


def pagination_row(
    language: str, prefix: str, page: int, total_pages: int
) -> list[InlineKeyboardButton]:
    row = []
    if page > 1:
        row.append(_btn(text(language, "btn_prev"), f"{prefix}:{page - 1}"))
    row.append(_btn(text(language, "page_of", page=page, total=max(total_pages, 1)), NOOP))
    if page < total_pages:
        row.append(_btn(text(language, "btn_next"), f"{prefix}:{page + 1}"))
    return row


def prev_next_row(
    language: str, prefix: str, page: int, has_next: bool
) -> list[InlineKeyboardButton]:
    """For lists with no cheap total count (e.g. notifications) - pages
    forward/back based on whether a full page was returned, not a total."""
    row = []
    if page > 1:
        row.append(_btn(text(language, "btn_prev"), f"{prefix}:{page - 1}"))
    row.append(_btn(str(page), NOOP))
    if has_next:
        row.append(_btn(text(language, "btn_next"), f"{prefix}:{page + 1}"))
    return row


def confirm_keyboard(language: str, go: str, back: str) -> InlineKeyboardMarkup:
    return keyboard(
        [
            [_btn(text(language, "btn_confirm"), go), _btn(text(language, "btn_cancel"), back)],
            nav_row(language),
        ]
    )


def total_pages(total_items: int, page_size: int = PAGE_SIZE) -> int:
    return max(1, (total_items + page_size - 1) // page_size)


# ---------------------------------------------------------------------------
# Role main menus
# ---------------------------------------------------------------------------

_ROLE_MENUS: dict[UserRole, list[tuple[str, str]]] = {
    UserRole.OWNER: [
        ("btn_dashboard", "ow_dash"),
        ("btn_accounts", "ow_acc:1"),
        ("btn_deals", "ow_deals:1"),
        ("btn_withdrawals", "ow_wd"),
        ("btn_payouts", "ow_payouts:1"),
        ("btn_team_leads", "ow_tl:1"),
        ("btn_risk", "ow_risk"),
        ("btn_treasury", "ow_treasury"),
    ],
    UserRole.TEAM_LEAD: [
        ("btn_dashboard", "tl_dash"),
        ("btn_team", "tl_team:1"),
        ("btn_profit", "tl_profit:1"),
        ("btn_my_withdrawals", "tl_wd:1"),
    ],
    UserRole.USER: [
        ("btn_balance", "u_bal"),
        ("btn_deals", "u_deals:1"),
        ("btn_withdrawals", "u_wd:1"),
    ],
    UserRole.MERCHANT: [
        ("btn_balance", "m_bal"),
        ("btn_invoices", "m_inv:1"),
        ("btn_deals", "m_deals:1"),
        ("btn_withdrawals", "m_wd:1"),
        ("btn_statistics", "m_stats"),
    ],
}


def home_menu(language: str, role: UserRole) -> InlineKeyboardMarkup:
    items = _ROLE_MENUS.get(role, [])
    buttons = [_btn(text(language, label_key), callback) for label_key, callback in items]
    rows = _rows_of_two(buttons)
    rows.append(
        [
            _btn(text(language, "btn_notifications"), "notif:1"),
            _btn(text(language, "btn_settings"), "settings"),
        ]
    )
    return keyboard(rows)


def owner_withdrawals_menu(language: str) -> InlineKeyboardMarkup:
    return with_nav(
        language,
        [
            [
                _btn(text(language, "btn_merchant"), "ow_wdm:1"),
                _btn(text(language, "btn_user"), "ow_wdu:1"),
            ]
        ],
        back="home",
    )


def settings_menu(
    language: str, *, connected: bool, delivery_enabled: bool
) -> InlineKeyboardMarkup:
    rows = [[_btn(text(language, "btn_language"), "set_lang")]]
    if connected:
        rows.append([_btn(text(language, "btn_toggle_delivery"), "set_delivery")])
        rows.append([_btn(text(language, "btn_unlink"), "set_unlink")])
    return with_nav(language, rows, back=None)


def language_menu(language: str) -> InlineKeyboardMarkup:
    return with_nav(
        language,
        [
            [
                _btn(text(language, "btn_lang_ru"), "lang:ru"),
                _btn(text(language, "btn_lang_en"), "lang:en"),
                _btn(text(language, "btn_lang_tg"), "lang:tg"),
            ]
        ],
        back="settings",
    )


def destination_type_keyboard(language: str, *, back: str) -> InlineKeyboardMarkup:
    return keyboard(
        [
            [
                _btn(text(language, "btn_dest_trc20"), "wdflow:dt:usdt_trc20_address"),
                _btn(text(language, "btn_dest_bybit"), "wdflow:dt:bybit_uid"),
            ],
            nav_row(language, back=back),
        ]
    )


def list_keyboard(
    language: str,
    *,
    item_callbacks: list[tuple[str, str]],
    page_prefix: str,
    page: int,
    total_items: int,
    back: str,
    extra_rows: list[list[InlineKeyboardButton]] | None = None,
) -> InlineKeyboardMarkup:
    rows = [[_btn(label, callback)] for label, callback in item_callbacks]
    if extra_rows:
        rows.extend(extra_rows)
    rows.append(pagination_row(language, page_prefix, page, total_pages(total_items)))
    return with_nav(language, rows, back=back)


def flow_cancel_keyboard(language: str) -> InlineKeyboardMarkup:
    return keyboard([[_btn(text(language, "btn_cancel"), "wdflow_cancel")], nav_row(language)])


def invoice_flow_cancel_keyboard(language: str) -> InlineKeyboardMarkup:
    return keyboard([[_btn(text(language, "btn_cancel"), "invflow_cancel")], nav_row(language)])


def detail_keyboard(
    language: str,
    *,
    action_rows: list[list[InlineKeyboardButton]] | None = None,
    back: str,
) -> InlineKeyboardMarkup:
    return with_nav(language, action_rows or [], back=back)
