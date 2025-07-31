import os
import sqlite3
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import openai
import asyncio

# הגדרת לוגים
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# הגדרת API keys
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
openai.api_key = OPENAI_API_KEY

class IdeasBot:
    def __init__(self):
        self.init_database()
    
    def init_database(self):
        """יצירת מסד נתונים SQLite"""
        conn = sqlite3.connect('ideas_bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    
    def save_entry(self, user_id: str, content: str):
        """שמירת רשומה חדשה"""
        conn = sqlite3.connect('ideas_bot.db')
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO entries (user_id, content) VALUES (?, ?)',
            (user_id, content)
        )
        conn.commit()
        conn.close()
    
    def get_user_entries(self, user_id: str, limit: int = 50):
        """שליפת כל הרשומות של משתמש"""
        conn = sqlite3.connect('ideas_bot.db')
        cursor = conn.cursor()
        cursor.execute(
            'SELECT content, created_at FROM entries WHERE user_id = ? ORDER BY created_at DESC LIMIT ?',
            (user_id, limit)
        )
        entries = cursor.fetchall()
        conn.close()
        return entries
    
    def delete_user_entries(self, user_id: str):
        """מחיקת כל הרשומות של משתמש"""
        conn = sqlite3.connect('ideas_bot.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM entries WHERE user_id = ?', (user_id,))
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        return deleted_count
    
    async def generate_ideas(self, user_entries: list) -> str:
        """יצירת רעיונות באמצעות OpenAI"""
        if not user_entries:
            return "אין לך עדיין רשומות במאגר. כתב לי כמה דברים קודם!"
        
        # הכנת הטקסט לשליחה ל-OpenAI
        entries_text = "\n".join([f"- {entry[0]}" for entry in user_entries[:20]])  # רק 20 האחרונות
        
        prompt = f"""
אתה מכונת רעיונות חכמה. קיבלת את הדברים הבאים שמשתמש כתב:

{entries_text}

על בסיס הדברים שהוא כתב, הצע לו 3 רעיונות חדשים ומעניינים שמתאימים לסגנון שלו ולתחומי העניין שלו.
הרעיונות צריכים להיות:
1. מעשיים ובני-ביצוע
2. בסגנון שלו
3. משהו שהוא עדיין לא עשה

כתב בעברית בצורה ידידותית וחמה.
"""

        try:
            response = await openai.ChatCompletion.acreate(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "אתה מכונת רעיונות חכמה שכותבת בעברית"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.8
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"שגיאה בקריאה ל-OpenAI: {e}")
            return "סליחה, יש לי בעיה טכנית עם יצירת הרעיונות. נסה שוב מאוחר יותר."

# יצירת מופע של הבוט
ideas_bot = IdeasBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /start"""
    welcome_message = """
🧠 שלום! אני מכונת הרעיונות שלך!

איך זה עובד?
📝 כתב לי כל דבר - רעיונות, מחשבות, פרויקטים
🎯 כשתכתב /איןלי - אני אציע לך רעיונות חדשים בהתבסס על מה שכתבת

פקודות זמינות:
/איןלי - קבל רעיונות חדשים
/הרעיונותשלי - צפה בהיסטוריה שלך
/מחקהכל - מחק את כל הנתונים שלך
/עזרה - הצג הודעה זו

בוא נתחיל! כתב לי משהו...
"""
    await update.message.reply_text(welcome_message)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בהודעות טקסט רגילות"""
    user_id = str(update.effective_user.id)
    content = update.message.text
    
    # שמירת ההודעה
    ideas_bot.save_entry(user_id, content)
    
    # מספר רשומות של המשתמש
    entries = ideas_bot.get_user_entries(user_id)
    count = len(entries)
    
    responses = [
        f"💾 נשמר! יש לך כבר {count} רשומות במאגר",
        f"✅ קלט! {count} רשומות במאגר שלך",
        f"📚 נוסף למאגר הרעיונות! ({count} רשומות בסך הכל)",
        f"🎯 רשמתי! {count} פריטים במכונת הרעיונות שלך"
    ]
    
    response = responses[count % len(responses)]
    await update.message.reply_text(response)

async def get_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /איןלי"""
    user_id = str(update.effective_user.id)
    
    await update.message.reply_text("🤔 חושב על רעיונות בשבילך...")
    
    # שליפת רשומות המשתמש
    entries = ideas_bot.get_user_entries(user_id)
    
    # יצירת רעיונות
    ideas = await ideas_bot.generate_ideas(entries)
    
    await update.message.reply_text(f"💡 הנה הרעיונות שלך:\n\n{ideas}")

async def show_my_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /הרעיונותשלי"""
    user_id = str(update.effective_user.id)
    entries = ideas_bot.get_user_entries(user_id, limit=10)
    
    if not entries:
        await update.message.reply_text("אין לך עדיין רשומות. כתב לי משהו קודם!")
        return
    
    message = "📚 הרשומות האחרונות שלך:\n\n"
    for i, (content, created_at) in enumerate(entries, 1):
        # המרת תאריך
        date_obj = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        date_str = date_obj.strftime('%d/%m %H:%M')
        
        # קיצור הטקסט אם הוא ארוך
        short_content = content[:80] + "..." if len(content) > 80 else content
        message += f"{i}. {short_content}\n📅 {date_str}\n\n"
    
    await update.message.reply_text(message)

async def delete_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /מחקהכל"""
    user_id = str(update.effective_user.id)
    deleted_count = ideas_bot.delete_user_entries(user_id)
    
    if deleted_count > 0:
        await update.message.reply_text(f"🗑️ נמחקו {deleted_count} רשומות מהמאגר שלך")
    else:
        await update.message.reply_text("אין לך רשומות למחיקה")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /עזרה"""
    help_text = """
🧠 מכונת הרעיונות - מדריך שימוש

איך זה עובד?
1️⃣ כתב לי כל דבר שעולה לך - רעיונות, מחשבות, פרויקטים
2️⃣ כשתרצה רעיון חדש, כתב /איןלי
3️⃣ אני אנתח את מה שכתבת ואציע רעיונות שמתאימים לך

פקודות:
/איןלי - קבל רעיונות חדשים מבוססי ההיסטוריה שלך
/הרעיונותשלי - צפה ב-10 הרשומות האחרונות שלך
/מחקהכל - מחק את כל הנתונים שלך
/עזרה - הצג הודעה זו

💡 טיפ: ככל שתכתב לי יותר, הרעיונות יהיו יותר מדויקים ומותאמים אישית!
"""
    await update.message.reply_text(help_text)

def main():
    """הפעלת הבוט"""
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN לא הוגדר!")
        return
    
    # יצירת האפליקציה
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # הוספת handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("איןלי", get_ideas))
    application.add_handler(CommandHandler("הרעיונותשלי", show_my_ideas))
    application.add_handler(CommandHandler("מחקהכל", delete_all))
    application.add_handler(CommandHandler("עזרה", help_command))
    application.add_handler(CommandHandler("help", help_command))
    
    # טיפול בהודעות טקסט (לא פקודות)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # הפעלה
    port = int(os.environ.get('PORT', 8080))
    logger.info(f"מתחיל בוט על פורט {port}")
    
    # לרנדר - webhook
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=f"https://{os.environ.get('RENDER_EXTERNAL_URL', 'your-app-name.onrender.com')}/{TELEGRAM_TOKEN}"
    )

if __name__ == '__main__':
    main()
