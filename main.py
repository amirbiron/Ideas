# Configuration constants
IDEAS_PER_PAGE = 10
import os
import sys
import signal
import atexit
import logging
import time

# --- Start of Improved Lock File Code ---

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

LOCK_FILE = "bot.lock"

def is_process_running(pid):
    """Check if a process with the given PID is running."""
    try:
        # os.kill(pid, 0) doesn't send a signal, but checks for process existence.
        # It will raise a ProcessLookupError if the process doesn't exist.
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True

def create_lock():
    """Create a lock file, ensuring no other instance is running."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            
            if is_process_running(old_pid):
                logger.error(f"🔒 Bot already running (PID: {old_pid}). Exiting.")
                sys.exit(1)
            else:
                logger.warning("⚠️ Stale lock file found for a non-running process. Overwriting.")
        except (ValueError, FileNotFoundError):
             logger.warning("⚠️ Lock file is invalid. Overwriting.")

    # Register cleanup before creating the file to handle interruptions
    atexit.register(remove_lock)
    
    # Create the new lock file
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    logger.info(f"✅ Lock file created (PID: {os.getpid()})")

def remove_lock():
    """Remove the lock file if it belongs to the current process."""
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE, "r") as f:
                pid_in_file = int(f.read().strip())
            if pid_in_file == os.getpid():
                os.remove(LOCK_FILE)
                logger.info("🧹 Lock file removed.")
    except (IOError, ValueError) as e:
        logger.warning(f"Could not remove lock file on exit: {e}")

# --- Main Logic ---
create_lock()

# ===============================================================
# Your existing bot code starts here.
# For example:
#
# from telegram.ext import Application
#
# def main() -> None:
#     try:
#         logger.info("Bot is starting up...")
#         application = Application.builder().token("YOUR_TOKEN_HERE").build()
#         # ... add your handlers, etc.
#         application.run_polling()
#     finally:
#         # The atexit handler is usually enough, but this is for extra safety
#         remove_lock() 
#
# if __name__ == "__main__":
#     main()
# ===============================================================

# Example of a running process for testing:
try:
    logger.info("🤖 Bot logic would be running here...")
    # Keep the script alive to simulate a running bot
    while True:
        time.sleep(60) 
except KeyboardInterrupt:
    logger.info("🛑 Bot shutting down manually.")
finally:
    # The atexit handler will be called automatically, no need to call remove_lock() here
    pass

# ===============================================================
# Your existing bot code starts here.
# For example:
#
# from telegram.ext import Application
#
# def main() -> None:
#     """Start the bot."""
#     application = Application.builder().token("YOUR_TOKEN_HERE").build()
#     # ... add your handlers, etc.
#     application.run_polling()
#
# if __name__ == "__main__":
#     logger.info("Bot is starting up...")
#     main()
# ===============================================================


import logging
import os
import sys
from threading import Thread
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask
from pymongo import MongoClient
from openai import AsyncOpenAI
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
    ConversationHandler, CallbackQueryHandler
)
from telegram.error import Conflict

# --- Environment Setup ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
# --- ✨ New Environment Variable for Run Mode ---
RUN_MODE = os.getenv("RUN_MODE", "bot")

# --- Validations ---
if not all([TELEGRAM_TOKEN, OPENAI_API_KEY, MONGO_URI]):
    print("Error: Missing one or more environment variables")
    sys.exit(1)

# --- Client Initializations ---
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger('werkzeug').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    if isinstance(context.error, Conflict):
        logger.warning("Conflict error detected. Another bot instance might be running. This is often caused by a cron job re-running the bot script.")
        return
    try:
        if isinstance(update, Update) and update.effective_chat:
            text = "אופס, משהו השתבש. אני מתנצל, אבל לא הצלחתי לעבד את הבקשה האחרונה שלך."
            await context.bot.send_message(chat_id=update.effective_chat.id, text=text)
    except Exception as e:
        logger.error(f"Failed to send error message to user: {e}", exc_info=e)

# --- Database Setup (MongoDB) ---
try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client.ideas_bot_db
    entries_collection = db.user_entries
    mongo_client.admin.command('ping')
    logger.info("✅ Successfully connected to MongoDB.")
except Exception as e:
    logger.error(f"❌ Could not connect to MongoDB: {e}")
    sys.exit(1)

# --- Data Functions ---
def save_entry(user_id: str, content: str, category: str):
    entry = {"user_id": user_id, "content": content, "category": category, "created_at": datetime.utcnow()}
    entries_collection.insert_one(entry)

def get_user_entries(user_id: str, category: str, limit: int = None):
    query = {"user_id": user_id, "category": category}
    cursor = entries_collection.find(query).sort("created_at", -1)
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)

def get_all_user_entries(user_id: str, limit: int = 10):
    return list(entries_collection.find({"user_id": user_id}).sort("created_at", -1).limit(limit))

def get_user_entries_paginated(user_id: str, page: int = 0, per_page: int = IDEAS_PER_PAGE):
    skip = page * per_page
    return list(entries_collection.find({"user_id": user_id}).sort("created_at", -1).skip(skip).limit(per_page))

def count_user_entries(user_id: str):
    return entries_collection.count_documents({"user_id": user_id})

def delete_user_entries(user_id: str):
    return entries_collection.delete_many({"user_id": user_id}).deleted_count

# --- OpenAI Logic ---
async def generate_ideas(user_entries: list, category: str) -> str:
    if not user_entries:
        return f"אין לך עדיין רשומות בקטגוריית '{category}'. כתוב לי כמה דברים קודם!"
    
    # משתמש בכל הרעיונות, לא רק ב-20 הראשונים
    entries_text = "\n".join([f"- {entry['content']}" for entry in user_entries])
    
    # פרומפט משופר שמדגיש הישארות נאמן לסגנון
    prompt = f"""על בסיס כל הרעיונות שלי בקטגוריית '{category}':

