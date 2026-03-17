from __future__ import annotations

from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .openvpn import (
    add_bot_user,
    allowed_bot_users,
    backup_all,
    block_client,
    connected_clients,
    create_client,
    delete_client,
    extend_client,
    list_clients,
    recreate_client,
    remove_bot_user,
    summary_text,
    telegram_settings,
    unblock_client,
)

STATE_CREATE_NAME, STATE_CREATE_DAYS = range(2)
STATE_DELETE = 10
STATE_RECREATE = 11
STATE_EXTEND_NAME, STATE_EXTEND_DAYS = range(20, 22)
STATE_BLOCK = 30
STATE_UNBLOCK = 31
STATE_ADD_USER = 40
STATE_REMOVE_USER = 41


def _settings():
    return telegram_settings()


def _admin_ids() -> set[str]:
    settings = _settings()
    raw = settings.get("admin_ids", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


def _allowed_ids() -> set[str]:
    ids = set(allowed_bot_users())
    ids.update(_admin_ids())
    return ids


def _is_admin(user_id: int) -> bool:
    return str(user_id) in _admin_ids()


def _is_allowed(user_id: int) -> bool:
    return str(user_id) in _allowed_ids()


def _main_keyboard(is_admin: bool) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("📊 Статус", callback_data="status"), InlineKeyboardButton("📋 Ключи", callback_data="list")],
        [InlineKeyboardButton("➕ Создать", callback_data="create"), InlineKeyboardButton("🗑 Удалить", callback_data="delete")],
        [InlineKeyboardButton("♻️ Пересоздать", callback_data="recreate"), InlineKeyboardButton("⏳ Продлить", callback_data="extend")],
        [InlineKeyboardButton("⛔ Блок", callback_data="block"), InlineKeyboardButton("✅ Разблок", callback_data="unblock")],
        [InlineKeyboardButton("👥 Подключенные", callback_data="connected"), InlineKeyboardButton("💾 Бэкап", callback_data="backup")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("👤 +Пользователь", callback_data="add_user"), InlineKeyboardButton("👤 -Пользователь", callback_data="remove_user")])
    return InlineKeyboardMarkup(buttons)


async def _require_access(update: Update) -> bool:
    user = update.effective_user
    if not user or not _is_allowed(user.id):
        if update.message:
            await update.message.reply_text("⛔️ У вас нет доступа к боту.")
        elif update.callback_query:
            await update.callback_query.answer("Нет доступа", show_alert=True)
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_access(update):
        return
    await update.message.reply_text("Меню управления OpenVPN", reply_markup=_main_keyboard(_is_admin(update.effective_user.id)))


async def cb_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await _require_access(update):
        return ConversationHandler.END
    query = update.callback_query
    assert query is not None
    await query.answer()
    action = query.data
    if action == "status":
        await query.message.reply_text(summary_text(), reply_markup=_main_keyboard(_is_admin(update.effective_user.id)))
        return ConversationHandler.END
    if action == "list":
        rows = list_clients()
        text = "Клиентов пока нет." if not rows else "\n".join([f"• {r['key_name']} | {'активен' if r['active'] else 'блок'} | {r['traffic_human']} | дней: {r['days_left']}" for r in rows])
        await query.message.reply_text(text, reply_markup=_main_keyboard(_is_admin(update.effective_user.id)))
        return ConversationHandler.END
    if action == "connected":
        rows = connected_clients()
        text = "Сейчас никто не подключен." if not rows else "\n".join([f"• {r['key_name']}" for r in rows])
        await query.message.reply_text(text, reply_markup=_main_keyboard(_is_admin(update.effective_user.id)))
        return ConversationHandler.END
    if action == "backup":
        path = backup_all()
        with open(path, "rb") as f:
            await query.message.reply_document(f, filename=Path(path).name, caption="Бэкап OpenVPN")
        return ConversationHandler.END
    if action == "create":
        await query.message.reply_text("Введите имя ключа:")
        return STATE_CREATE_NAME
    if action == "delete":
        await query.message.reply_text("Введите имя ключа для удаления:")
        return STATE_DELETE
    if action == "recreate":
        await query.message.reply_text("Введите имя ключа для пересоздания:")
        return STATE_RECREATE
    if action == "extend":
        await query.message.reply_text("Введите имя ключа:")
        return STATE_EXTEND_NAME
    if action == "block":
        await query.message.reply_text("Введите имя ключа для блокировки:")
        return STATE_BLOCK
    if action == "unblock":
        await query.message.reply_text("Введите имя ключа для разблокировки:")
        return STATE_UNBLOCK
    if action == "add_user" and _is_admin(update.effective_user.id):
        await query.message.reply_text("Введите Telegram ID пользователя для добавления:")
        return STATE_ADD_USER
    if action == "remove_user" and _is_admin(update.effective_user.id):
        await query.message.reply_text("Введите Telegram ID пользователя для удаления:")
        return STATE_REMOVE_USER
    return ConversationHandler.END


