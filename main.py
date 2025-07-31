import logging
import os
import sys
from threading import Thread
from datetime import datetime

from dotenv import load_dotenv
from flask import Flask
from pymongo import MongoClient
from openai import AsyncOpenAI
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
    ConversationHandler
)

# --- Environment Setup ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

# --- Validations ---
if not all([TELEGRAM_TOKEN, OPENAI_API_KEY, MONGO_URI]):
    print("Error: Missing one or more environment variables (TELEGRAM_TOKEN, OPENAI_API_KEY, MONGO_URI)")
    sys.exit(1)

# --- Client Initializations ---
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

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

# --- Data Functions (MongoDB implementation) ---
def save_entry(user_id: str, content: str, category: str):
    entry = {
        "user_id": user_id,
        "content": content,
        "category": category,
        "created_at": datetime.utcnow()
    }
    entries_collection.insert_one(entry)

def get_user_entries(user_id: str, category: str, limit: int = 50):
    return list(entries_collection.find({"user_id": user_id, "category": category}).sort("created_at", -1).limit(limit))

def get_all_user_entries(user_id: str, limit: int = 10):
    return list(entries_collection.find({"user_id": user_id}).sort("created_at", -1).limit(limit))

def delete_user_entries(user_id: str):
    result = entries_collection.delete_many({"user_id": user_id})
    return result.deleted_count

# --- OpenAI Logic ---
async def generate_ideas(user_entries: list, category: str) -> str:
    if not user_entries:
        return f"אין לך עדיין רשומות בקטגוריית '{category}'. כתוב לי כמה דברים קודם!"
    
    entries_text = "\n".join([f"- {entry['content']}" for entry in user_entries[:20]])
    
    prompt = f"""
אתה מכונת רעיונות חכמה. קיבלת את הדברים הבאים שמשתמש כתב בקטגוריה '{category}':

{entries_text}

על בסיס הדברים שהוא כתב, הצע לו 3 רעיונות חדשים ומעניינים שמתאימים לסגנון שלו ולתחומי העניין שלו, ספציפית בתחום של '{category}'.
הרעיונות צריכים להיות:
1. מעשיים ובני-ביצוע
2. בסגנון שלו
3. משהו שהוא עדיין לא עשה

כתוב בעברית בצורה ידידותית וחמה.
"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": f"אתה מכונת רעיונות חכמה שכותבת בעברית ומתמחה בתחום '{category}'."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000,  # Increased token limit
            temperature=0.8
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error calling OpenAI: {e}")
        return "סליחה, יש לי בעיה טכנית עם יצירת הרעיונות. נסה שוב מאוחר יותר."

# --- Conversation Handler States ---
CHOOSE_CATEGORY = range(1)

# --- Telegram Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = """
🧠 שלום! אני מכונת הרעיונות שלך!

איך זה עובד?
1️⃣ כתוב לי כל דבר - רעיון, מחשבה, פרויקט.
2️⃣ אני אשאל אותך לאיזו קטגוריה לשייך את הרעיון: "יצירת בוטים" או "מדריכים".
3️⃣ בקש רעיונות חדשים לפי קטגוריה!

פקודות זמינות:
🤖 /idea_bots - קבל רעיונות ליצירת בוטים
📖 /idea_guides - קבל רעיונות לכתיבת מדריכים
📚 /my_ideas - צפה בהיסטוריה שלך
🗑️ /clear_all - מחק את כל הנתונים שלך
❓ /help - הצג הודעה זו

בוא נתחיל! כתוב לי משהו...
"""
    await update.message.reply_text(welcome_message)

async def get_idea_by_category(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str):
    user_id = str(update.effective_user.id)
    await update.message.reply_text(f"🤔 חושב על רעיונות בשבילך בקטגוריית '{category}'...")
    entries = get_user_entries(user_id, category)
    ideas = await generate_ideas(entries, category)
    await update.message.reply_text(f"💡 הנה הרעיונות שלך:\n\n{ideas}")

async def idea_bots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await get_idea_by_category(update, context, category="יצירת בוטים")

async def idea_guides_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await get_idea_by_category(update, context, category="מדריכים")

async def show_my_ideas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    entries = get_all_user_entries(user_id, limit=10)
    
    if not entries:
        await update.message.reply_text("אין לך עדיין רשומות. כתוב לי משהו קודם!")
        return
    
    message = "📚 10 הרשומות האחרונות שלך (מכל הקטגוריות):\n\n"
    for i, entry in enumerate(entries, 1):
        content = entry['content']
        category = entry['category']
        date_obj = entry['created_at']
        date_str = date_obj.strftime('%d/%m %H:%M')
        
        short_content = content[:60] + "..." if len(content) > 60 else content
        message += f"*{i}. {short_content}*\n*קטגוריה:* {category} | *תאריך:* {date_str}\n\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def delete_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    deleted_count = delete_user_entries(user_id)
    
    if deleted_count > 0:
        await update.message.reply_text(f"🗑️ נמחקו {deleted_count} רשומות מהמאגר שלך")
    else:
        await update.message.reply_text("אין לך רשומות למחיקה")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context) # The start message is a good help message

# --- Conversation Logic for saving entries ---
async def text_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the conversation to categorize a new text entry."""
    context.user_data['new_entry_content'] = update.message.text
    reply_keyboard = [["יצירת בוטים", "מדריכים"]]
    await update.message.reply_text(
        "לאיזו קטגוריה לשייך את הרעיון הזה?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True),
    )
    return CHOOSE_CATEGORY

async def category_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle the category choice and save the entry."""
    category = update.message.text
    content = context.user_data.pop('new_entry_content', None)
    user_id = str(update.effective_user.id)

    if not content:
        await update.message.reply_text("אופס, משהו השתבש. נסה לשלוח את הרעיון שוב.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    save_entry(user_id, content, category)
    await update.message.reply_text(f"✅ רשמתי! הרעיון נשמר בקטגוריית '{category}'.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text("הפעולה בוטלה.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- Flask Keep-Alive Server ---
flask_app = Flask(__name__)
@flask_app.route('/')
def health_check(): return "I'm alive!", 200
def run_flask(): flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

# --- Main Application Setup ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Conversation handler for adding new entries
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, text_entry)],
        states={
            CHOOSE_CATEGORY: [MessageHandler(filters.Regex("^(יצירת בוטים|מדריכים)$"), category_choice)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conversation)],
    )
    application.add_handler(conv_handler)

    # Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("idea_bots", idea_bots_command))
    application.add_handler(CommandHandler("idea_guides", idea_guides_command))
    application.add_handler(CommandHandler("my_ideas", show_my_ideas_command))
    application.add_handler(CommandHandler("clear_all", delete_all_command))
    application.add_handler(CommandHandler("help", help_command))
    
    logger.info("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    main()
