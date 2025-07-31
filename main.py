import logging
import os
import random
import sys
import json
from functools import partial
from threading import Thread
from pathlib import Path

import openai
from dotenv import load_dotenv
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Environment Setup ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- Validations ---
if not TELEGRAM_TOKEN:
    print("Error: TELEGRAM_TOKEN environment variable not set.")
    sys.exit(1)
if not OPENAI_API_KEY:
    print("Error: OPENAI_API_KEY environment variable not set.")
    sys.exit(1)
openai.api_key = OPENAI_API_KEY

if ADMIN_ID:
    try:
        ADMIN_ID = int(ADMIN_ID)
    except ValueError:
        print("Error: ADMIN_ID must be a valid integer.")
        sys.exit(1)

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Database Setup (File-based JSON) ---
DATA_DIR = Path("/var/data/ideas_bot")
DATA_DIR.mkdir(parents=True, exist_ok=True)
USER_IDEAS_DB = DATA_DIR / "user_ideas.json"

def load_user_data():
    if not USER_IDEAS_DB.exists():
        return {}
    with open(USER_IDEAS_DB, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_user_data(data):
    with open(USER_IDEAS_DB, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# --- Flask Keep-Alive Server ---
flask_app = Flask(__name__)
@flask_app.route('/')
def health_check():
    return "I'm alive!", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# --- Bot Logic ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    welcome_message = (
        f"שלום {user.mention_html()}!\n\n"
        "אני בוט רעיונות מבוסס AI. אני יכול לייצר עבורך רעיונות מקוריים לפרויקטים.\n\n"
        "הנה הפקודות שאני מכיר:\n"
        "🔹 /get_idea - לקבלת רעיון חדש שנוצר על ידי GPT.\n"
        "🔹 /my_ideas - לצפייה בכל הרעיונות שקיבלת עד כה.\n"
        "🔹 /clear_my_ideas - למחיקת כל הרעיונות ששמרתי עבורך."
    )
    await update.message.reply_html(welcome_message)

async def get_idea(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates a new idea using OpenAI API and saves it."""
    user_id = str(update.effective_user.id)
    await update.message.reply_text("מייצר רעיון חדש בעזרת AI, אנא המתן...")

    try:
        # Construct the prompt for OpenAI
        prompt = (
            "אתה אסיסטנט יצירתי שתפקידך לתת רעיונות לפרויקטי תכנות לאנשים שלומדים פיתוח. "
            "הצע רעיון אחד, קצר וקולע (משפט אחד או שניים) לפרויקט תכנות. "
            "התמקד ברעיונות מקוריים ושימושיים שאפשר לממש כפרויקט צד. "
            "לדוגמה: 'בניית תוסף לדפדפן שמסכם סרטוני יוטיוב ארוכים' או 'פיתוח אפליקציה למעקב אחר צריכת מים יומית'. "
            "ענה בעברית ובמשפט אחד בלבד."
        )

        # Call OpenAI API
        response = await context.bot.loop.run_in_executor(
            None,
            lambda: openai.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "system", "content": "You are a creative assistant."},
                          {"role": "user", "content": prompt}],
                max_tokens=60,
                n=1,
                temperature=0.8,
            )
        )
        
        generated_idea = response.choices[0].message.content.strip()

        # Save the idea for the user
        user_data = load_user_data()
        if user_id not in user_data:
            user_data[user_id] = []
        user_data[user_id].append(generated_idea)
        save_user_data(user_data)
        
        message = f"הנה רעיון שנוצר במיוחד בשבילך:\n\n💡 *{generated_idea}*\n\nשמרתי לך אותו. כדי לראות את כל הרעיונות, שלח /my_ideas."
        await update.message.reply_text(message, parse_mode='MarkdownV2')

    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        await update.message.reply_text("מצטער, הייתה בעיה ביצירת הרעיון. אנא נסה שוב מאוחר יותר.")


async def my_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id not in user_data or not user_data[user_id]:
        await update.message.reply_text("עדיין לא שמרתי לך רעיונות. שלח /get_idea כדי לקבל את הרעיון הראשון שלך!")
        return

    user_ideas = user_data[user_id]
    message = "הנה כל הרעיונות ששמרתי לך עד כה:\n\n"
    for i, idea in enumerate(user_ideas, 1):
        message += f"🔹 {idea}\n"
    
    await update.message.reply_text(message)

async def clear_my_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    user_data = load_user_data()
    
    if user_id in user_data and user_data[user_id]:
        user_data[user_id] = []
        save_user_data(user_data)
        await update.message.reply_text("מחקתי בהצלחה את כל הרעיונות ששמרתי עבורך.")
    else:
        await update.message.reply_text("לא מצאתי רעיונות שמורים למחיקה.")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if ADMIN_ID and str(update.effective_user.id) != str(ADMIN_ID):
        await update.message.reply_text("מצטער, הפקודה הזו מיועדת למנהל המערכת בלבד.")
        return
    
    user_data = load_user_data()
    user_count = len(user_data)
    total_ideas = sum(len(ideas) for ideas in user_data.values())
    await update.message.reply_text(f"📊 סטטיסטיקות הבוט:\n\n👤 משתמשים עם רעיונות שמורים: {user_count}\n💡 סך כל הרעיונות השמורים: {total_ideas}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("get_idea", get_idea))
    application.add_handler(CommandHandler("my_ideas", my_ideas))
    application.add_handler(CommandHandler("clear_my_ideas", clear_my_ideas))
    application.add_handler(CommandHandler("stats", admin_stats))
    
    application.add_error_handler(error_handler)

    logger.info("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    main()
