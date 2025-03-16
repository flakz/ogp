import asyncio
import logging
from typing import Dict, List, Optional, Any

import aiohttp
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, ConversationHandler, MessageHandler,
                          filters)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
AWAITING_TOKENS = 0
POSITION_URL = "https://ceremony-backend.silentprotocol.org/ceremony/position"
PING_URL = "https://ceremony-backend.silentprotocol.org/ceremony/ping"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 5
MONITOR_INTERVAL = 300

# Storage
user_tokens: Dict[int, List[str]] = {}
monitoring_tasks: Dict[int, asyncio.Task] = {}

# Callback prefixes
REMOVE_PREFIX = "remove_"
INFO_PREFIX = "info_"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Initialize the main menu."""
    keyboard = [
        [
            InlineKeyboardButton("Tokens", callback_data="tokens"),
            InlineKeyboardButton("Position", callback_data="position"),
        ],
        [
            InlineKeyboardButton("Start Monitoring", callback_data="start_monitoring"),
            InlineKeyboardButton("Stop Monitoring", callback_data="stop_monitoring"),
        ],
        [InlineKeyboardButton("About", callback_data="about")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔍 Silent Protocol Monitoring Bot\nChoose an option:",
        reply_markup=reply_markup
    )

async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[int]:
    """Process inline keyboard interactions."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    
    if user_id not in user_tokens:
        user_tokens[user_id] = []

    if query.data == "tokens":
        await show_token_menu(query)
    elif query.data == "add_tokens":
        await query.edit_message_text("📥 Send tokens (one per line):\nExample:\ntoken1\ntoken2\ntoken3")
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
    elif query.data.startswith((REMOVE_PREFIX, INFO_PREFIX)):
        await handle_token_actions(query, user_id)
    
    return ConversationHandler.END

async def show_token_menu(query: Any) -> None:
    """Display token management interface."""
    menu = InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Tokens", callback_data="add_tokens"),
         InlineKeyboardButton("Remove Tokens", callback_data="remove_tokens"),
         InlineKeyboardButton("Token Info", callback_data="token_info")],
        [InlineKeyboardButton("Main Menu", callback_data="back_to_main")]
    ])
    await query.edit_message_text("🔑 Token Management", reply_markup=menu)

async def show_remove_menu(query: Any, user_id: int) -> None:
    """Show token removal menu."""
    tokens = user_tokens.get(user_id, [])
    if not tokens:
        await query.edit_message_text("❌ No tokens to remove")
        return
    
    keyboard = [
        [InlineKeyboardButton(f"Remove ...{token[-6:]}", callback_data=f"{REMOVE_PREFIX}{i}")]
        for i, token in enumerate(tokens)
    ]
    keyboard.append([InlineKeyboardButton("Back", callback_data="tokens")])
    await query.edit_message_text("Select token to remove:", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_info_menu(query: Any, user_id: int) -> None:
    """Show token info menu."""
    tokens = user_tokens.get(user_id, [])
    if not tokens:
        await query.edit_message_text("❌ No tokens to view")
        return
    
    keyboard = [
        [InlineKeyboardButton(f"Info ...{token[-6:]}", callback_data=f"{INFO_PREFIX}{i}")]
        for i, token in enumerate(tokens)
    ]
    keyboard.append([InlineKeyboardButton("Back", callback_data="tokens")])
    await query.edit_message_text("Select token to view:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_token_actions(query: Any, user_id: int) -> None:
    """Handle token removal/info actions."""
    data = query.data
    tokens = user_tokens.get(user_id, [])
    
    if data.startswith(REMOVE_PREFIX):
        index = int(data[len(REMOVE_PREFIX):])
        if 0 <= index < len(tokens):
            removed = tokens.pop(index)
            await query.edit_message_text(f"✅ Removed token: ...{removed[-6:]}")
        else:
            await query.edit_message_text("❌ Invalid token selection")
            
    elif data.startswith(INFO_PREFIX):
        index = int(data[len(INFO_PREFIX):])
        if 0 <= index < len(tokens):
            await show_token_info(query, tokens[index])
        else:
            await query.edit_message_text("❌ Invalid token selection")

async def show_token_info(query: Any, token: str) -> None:
    """Display token information."""
    ping = await ping_server(token)
    position = await get_position(token)
    
    text = [
        f"🔐 Token: ...{token[-6:]}",
        f"🟢 Status: {ping.get('status', 'unknown') if ping else 'unavailable'}",
        f"📌 Position: {position.get('behind', 'unknown') if position else 'unavailable'}"
    ]
    
    await query.edit_message_text("\n".join(text), reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("Back", callback_data="token_info")]
    ]))

