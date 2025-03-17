import os
import asyncio
import logging
import time
from typing import Dict, List, Optional, Any
from aiohttp import web

import aiohttp
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, ConversationHandler, MessageHandler,
                          filters)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
AWAITING_TOKENS = 0
POSITION_URL = "https://ceremony-backend.silentprotocol.org/ceremony/position"
PING_URL = "https://ceremony-backend.silentprotocol.org/ceremony/ping"

# Storage
user_tokens: Dict[int, List[str]] = {}
monitoring_tasks: Dict[int, List[asyncio.Task]] = {}


# Web Server Setup
async def health_handler(request):
    return web.Response(text="OK")


async def start_web_server():
    app = web.Application()
    app.router.add_get('/health', health_handler)
    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info(f"Health server running on port {port}")
    return runner


def format_token(token: str) -> str:
    return f"...{token[-6:]}" if len(token) > 6 else token


def get_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization":
        f"Bearer {token}",
        "Accept":
        "*/*",
        "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }


async def get_position(token: str) -> Optional[Dict]:
    """Get position with infinite timeout"""
    ts = format_token(token)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    POSITION_URL,
                    headers=get_headers(token),
                    timeout=None  # Infinite timeout
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.warning(
                    f"[{ts}] Position error: HTTP {response.status}")
                return None
    except Exception as e:
        logger.error(f"[{ts}] Position error: {str(e)}")
        return None


async def ping_server(token: str) -> Optional[Dict]:
    """Ping server with infinite timeout"""
    ts = format_token(token)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    PING_URL,
                    headers=get_headers(token),
                    timeout=None  # Infinite timeout
            ) as response:
                if response.status == 200:
                    return await response.json()
                logger.warning(f"[{ts}] Ping error: HTTP {response.status}")
                return None
    except Exception as e:
        logger.error(f"[{ts}] Ping error: {str(e)}")
        return None


async def monitor_token(bot: telegram.Bot, user_id: int, token: str) -> None:
    """Continuous monitoring for a single token"""
    try:
        while True:
            ping_data = await ping_server(token)
            position_data = await get_position(token)

            status = (
                f"• *{format_token(token)}*:\n"
                f"  Status: `{ping_data.get('status', 'N/A') if ping_data else 'Error'}`\n"
                f"  Position: `{position_data.get('behind', 'N/A') if position_data else 'Error'}`"
            )

            await bot.send_message(user_id,
                                   f"🔄 Status Update:\n{status}",
                                   parse_mode="Markdown")

    except asyncio.CancelledError:
        logger.info(f"Monitoring stopped for token {format_token(token)}")
    except Exception as e:
        logger.error(f"Critical failure: {traceback.format_exc()}")
        await bot.send_message(
            user_id,
            f"❌ Monitoring crashed for {format_token(token)} - restart required"
        )


# Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [
            InlineKeyboardButton("Tokens", callback_data="tokens"),
            InlineKeyboardButton("Position", callback_data="position"),
        ],
        [
            InlineKeyboardButton("Start Monitoring",
                                 callback_data="start_monitoring"),
            InlineKeyboardButton("Stop Monitoring",
                                 callback_data="stop_monitoring"),
        ],
        [InlineKeyboardButton("About", callback_data="about")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔍 Silent Protocol Monitoring Bot\nChoose an option:",
        reply_markup=reply_markup)