async def create_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["create_name"] = (update.message.text or "").strip()
    await update.message.reply_text("На сколько дней создать ключ? [30]")
    return STATE_CREATE_DAYS


async def create_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get("create_name", "")
    raw = (update.message.text or "").strip() or "30"
    try:
        result = create_client(name, int(raw), actor=f"bot:{update.effective_user.id}")
        with open(result["profile_path"], "rb") as f:
            await update.message.reply_document(f, filename=Path(result["profile_path"]).name, caption=f"Ключ {result['key_name']} создан")
    except Exception as exc:
        await update.message.reply_text(f"Ошибка: {exc}")
    return ConversationHandler.END


async def delete_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        delete_client((update.message.text or "").strip(), actor=f"bot:{update.effective_user.id}")
        await update.message.reply_text("Клиент удален")
    except Exception as exc:
        await update.message.reply_text(f"Ошибка: {exc}")
    return ConversationHandler.END


async def recreate_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = recreate_client((update.message.text or "").strip(), actor=f"bot:{update.effective_user.id}")
        with open(result["profile_path"], "rb") as f:
            await update.message.reply_document(f, filename=Path(result["profile_path"]).name, caption="Ключ пересоздан")
    except Exception as exc:
        await update.message.reply_text(f"Ошибка: {exc}")
    return ConversationHandler.END


async def extend_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["extend_name"] = (update.message.text or "").strip()
    await update.message.reply_text("На сколько дней продлить? [30]")
    return STATE_EXTEND_DAYS


async def extend_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = context.user_data.get("extend_name", "")
    raw = (update.message.text or "").strip() or "30"
    try:
        new_date = extend_client(name, int(raw), actor=f"bot:{update.effective_user.id}")
        await update.message.reply_text(f"Новый срок: {new_date}")
    except Exception as exc:
        await update.message.reply_text(f"Ошибка: {exc}")
    return ConversationHandler.END


async def block_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        block_client((update.message.text or "").strip(), actor=f"bot:{update.effective_user.id}")
        await update.message.reply_text("Клиент заблокирован")
    except Exception as exc:
        await update.message.reply_text(f"Ошибка: {exc}")
    return ConversationHandler.END


async def unblock_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        unblock_client((update.message.text or "").strip(), actor=f"bot:{update.effective_user.id}")
        await update.message.reply_text("Клиент разблокирован")
    except Exception as exc:
        await update.message.reply_text(f"Ошибка: {exc}")
    return ConversationHandler.END


async def add_user_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Недостаточно прав")
        return ConversationHandler.END
    try:
        add_bot_user((update.message.text or "").strip())
        await update.message.reply_text("Пользователь добавлен")
    except Exception as exc:
        await update.message.reply_text(f"Ошибка: {exc}")
    return ConversationHandler.END


async def remove_user_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Недостаточно прав")
        return ConversationHandler.END
    try:
        remove_bot_user((update.message.text or "").strip())
        await update.message.reply_text("Пользователь удален")
    except Exception as exc:
        await update.message.reply_text(f"Ошибка: {exc}")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отмена")
    return ConversationHandler.END


def build_application() -> Application:
    settings = _settings()
    token = settings.get("bot_token") or ""
    if not token:
        raise RuntimeError("Токен Telegram-бота пустой")
    app = Application.builder().token(token).build()
    conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_router)],
        states={
            STATE_CREATE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_name)],
            STATE_CREATE_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_days)],
            STATE_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_name)],
            STATE_RECREATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, recreate_name)],
            STATE_EXTEND_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, extend_name)],
            STATE_EXTEND_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, extend_days)],
            STATE_BLOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, block_name)],
            STATE_UNBLOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, unblock_name)],
            STATE_ADD_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_user_name)],
            STATE_REMOVE_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, remove_user_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", start))
    app.add_handler(conv)
    return app


def main() -> int:
    app = build_application()
    app.run_polling(drop_pending_updates=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
