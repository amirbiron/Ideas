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
# --- Added import for the error handler ---
from telegram.error import Conflict

# --- Environment Setup ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

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

# --- ✨ Custom Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    logger.error("Exception while handling an update:", exc_info=context.error)

    if isinstance(context.error, Conflict):
        logger.warning("Conflict error detected. Another bot instance might be running.")
        # No need to inform the user, as this is a backend issue.
        return

    # You can add more specific error handling here if needed
    
    # Finally, send a generic message to the user
    try:
        if isinstance(update, Update) and update.effective_chat:
            text = "אופס, משהו השתבש. אני מתנצל, אבל לא הצלחתי לעבד את הבקשה האחרונה שלך. הצוות שלי קיבל על כך הודעה."
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

def get_user_entries(user_id: str, category: str, limit: int = 50):
    return list(entries_collection.find({"user_id": user_id, "category": category}).sort("created_at", -1).limit(limit))

def get_all_user_entries(user_id: str, limit: int = 10):
    return list(entries_collection.find({"user_id": user_id}).sort("created_at", -1).limit(limit))

def delete_user_entries(user_id: str):
    return entries_collection.delete_many({"user_id": user_id}).deleted_count

# --- OpenAI Logic ---
async def generate_ideas(user_entries: list, category: str) -> str:
    if not user_entries:
        return f"אין לך עדיין רשומות בקטגוריית '{category}'. כתוב לי כמה דברים קודם!"
    
    entries_text = "\n".join([f"- {entry['content']}" for entry in user_entries[:20]])
    prompt = f"""
אתה מכונת רעיונות חכמה. קיבלת את הדברים הבאים שמשתמש כתב בקטגוריה '{category}':
{entries_text}
על בסיס הדברים שהוא כתב, הצע לו 3 רעיונות חדשים ומעניינים שמתאימים לסגנון שלו ולתחומי העניין שלו, ספציפית בתחום של '{category}'.
כתוב בעברית בצורה ידידותית וחמה.
"""
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": f"אתה מכונת רעיונות חכמה שכותבת בעברית ומתמחה בתחום '{category}'."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000, temperature=0.8
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error calling OpenAI: {e}")
        return "סליחה, יש לי בעיה טכנית עם יצירת הרעיונות. נסה שוב מאוחר יותר."

# --- Conversation Handler States ---
CHOOSE_CATEGORY = range(1)

# --- Keyboards ---
def get_main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🤖 בקש רעיון לבוט", callback_data='main_idea_bots')],
        [InlineKeyboardButton("📖 בקש רעיון למדריך", callback_data='main_idea_guides')],
        [InlineKeyboardButton("📚 הצג את הרעיונות שלי", callback_data='main_my_ideas')],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_to_menu_keyboard():
    keyboard = [[InlineKeyboardButton("⬅️ חזור לתפריט", callback_data='main_show_menu')]]
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
    await message.edit_text(f"🤔 חושב על רעיונות בשבילך בקטגוריית '{category}'...")
    entries = get_user_entries(user_id, category)
    ideas = await generate_ideas(entries, category)
    await message.edit_text(f"💡 הנה הרעיונות שלך:\n\n{ideas}", reply_markup=get_back_to_menu_keyboard())

async def show_my_ideas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    entries = get_all_user_entries(user_id, limit=10)
    message = update.callback_query.message
    
    if not entries:
        await message.edit_text("אין לך עדיין רשומות. כתוב לי משהו קודם!", reply_markup=get_back_to_menu_keyboard())
        return
    
    text = "📚 10 הרשומות האחרונות שלך (מכל הקטגוריות):\n\n"
    for i, entry in enumerate(entries, 1):
        content = entry['content']
        category = entry.get('category', 'ללא קטגוריה') 
        date_obj = entry['created_at']
        date_str = date_obj.strftime('%d/%m %H:%M')
        short_content = content[:60] + "..." if len(content) > 60 else content
        text += f"*{i}. {short_content}*\n*קטגוריה:* {category} | *תאריך:* {date_str}\n\n"
    
    await message.edit_text(text, parse_mode='Markdown', reply_markup=get_back_to_menu_keyboard())

async def delete_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    deleted_count = delete_user_entries(user_id)
    response_text = f"🗑️ נמחקו {deleted_count} רשומות." if deleted_count > 0 else "לא היו רשומות למחיקה."
    await update.message.reply_text(response_text)

# --- Conversation Logic for saving entries ---
async def text_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['new_entry_content'] = update.message.text
    keyboard = [
        [InlineKeyboardButton("יצירת בוטים", callback_data='category_יצירת בוטים')],
        [InlineKeyboardButton("מדריכים", callback_data='category_מדריכים')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("לאיזו קטגוריה לשייך את הרעיון?", reply_markup=reply_markup)
    return CHOOSE_CATEGORY

async def category_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    category = query.data.split('_')[1]
    content = context.user_data.pop('new_entry_content', None)
    user_id = str(update.effective_user.id)

    if not content:
        await query.message.edit_text("אופס, משהו השתבש. נסה לשלוח את הרעיון שוב.", reply_markup=get_back_to_menu_keyboard())
        return ConversationHandler.END

    save_entry(user_id, content, category)
    await query.message.edit_text(f"✅ רשמתי! הרעיון נשמר בקטגוריית '{category}'.", reply_markup=get_main_menu_keyboard())
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await show_main_menu(update, context, "הפעולה בוטלה. חוזר לתפריט הראשי:")
    return ConversationHandler.END

# --- Flask Keep-Alive Server ---
flask_app = Flask(__name__)
@flask_app.route('/')
def health_check(): return "I'm alive!", 200
def run_flask(): flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

# --- Main Application Setup ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # --- Add the error handler ---
    application.add_error_handler(error_handler)

    # --- Add other handlers ---
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, text_entry)],
        states={
            CHOOSE_CATEGORY: [CallbackQueryHandler(category_choice, pattern='^category_')],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(conv_handler)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("clear_all", delete_all_command))
    application.add_handler(CallbackQueryHandler(button_click_handler, pattern='^main_'))

    logger.info("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    main()