{entries_text}

אנא נתח בעמקות את הסגנון, הטון, רמת הפירוט, סוג המילים והביטויים שאני משתמש בהם, ואת הנושאים הספציפיים שמעניינים אותי. 

לאחר מכן, הצע 15 רעיונות חדשים שמחקים בדיוק את הסגנון שלי - כאילו אני בעצמי כתבתי אותם.

חשוב מאוד:
- היצמד לסגנון הכתיבה שלי בדיוק - אותו טון, אותה רמת פירוט, אותו סוג מילים
- שמור על אותם נושאים ותחומי עניין שאני כותב עליהם
- הרעיונות צריכים להרגיש טבעיים וכאילו הם באים ממני
- אל תהיה גנרי - היה ספציפי כמו שאני
- אם מדובר ברעיונות לבוטים: התמקד דווקא בבוטים טכנולוגיים עם נושא פרוקטיביות, ולא בנושאים של ניהול סדר יום, תזכורות או משימות יומיומיות

כתוב 15 רעיונות בעברית, כל אחד בשורה נפרדת עם מספר."""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": f"אתה מומחה בניתוח וחיקוי סגנון כתיבה אישי. המשימה שלך היא לנתח בעמקות את סגנון הכתיבה של המשתמש בתחום '{category}' - איך הוא כותב, איזה מילים הוא בוחר, איזה רמת פירוט, איזה נושאים ספציפיים מעניינים אותו. לאחר מכן, ייצר רעיונות חדשים שמרגישים כאילו המשתמש בעצמו כתב אותם. התמקד בייחודיות שלו ואל תהיה גנרי. חשוב: כשמדובר ברעיונות לבוטים, התמקד דווקא בבוטים טכנולוגיים עם נושא פרוקטיביות, ולא בנושאים של ניהול סדר יום, תזכורות או משימות יומיומיות."},
                {"role": "user", "content": prompt}
                          ], max_tokens=2500, temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error calling OpenAI: {e}")
        return "סליחה, יש לי בעיה טכנית עם יצירת הרעיונות. נסה שוב מאוחר יותר."

# --- Conversation Handler States ---
CHOOSE_CATEGORY, AWAITING_IDEAS, CHOOSE_CATEGORY_FOR_LIST = range(3)

# --- Pagination Constants ---
IDEAS_PER_PAGE = 10

# --- Keyboards ---
def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🤖 בקש רעיון לבוט", callback_data='main_idea_bots')],
        [InlineKeyboardButton("📖 בקש רעיון למדריך", callback_data='main_idea_guides')],
        [InlineKeyboardButton("📚 הצג את הרעיונות שלי", callback_data='main_my_ideas')],
        [InlineKeyboardButton("➕ הוסף רשימת רעיונות", callback_data='main_add_list')]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_to_menu_keyboard():
    keyboard = [[InlineKeyboardButton("⬅️ חזור לתפריט", callback_data='main_show_menu')]]
    return InlineKeyboardMarkup(keyboard)

def get_pagination_keyboard(current_page: int, total_pages: int, has_next: bool, has_prev: bool):
    keyboard = []
    
    # שורה של כפתורי ניווט
    nav_row = []
    if has_prev:
        nav_row.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f'page_{current_page - 1}'))
    
    nav_row.append(InlineKeyboardButton(f"עמוד {current_page + 1} מתוך {total_pages}", callback_data='page_info'))
    
    if has_next:
        nav_row.append(InlineKeyboardButton("הבא ➡️", callback_data=f'page_{current_page + 1}'))
    
    keyboard.append(nav_row)
    
    # כפתור חזרה לתפריט
    keyboard.append([InlineKeyboardButton("⬅️ חזור לתפריט", callback_data='main_show_menu')])
    
    return InlineKeyboardMarkup(keyboard)

def get_category_keyboard():
    keyboard = [
        [InlineKeyboardButton("יצירת בוטים", callback_data='category_יצירת בוטים')],
        [InlineKeyboardButton("מדריכים", callback_data='category_מדריכים')],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Menu Functions ---
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    reply_markup = get_main_menu_keyboard()
    if update.callback_query:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = "שלום! אני מכונת הרעיונות שלך. תוכל לכתוב לי רעיון או להשתמש בתפריט:"
    await show_main_menu(update, context, welcome_text)

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update, context, "תפריט ראשי:")

# --- Button Click (CallbackQuery) Handler ---
async def button_click_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() 
    
    # טיפול בכפתורי ניווט עמודים
    if query.data.startswith('page_'):
        page_data = query.data.replace('page_', '')
        if page_data == 'info':
            return  # לא לעשות כלום אם לוחצים על מידע העמוד
        try:
            page = int(page_data)
            await show_my_ideas_command(update, context, page)
            return
        except ValueError:
            pass
    
    command = query.data.replace('main_', '')
    
    if command == 'idea_bots':
        await get_idea_by_category(update, context, category="יצירת בוטים")
    elif command == 'idea_guides':
        await get_idea_by_category(update, context, category="מדריכים")
    elif command == 'my_ideas':
        await show_my_ideas_command(update, context)
    elif command == 'show_menu':
        await show_main_menu(update, context, "תפריט ראשי:")

# --- Command Logic ---
async def get_idea_by_category(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    user_id = str(update.effective_user.id)
    message = update.callback_query.message
    await message.edit_text(f"🤔 חושב על רעיונות בשבילך בקטגוריית '{category}'...", reply_markup=None)
    entries = get_user_entries(user_id, category)
    ideas = await generate_ideas(entries, category)
    await message.edit_text(f"💡 הנה הרעיונות שלך:\n\n{ideas}", reply_markup=get_back_to_menu_keyboard())

async def show_my_ideas_command(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0):
    user_id = str(update.effective_user.id)
    total_entries = count_user_entries(user_id)
    
    if total_entries == 0:
        message = update.callback_query.message if update.callback_query else update.message
        await message.edit_text("אין לך עדיין רשומות. כתוב לי משהו קודם!", reply_markup=get_back_to_menu_keyboard())
        return
    
    entries = get_user_entries_paginated(user_id, page, IDEAS_PER_PAGE)
    total_pages = (total_entries + IDEAS_PER_PAGE - 1) // IDEAS_PER_PAGE
    
    has_next = page < total_pages - 1
    has_prev = page > 0
    
    text = f"📚 הרעיונות שלך (עמוד {page + 1} מתוך {total_pages}):\n\n"
    
    start_index = page * IDEAS_PER_PAGE + 1
    for i, entry in enumerate(entries, start_index):
        content = entry['content']
        category = entry.get('category', 'ללא קטגוריה') 
        date_obj = entry['created_at']
        date_str = date_obj.strftime('%d/%m %H:%M')
        short_content = content[:60] + "..." if len(content) > 60 else content
        text += (f"*{i}. {short_content}*\n"
                 f"*קטגוריה:* {category} | *תאריך:* {date_str}\n\n")
    
    text += f"\n📊 סך הכל: {total_entries} רעיונות"
    
    reply_markup = get_pagination_keyboard(page, total_pages, has_next, has_prev)
    
    message = update.callback_query.message if update.callback_query else update.message
    await message.edit_text(text, parse_mode='Markdown', reply_markup=reply_markup)

async def delete_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    deleted_count = delete_user_entries(user_id)
    await update.message.reply_text(f"🗑️ נמחקו {deleted_count} רשומות.")

# --- Single Entry Conversation ---
async def text_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_entry_content'] = update.message.text
    await update.message.reply_text("לאיזו קטגוריה לשייך את הרעיון?", reply_markup=get_category_keyboard())
    return CHOOSE_CATEGORY

async def category_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    category = query.data.split('_')[1]
    content = context.user_data.pop('new_entry_content', None)
    
    if not content:
        await query.message.edit_text("אופס, משהו השתבש. נסה שוב.", reply_markup=get_back_to_menu_keyboard())
        return ConversationHandler.END

    save_entry(str(query.from_user.id), content, category)
    await query.message.edit_text(f"✅ רשמתי! הרעיון נשמר בקטגוריית '{category}'.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("הפעולה בוטלה.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# --- List Entry Conversation ---
async def start_list_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['idea_list'] = []
    await query.message.edit_text("מעולה. שלח לי את הרעיונות שלך, **כל אחד בהודעה נפרדת**.\n"
                                   "כשתסיים, שלח את הפקודה /done.", parse_mode='Markdown')
    return AWAITING_IDEAS

async def add_to_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    idea_list = context.user_data.get('idea_list', [])
    idea_list.append(update.message.text)
    context.user_data['idea_list'] = idea_list
    await update.message.reply_text(f"👍 קיבלתי! (נאספו {len(idea_list)} רעיונות). שלח את הבא, או /done לסיום.")
    return AWAITING_IDEAS

async def ask_category_for_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    idea_list = context.user_data.get('idea_list', [])
    if not idea_list:
        await update.message.reply_text("לא הזנת רעיונות. חוזר לתפריט הראשי.", reply_markup=get_main_menu_keyboard())
        context.user_data.clear()
        return ConversationHandler.END
    
    await update.message.reply_text(f"קיבלתי {len(idea_list)} רעיונות. לאיזו קטגוריה לשייך אותם?", reply_markup=get_category_keyboard())
    return CHOOSE_CATEGORY_FOR_LIST

async def save_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    category = query.data.split('_')[1]
    idea_list = context.user_data.pop('idea_list', [])
    user_id = str(query.from_user.id)

    for idea in idea_list:
        save_entry(user_id, idea, category)
    
    await query.message.edit_text(f"✅ הצלחה! {len(idea_list)} רעיונות חדשים נשמרו בקטגוריית '{category}'.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

async def cancel_list_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("הוספת הרשימה בוטלה. חוזר לתפריט הראשי.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

# --- Main Application Setup and Execution ---
def run_bot():
    """Initializes and runs the Telegram bot."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_error_handler(error_handler)

    single_entry_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, text_entry)],
        states={ CHOOSE_CATEGORY: [CallbackQueryHandler(category_choice, pattern='^category_')] },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )

    list_entry_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_list_entry, pattern='^main_add_list$')],
        states={
            AWAITING_IDEAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_to_list)],
            CHOOSE_CATEGORY_FOR_LIST: [CallbackQueryHandler(save_list, pattern='^category_')]
        },
        fallbacks=[
            CommandHandler('done', ask_category_for_list),
            CommandHandler('cancel', cancel_list_conversation)
        ],
    )
    
    application.add_handler(list_entry_conv)
    application.add_handler(single_entry_conv)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("clear_all", delete_all_command))
    application.add_handler(CallbackQueryHandler(button_click_handler, pattern='^page_'))
    application.add_handler(CallbackQueryHandler(button_click_handler, pattern='^main_(?!add_list)'))

    logger.info("Starting bot in polling mode...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

def run_scheduled_job():
    """Runs a scheduled job. Placeholder for future cron tasks."""
    logger.info("Running a scheduled job...")
    # TODO: Add your cron job logic here
    # For example: db.cleanup_old_entries()
    logger.info("Scheduled job finished.")

if __name__ == "__main__":
    logger.info(f"Starting application in '{RUN_MODE}' mode.")
    
    if RUN_MODE == "bot":
        # The Flask server is only needed for the keep-alive mechanism of the bot
        flask_app = Flask(__name__)
        @flask_app.route('/')
        def health_check(): return "I'm alive!", 200
        
        flask_thread = Thread(target=lambda: flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080))))
        flask_thread.daemon = True
        flask_thread.start()
        
        run_bot()
        
    elif RUN_MODE == "cron":
        run_scheduled_job()
        
    else:
        logger.error(f"Unknown RUN_MODE: '{RUN_MODE}'. Exiting.")
        sys.exit(1)
