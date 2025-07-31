import logging
import os
import random
import sys
from functools import partial
from threading import Thread

from dotenv import load_dotenv
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Environment Setup ---
# Load environment variables from .env file, if it exists
load_dotenv()

# Get environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

# Check for mandatory environment variables
if not TELEGRAM_TOKEN:
    print("Error: TELEGRAM_TOKEN environment variable not set.")
    sys.exit(1)
if not ADMIN_ID:
    print("Warning: ADMIN_ID environment variable not set. Admin commands will not be secured.")
else:
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

# --- Flask Keep-Alive Server ---
# This is a simple web server to keep the Render service alive on the free tier.
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    """A simple endpoint to confirm the web server is running."""
    return "I'm alive!", 200

def run_flask():
    """Runs the Flask web server."""
    # The port is dynamically assigned by Render.
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# --- Bot Logic ---
ideas = [
    "פיתוח אפליקציה לניהול מתכונים משפחתיים.",
    "יצירת בוט טלגרם שמסכם מאמרים ארוכים.",
    "בניית אתר אינטרנט לקהילת חובבי גינון אורבני.",
    "פיתוח משחק מובייל פשוט מבוסס פאזלים.",
    "יצירת פלטפורמה להחלפת ספרים משומשים.",
    "כתיבת סקריפט לאוטומציה של משימות חוזרות במחשב.",
    "פיתוח מערכת לניהול תקציב אישי עם התראות חכמות.",
    "בניית אתר פורטפוליו אישי להצגת פרויקטים.",
    "יצירת תוסף לדפדפן שמסיר פרסומות מסיחות דעת.",
    "פיתוח אפליקציית מדיטציה עם קולות טבע מרגיעים.",
    "בניית לוח מודעות וירטואלי לשכונה.",
    "יצירת בוט שמנטר מחירים של מוצרים באינטרנט.",
    "פיתוח פלטפורמה ללימוד שפה חדשה באמצעות שיחות וידאו.",
    "בניית מערכת המלצות לסרטים וסדרות מבוססת AI.",
    "יצירת אפליקציה למעקב אחר אימוני כושר אישיים.",
    "פיתוח כלי לניהול משימות ופרויקטים בקבוצות קטנות.",
    "בניית אתר להזמנת אוכל ממסעדות מקומיות קטנות.",
    "יצירת מחולל סיפורים קצרים רנדומלי.",
    "פיתוח אפליקציה לזיהוי צמחים ופרחים באמצעות המצלמה.",
    "בניית פלטפורמה לחיבור בין מתנדבים לעמותות.",
    "יצירת בוט שמספק ציטוטים מעוררי השראה כל בוקר.",
    "פיתוח מערכת לניהול מלאי לעסקים קטנים.",
    "בניית אתר המרכז אירועים ופעילויות לילדים באזור מסוים.",
    "יצירת אפליקציה ללימוד נגינה על כלי בסיסי כמו יוקלילי.",
    "פיתוח פלטפורמה למציאת שותפים לטיולים ופעילויות ספורט.",
    "בניית בוט שמלמד עובדות מעניינות כל יום.",
    "יצירת כלי אונליין להמרת קבצים בין פורמטים שונים.",
    "פיתוח אפליקציה למעקב אחר צריכת מים יומית.",
    "בניית אתר המאפשר למשתמשים ליצור ולשתף רשימות השמעה.",
    "יצירת בוט שמזכיר למשתמשים לקחת הפסקות קצרות מהעבודה.",
    "פיתוח מערכת להזמנת תורים אונליין לעסקים קטנים (ספרים, קוסמטיקאיות).",
    "בניית פלטפורמה לחיבור בין מורים פרטיים לתלמידים.",
    "יצירת אפליקציה שמציעה מסלולי טיול רגליים בטבע.",
    "פיתוח בוט שמספק עדכוני חדשות מסוננים לפי תחומי עניין.",
    "בניית אתר להשוואת מחירים בין סופרמרקטים.",
    "יצירת כלי ליצירת קורות חיים מקצועיים אונליין.",
    "פיתוח אפליקציית יומן אישי דיגיטלי עם אפשרויות אבטחה.",
    "בניית פלטפורמה לשיתוף כישרונות בין חברים (למשל, שיעור בישול תמורת תיקון מחשב).",
    "יצירת בוט שמסייע בתרגול אוצר מילים לשפה זרה.",
    "פיתוח אתר המרכז מידע על אימוץ חיות מחמד.",
    "בניית אפליקציה פשוטה לרישום הוצאות והכנסות.",
    "יצירת בוט שמספר בדיחות.",
    "פיתוח פלטפורמה לניהול ועדי בית.",
    "בניית אתר שמציג מתכונים לפי מרכיבים שיש בבית.",
    "יצירת כלי אונליין ליצירת סקרים ושאלונים מהירים.",
    "פיתוח אפליקציה לניהול רשימת קניות משותפת.",
    "בניית בוט שמספק מידע על תחבורה ציבורית בזמן אמת.",
    "יצירת פלטפורמה ללימוד קורסים קצרים אונליין (בסגנון Skillshare).",
    "פיתוח אתר המאפשר למצוא שותפים לדירה.",
    "יצירת בוט שמזכיר על ימי הולדת ואירועים חשובים."
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the /start command is issued."""
    user = update.effective_user
    welcome_message = (
        f"שלום {user.mention_html()}!\n\n"
        "אני בוט הרעיונות שלך.\n"
        "אין לך רעיון מה לפתח? פשוט תגיד לי!\n"
        "שלח לי /get_idea ואתן לך רעיון אקראי לפרויקט הבא שלך."
    )
    await update.message.reply_html(welcome_message)

async def get_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a random idea from the list."""
    # Choose a random idea
    random_idea = random.choice(ideas)
    
    # Prepare the message
    message = f"הנה רעיון בשבילך:\n\n💡 *{random_idea}*"
    
    # Send the message with MarkdownV2 formatting
    await update.message.reply_text(message, parse_mode='MarkdownV2')

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to show bot statistics. (Placeholder)"""
    # Security check: only the admin can use this command
    if str(update.effective_user.id) != str(ADMIN_ID):
        await update.message.reply_text("מצטער, הפקודה הזו מיועדת למנהל המערכת בלבד.")
        return

    # In a real bot, you would fetch this from a database.
    # For now, it's just a placeholder.
    user_count = "לא מחובר למסד נתונים" 
    await update.message.reply_text(f"סטטיסטיקות הבוט:\nמשתמשים רשומים: {user_count}")

# --- Helper function for error handling ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and send a telegram message to notify the developer."""
    logger.error("Exception while handling an update:", exc_info=context.error)
    # Optionally, notify the admin about the error
    # This part is commented out to avoid spamming, but can be enabled for production.
    # if ADMIN_ID:
    #     error_message = f"An error occurred: {context.error}"
    #     await context.bot.send_message(chat_id=ADMIN_ID, text=error_message)

# --- Main Application Setup ---
def main() -> None:
    """Start the bot."""
    # Create the Application and pass it your bot's token.
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # --- Register command handlers ---
    # on different commands - answer in Telegram
    application.add_handler(CommandHandler("start", start))
    
    # This is the corrected command
    application.add_handler(CommandHandler("get_idea", get_ideas))
    
    application.add_handler(CommandHandler("stats", admin_stats))
    
    # --- Register error handler ---
    application.add_error_handler(error_handler)

    # --- Start the Bot ---
    # Run the bot until the user presses Ctrl-C
    logger.info("Starting bot polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # Start the Flask server in a separate thread
    # This is the "keep-alive" trick for Render's free tier
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Start the bot's main function
    main()
