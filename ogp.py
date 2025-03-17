import os
import asyncio
import logging
import traceback  # Added missing import
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
    return runner, app

def format_token(token: str) -> str:
    return f"...{token[-6:]}" if len(token) > 6 else token

def get_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "*/*",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }

async def get_position(token: str) -> Optional[Dict]:
    ts = format_token(token)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(POSITION_URL, headers=get_headers(token), timeout=None) as response:
                return await response.json() if response.status == 200 else None
    except Exception as e:
        logger.error(f"[{ts}] Position error: {str(e)}")
        return None

async def ping_server(token: str) -> Optional[Dict]:
    ts = format_token(token)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(PING_URL, headers=get_headers(token), timeout=None) as response:
                return await response.json() if response.status == 200 else None
    except Exception as e:
        logger.error(f"[{ts}] Ping error: {str(e)}")
        return None

async def monitor_token(bot: telegram.Bot, user_id: int, token: str) -> None:
    try:
        while True:
            ping_data = await ping_server(token)
            position_data = await get_position(token)

            status = (
                f"• *{format_token(token)}*:\n"
                f"  Status: `{ping_data.get('status', 'N/A') if ping_data else 'Error'}`\n"
                f"  Position: `{position_data.get('behind', 'N/A') if position_data else 'Error'}`"
            )

            await bot.send_message(user_id, f"🔄 Status Update:\n{status}", parse_mode="Markdown")
            await asyncio.sleep(60)  # Check every 60 seconds

    except asyncio.CancelledError:
        logger.info(f"Monitoring stopped for token {format_token(token)}")
        raise
    except Exception as e:
        logger.error(f"Critical failure: {traceback.format_exc()}")
        await bot.send_message(user_id, f"❌ Monitoring crashed for {format_token(token)} - restart required")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [
        [InlineKeyboardButton("Tokens", callback_data="tokens"), InlineKeyboardButton("Position", callback_data="position")],
        [InlineKeyboardButton("Start Monitoring", callback_data="start_monitoring"), InlineKeyboardButton("Stop Monitoring", callback_data="stop_monitoring")],
        [InlineKeyboardButton("About", callback_data="about")],
    ]
    await update.message.reply_text("🔍 Silent Protocol Monitoring Bot\nChoose an option:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user_tokens.setdefault(user_id, [])

    handlers = {
        "tokens": show_token_menu,
        "add_tokens": lambda q: q.edit_message_text("📥 Send tokens (one per line):\nExample:\ntoken1\ntoken2\ntoken3"),
        "remove_tokens": lambda q: show_remove_menu(q, user_id),
        "token_info": lambda q: show_info_menu(q, user_id),
        "back_to_main": return_to_main,
        "position": lambda: fetch_positions(context, user_id),
        "start_monitoring": lambda: start_monitoring(query, context, user_id),
        "stop_monitoring": lambda: stop_monitoring(query, user_id),
        "about": show_about
    }

    if query.data in handlers:
        return await handlers[query.data](query) if query.data in ["add_tokens"] else await handlers[query.data]()
    
    if query.data.startswith(("remove_", "info_")):
        await handle_token_actions(query, user_id)
    
    return ConversationHandler.END

async def process_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    tokens = [t.strip() for t in update.message.text.split('\n') if t.strip()]
    
    if tokens:
        user_tokens[user_id].extend(tokens)
        await update.message.reply_text(f"✅ Added {len(tokens)} tokens\nTotal: {len(user_tokens[user_id])}")
    else:
        await update.message.reply_text("❌ No valid tokens found.")
    
    return ConversationHandler.END

async def stop_monitoring(query: Any, user_id: int) -> None:
    if user_id in monitoring_tasks:
        for task in monitoring_tasks[user_id]:
            task.cancel()
        await asyncio.gather(*monitoring_tasks[user_id], return_exceptions=True)
        del monitoring_tasks[user_id]
        await query.edit_message_text("🛑 Stopped monitoring")
    else:
        await query.edit_message_text("❌ No active monitoring")

def main() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    runner = None

    try:
        runner, app = loop.run_until_complete(start_web_server())
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        
        if not bot_token:
            raise ValueError("Missing TELEGRAM_BOT_TOKEN environment variable")

        application = Application.builder().token(bot_token).build()

        conv_handler = ConversationHandler(
            entry_points=[CallbackQueryHandler(handle_button_click, pattern="^add_tokens$")],
            states={AWAITING_TOKENS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_tokens)]},
            fallbacks=[CommandHandler("cancel", cancel)]
        )

        application.add_handler(CommandHandler("start", start))
        application.add_handler(conv_handler)
        application.add_handler(CallbackQueryHandler(handle_button_click))

        logger.info("Starting services...")
        application.run_polling()

    except Exception as e:
        logger.error(f"Fatal error: {traceback.format_exc()}")
    finally:
        logger.info("Cleaning up resources...")
        if runner:
            loop.run_until_complete(runner.cleanup())
        loop.close()

if __name__ == "__main__":
    main()