async def handle_button_click(
        update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if user_id not in user_tokens:
        user_tokens[user_id] = []

    if query.data == "tokens":
        await show_token_menu(query)
    elif query.data == "add_tokens":
        await query.edit_message_text(
            "📥 Send tokens (one per line):\nExample:\ntoken1\ntoken2\ntoken3")
        return AWAITING_TOKENS
    elif query.data == "remove_tokens":
        await show_remove_menu(query, user_id)
    elif query.data == "token_info":
        await show_info_menu(query, user_id)
    elif query.data == "back_to_main":
        await return_to_main(query)
    elif query.data == "position":
        await fetch_positions(context, user_id)
    elif query.data == "start_monitoring":
        await start_monitoring(query, context, user_id)
    elif query.data == "stop_monitoring":
        await stop_monitoring(query, user_id)
    elif query.data == "about":
        await show_about(query)
    elif query.data.startswith(("remove_", "info_")):
        await handle_token_actions(query, user_id)

    return ConversationHandler.END


async def show_token_menu(query: Any) -> None:
    menu = InlineKeyboardMarkup([[
        InlineKeyboardButton("Add Tokens", callback_data="add_tokens"),
        InlineKeyboardButton("Remove Tokens", callback_data="remove_tokens"),
        InlineKeyboardButton("Token Info", callback_data="token_info")
    ], [InlineKeyboardButton("Main Menu", callback_data="back_to_main")]])
    await query.edit_message_text("🔑 Token Management", reply_markup=menu)


async def show_remove_menu(query: Any, user_id: int) -> None:
    tokens = user_tokens.get(user_id, [])
    if not tokens:
        await query.edit_message_text("❌ No tokens to remove")
        return

    keyboard = [[
        InlineKeyboardButton(f"Remove {format_token(token)}",
                             callback_data=f"remove_{i}")
    ] for i, token in enumerate(tokens)]
    keyboard.append([InlineKeyboardButton("Back", callback_data="tokens")])
    await query.edit_message_text("Select token to remove:",
                                  reply_markup=InlineKeyboardMarkup(keyboard))


async def show_info_menu(query: Any, user_id: int) -> None:
    tokens = user_tokens.get(user_id, [])
    if not tokens:
        await query.edit_message_text("❌ No tokens to view")
        return

    keyboard = [[
        InlineKeyboardButton(f"Info {format_token(token)}",
                             callback_data=f"info_{i}")
    ] for i, token in enumerate(tokens)]
    keyboard.append([InlineKeyboardButton("Back", callback_data="tokens")])
    await query.edit_message_text("Select token to view:",
                                  reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_token_actions(query: Any, user_id: int) -> None:
    data = query.data
    tokens = user_tokens.get(user_id, [])

    if data.startswith("remove_"):
        index = int(data[len("remove_"):])
        if 0 <= index < len(tokens):
            removed = tokens.pop(index)
            await query.edit_message_text(
                f"✅ Removed token: {format_token(removed)}")
        else:
            await query.edit_message_text("❌ Invalid token selection")

    elif data.startswith("info_"):
        index = int(data[len("info_"):])
        if 0 <= index < len(tokens):
            await show_token_info(query, tokens[index])
        else:
            await query.edit_message_text("❌ Invalid token selection")


async def show_token_info(query: Any, token: str) -> None:
    ping = await ping_server(token)
    position = await get_position(token)

    text = [
        f"🔐 Token: {format_token(token)}",
        f"🟢 Status: {ping.get('status', 'N/A') if ping else 'Error'}",
        f"📌 Position: {position.get('behind', 'N/A') if position else 'Error'}"
    ]

    await query.edit_message_text(
        "\n".join(text),
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Back", callback_data="token_info")]]))


async def process_tokens(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    tokens = [t.strip() for t in update.message.text.split('\n') if t.strip()]

    if not tokens:
        await update.message.reply_text("❌ No valid tokens found.")
        return ConversationHandler.END

    user_tokens.setdefault(user_id, []).extend(tokens)
    await update.message.reply_text(
        f"✅ Added {len(tokens)} tokens\nTotal: {len(user_tokens[user_id])}",
        reply_markup=get_token_menu_markup())
    return ConversationHandler.END


async def fetch_positions(context: ContextTypes.DEFAULT_TYPE,
                          user_id: int) -> None:
    if not user_tokens.get(user_id):
        await context.bot.send_message(user_id, "⚠️ No tokens registered")
        return

    response = ["📊 Current Positions:"]
    for token in user_tokens[user_id]:
        position = await get_position(token)
        display = format_token(token)
        response.append(
            f"• {display}: {position.get('behind', 'Error') if position else 'Error'}"
        )

    await context.bot.send_message(user_id, "\n".join(response))


async def start_monitoring(query: Any, context: ContextTypes.DEFAULT_TYPE,
                           user_id: int) -> None:
    if user_id in monitoring_tasks:
        await query.edit_message_text("🔔 Monitoring already running")
        return

    monitoring_tasks[user_id] = []
    for token in user_tokens.get(user_id, []):
        task = asyncio.create_task(monitor_token(context.bot, user_id, token))
        monitoring_tasks[user_id].append(task)

    await query.edit_message_text(
        "🚀 Started continuous monitoring for all tokens")


async def stop_monitoring(query: Any, user_id: int) -> None:
    if user_id in monitoring_tasks:
        for task in monitoring_tasks[user_id]:
            task.cancel()
        del monitoring_tasks[user_id]
        await query.edit_message_text("🛑 Stopped monitoring")
    else:
        await query.edit_message_text("❌ No active monitoring")


async def return_to_main(query: Any) -> None:
    await start(query, None)


async def show_about(query: Any) -> None:
    await query.edit_message_text(
        "🤖 Silent Protocol Monitor Bot\n\n"
        "Track your ceremony participation status\n"
        "Developed by DEFIZO",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("Main Menu",
                                   callback_data="back_to_main")]]))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Operation cancelled")
    return ConversationHandler.END


def get_token_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Add Tokens", callback_data="add_tokens"),
        InlineKeyboardButton("Remove Tokens", callback_data="remove_tokens"),
        InlineKeyboardButton("Token Info", callback_data="token_info")
    ], [InlineKeyboardButton("Main Menu", callback_data="back_to_main")]])


def get_main_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Tokens", callback_data="tokens"),
            InlineKeyboardButton("Position", callback_data="position")
        ],
         [
             InlineKeyboardButton("Start Monitoring",
                                  callback_data="start_monitoring"),
             InlineKeyboardButton("Stop Monitoring",
                                  callback_data="stop_monitoring")
         ], [InlineKeyboardButton("About", callback_data="about")]])


def main() -> None:
    loop = asyncio.get_event_loop()

    try:
        web_server = loop.run_until_complete(start_web_server())

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable")

        application = Application.builder().token(bot_token).build()

        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(handle_button_click,
                                     pattern="^add_tokens$")
            ],
            states={
                AWAITING_TOKENS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   process_tokens)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)])

        application.add_handler(CommandHandler("start", start))
        application.add_handler(conv_handler)
        application.add_handler(CallbackQueryHandler(handle_button_click))

        logger.info("Starting services...")
        application.run_polling()

    except KeyboardInterrupt:
        logger.info("Initiating graceful shutdown...")
    finally:
        loop.run_until_complete(web_server.cleanup())
        logger.info("All services stopped")


if __name__ == "__main__":
    main()
