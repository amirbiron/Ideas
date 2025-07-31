import logging
import os
import sys
from threading import Thread
from datetime import datetime

import openai
from dotenv import load_dotenv
from flask import Flask
from pymongo import MongoClient
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- Environment Setup ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

# --- Validations ---
if not TELEGRAM_TOKEN:
    print("Error: TELEGRAM_TOKEN environment variable not set.")
    sys.exit(1)
if not OPENAI_API_KEY:
    print("Error: OPENAI_API_KEY environment variable not set.")
    sys.exit(1)
if not MONGO_URI:
    print("Error: MONGO_URI environment variable not set.")
    sys.exit(1)

openai.api_key = OPENAI_API_KEY

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Database Setup (MongoDB) ---
try:
    client = MongoClient(MONGO_URI)
    db = client.ideas_bot_db  # You can name your database whatever you want
    entries_collection = db.user_entries # The collection to store entries
    # The following line tests the connection.
    client.admin.command('ping')
    logger.info("✅ Successfully connected to MongoDB.")
except Exception as e:
    logger.error(f"❌ Could not connect to MongoDB: {e}")
    sys.exit(1)

# --- Data Functions (MongoDB implementation) ---
def save_entry(user_id: str, content: str):
    """Saves a new entry for a user in MongoDB."""
    entry = {
        "user_id": user_id,
        "content": content,
        "created_at": datetime.utcnow()
    }
    entries_collection.insert_one(entry)

def get_user_entries(user_id: str, limit: int = 50):
    """Retrieves entries for a user from MongoDB, sorted by date."""
    return list(entries_collection.find({"user_id": user_id}).sort("created_at", -1).limit(limit))

def delete_user_entries(user_id: str):
    """Deletes all entries for a user from MongoDB."""
    result = entries_collection.delete_many({"user_id": user_id})
    return result.deleted_count

# --- OpenAI Logic (Your original logic) ---
async def generate_ideas(user_entries: list) -> str:
    """Generates ideas using OpenAI based on user history."""
    if not user_entries:
        return "אין לך עדיין רשומות במאגר. כתוב לי כמה דברים קודם!"
    
    entries_text = "\n".join([f"- {entry['content']}" for entry in user_entries[:20]])
    
    prompt = f"""
אתה מכונת רעיונות חכמה. קיבלת את הדברים הבאים שמשתמש כתב:

{entries_text}

על בסיס הדברים שהוא כתב, הצע לו 3 רעיונות חדשים ומעניינים שמתאימים לסגנון שלו ולתחומי העניין שלו.
הרעיונות צריכים להיות:
1. מעשיים ובני-ביצוע
2. בסגנון שלו
3. משהו שהוא עדיין לא עשה

כתוב בעברית בצורה ידידותית וחמה.
"""

    try:
        response = await openai.chat.completions.acreate(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "אתה מכונת רעיונות חכמה שכותבת בעברית"},
                {"role": "user", "content": prompt}
            ],
            max_tokens=500,
            temperature=0.8
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error calling OpenAI: {e}")
        return "סליחה, יש לי בעיה טכנית עם יצירת הרעיונות. נסה שוב מאוחר יותר."

# --- Telegram Command Handlers (Your original logic) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = """
🧠 שלום! אני מכונת הרעיונות שלך!

איך זה עובד?
📝 כתוב לי כל דבר - רעיונות, מחשבות, פרויקטים. כל הודעה נשמרת.
🎯 כשתכתוב /get_idea - אני אציע לך רעיונות חדשים בהתבסס על מה שכתבת.

פקודות זמינות:
/get_idea - קבל רעיונות חדשים
/my_ideas - צפה בהיסטוריה שלך
/clear_all - מחק את כל הנתונים שלך
/help - הצג הודעה זו

בוא נתחיל! כתוב לי משהו...
"""
    await update.message.reply_text(welcome_message)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    content = update.message.text
    save_entry(user_id, content)
    
    count = entries_collection.count_documents({"user_id": user_id})
    
    responses = [
        f"💾 נשמר! יש לך כבר {count} רשומות במאגר",
        f"✅ קלט! {count} רשומות במאגר שלך",
        f"📚 נוסף למאגר הרעיונות! ({count} רשומות בסך הכל)",
        f"🎯 רשמתי! {count} פריטים במכונת הרעיונות שלך"
    ]
    response = responses[count % len(responses)]
    await update.message.reply_text(response)

async def get_idea_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    await update.message.reply_text("🤔 חושב על רעיונות בשבילך...")
    entries = get_user_entries(user_id)
    ideas = await generate_ideas(entries)
    await update.message.reply_text(f"💡 הנה הרעיונות שלך:\n\n{ideas}")

async def show_my_ideas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    entries = get_user_entries(user_id, limit=10)
    
    if not entries:
        await update.message.reply_text("אין לך עדיין רשומות. כתוב לי משהו קודם!")
        return
    
    message = "📚 10 הרשומות האחרונות שלך:\n\n"
    for i, entry in enumerate(entries, 1):
        content = entry['content']
        date_obj = entry['created_at'] # Already a datetime object
        date_str = date_obj.strftime('%d/%m %H:%M')
        
        short_content = content[:80] + "..." if len(content) > 80 else content
        message += f"*{i}. {short_content}*\n📅 {date_str}\n\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def delete_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    deleted_count = delete_user_entries(user_id)
    
    if deleted_count > 0:
        await update.message.reply_text(f"🗑️ נמחקו {deleted_count} רשומות מהמאגר שלך")
    else:
        await update.message.reply_text("אין לך רשומות למחיקה")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🧠 מכונת הרעיונות - מדריך שימוש

איך זה עובד?
1️⃣ כתוב לי כל דבר שעולה לך - רעיונות, מחשבות, פרויקטים
2️⃣ כשתרצה רעיון חדש, כתוב /get_idea
3️⃣ אני אנתח את מה שכתבת ואציע רעיונות שמתאימים לך

פקודות:
/get_idea - קבל רעיונות חדשים מבוססי ההיסטוריה שלך
/my_ideas - צפה ב-10 הרשומות האחרונות שלך
/clear_all - מחק את כל הנתונים שלך
/help - הצג הודעה זו

💡 טיפ: ככל שתכתוב לי יותר, הרעיונות יהיו יותר מדויקים ומותאמים אישית!
"""
    await update.message.reply_text(help_text)

# --- Flask Keep-Alive Server ---
flask_app = Flask(__name__)
@flask_app.route('/')
def health_check():
    return "I'm alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# --- Main Application Setup ---
def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("get_idea", get_idea_command))
    application.add_handler(CommandHandler("my_ideas", show_my_ideas_command))
    application.add_handler(CommandHandler("clear_all", delete_all_command))
    application.add_handler(CommandHandler("help", help_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    logger.info("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    main()