async def process_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store submitted tokens."""
    user_id = update.effective_user.id
    tokens = [t.strip() for t in update.message.text.split('\n') if t.strip()]
    
    if not tokens:
        await update.message.reply_text("❌ No valid tokens found.")
        return ConversationHandler.END
        
    user_tokens.setdefault(user_id, []).extend(tokens)
    await update.message.reply_text(
        f"✅ Added {len(tokens)} tokens\nTotal: {len(user_tokens[user_id])}",
        reply_markup=get_token_menu_markup()
    )
    return ConversationHandler.END

async def fetch_positions(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Retrieve and display positions."""
    if not user_tokens.get(user_id):
        await context.bot.send_message(user_id, "⚠️ No tokens registered")
        return

    response = ["📊 Current Positions:"]
    for token in user_tokens[user_id]:
        position = await get_position(token)
        display = f"...{token[-6:]}" if len(token) > 6 else token
        response.append(f"• {display}: {position.get('behind', 'Unavailable') if position else 'Error'}")
    
    await context.bot.send_message(user_id, "\n".join(response))

async def get_position(token: str) -> Optional[Dict]:
    """Fetch position data with retries."""
    for attempt in range(MAX_RETRIES):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as session:
                async with session.get(POSITION_URL, headers={"Authorization": f"Bearer {token}"}) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)
    return None

async def ping_server(token: str) -> Optional[Dict]:
    """Check server status with retries."""
    for attempt in range(MAX_RETRIES):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as session:
                async with session.get(PING_URL, headers={"Authorization": f"Bearer {token}"}) as response:
                    if response.status == 200:
                        return await response.json()
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY)
    return None

async def start_monitoring(query: Any, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Start monitoring service."""
    if user_id in monitoring_tasks and not monitoring_tasks[user_id].done():
        await query.edit_message_text("🔔 Monitoring already running")
        return
    
    monitoring_tasks[user_id] = asyncio.create_task(monitor_tokens(context.bot, user_id))
    await query.edit_message_text("🚀 Started monitoring - updates every 5 minutes")

async def stop_monitoring(query: Any, user_id: int) -> None:
    """Stop monitoring service."""
    if user_id in monitoring_tasks:
        monitoring_tasks[user_id].cancel()
        del monitoring_tasks[user_id]
        await query.edit_message_text("🛑 Stopped monitoring")
    else:
        await query.edit_message_text("❌ No active monitoring")

async def monitor_tokens(bot: telegram.Bot, user_id: int) -> None:
    """Continuous monitoring with status tracking."""
    prev_status = {}
    
    try:
        while True:
            updates = []
            for token in user_tokens.get(user_id, []):
                current_ping = await ping_server(token)
                current_pos = await get_position(token)
                
                status = {
                    "ping": current_ping.get("status") if current_ping else "down",
                    "position": current_pos.get("behind") if current_pos else None
                }
                
                if prev_status.get(token) != status:
                    updates.append(format_status(token, status))
                    prev_status[token] = status
            
            if updates:
                await bot.send_message(user_id, "🔄 Status Update:\n" + "\n".join(updates))
            
            await asyncio.sleep(MONITOR_INTERVAL)
            
    except asyncio.CancelledError:
        logger.info(f"Monitoring stopped for {user_id}")
    except Exception as e:
        logger.error(f"Monitoring failure: {str(e)}")
        await bot.send_message(user_id, "❌ Monitoring suspended due to errors")

def format_status(token: str, status: Dict) -> str:
    """Format status information."""
    short_token = f"...{token[-6:]}" if len(token) > 6 else token
    return (
        f"• {short_token}:\n"
        f"  Status: {status['ping'].capitalize()}\n"
        f"  Position: {status['position'] or 'Unknown'}"
    )

async def return_to_main(query: Any) -> None:
    """Return to main menu."""
    await start(query, None)

async def show_about(query: Any) -> None:
    """Show about information."""
    await query.edit_message_text(
        "🤖 Silent Protocol Monitor Bot\n\n"
        "Track your ceremony participation status\n"
        "Developed by DEFIZO",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Main Menu", callback_data="back_to_main")]])
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel current operation."""
    await update.message.reply_text("❌ Operation cancelled")
    return ConversationHandler.END

def get_token_menu_markup() -> InlineKeyboardMarkup:
    """Generate token menu markup."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Add Tokens", callback_data="add_tokens"),
         InlineKeyboardButton("Remove Tokens", callback_data="remove_tokens"),
         InlineKeyboardButton("Token Info", callback_data="token_info")],
        [InlineKeyboardButton("Main Menu", callback_data="back_to_main")]
    ])

def get_main_menu_markup() -> InlineKeyboardMarkup:
    """Generate main menu markup."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Tokens", callback_data="tokens"),
         InlineKeyboardButton("Position", callback_data="position")],
        [InlineKeyboardButton("Start Monitoring", callback_data="start_monitoring"),
         InlineKeyboardButton("Stop Monitoring", callback_data="stop_monitoring")],
        [InlineKeyboardButton("About", callback_data="about")]
    ])

def main() -> None:
    """Initialize and run the bot."""
    app = Application.builder().token("7818195044:AAHKD18hDQm8mpjTrBID7N_1Wj11NFcsAZY").build()
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(handle_button_click, pattern="^add_tokens$")],
        states={
            AWAITING_TOKENS: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_tokens)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(handle_button_click))
    
    app.run_polling()

if __name__ == "__main__":
    main()