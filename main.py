# main.py
import os
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# -----------------------------
# Config
# -----------------------------
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN topilmadi. .env faylida BOT_TOKEN=... ni yozing.")

DATA_DIR = Path("/data")
DB_FILE = str(DATA_DIR / "looptrecker.db") if DATA_DIR.exists() else str(
    Path(__file__).with_name("looptrecker.db")
)

# -----------------------------
# Logging
# -----------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -----------------------------
# Database helpers
# -----------------------------
def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            streak INTEGER NOT NULL DEFAULT 0,
            last_done TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            habit_name TEXT NOT NULL,
            done_date TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_completion
        ON completions (user_id, habit_name, done_date)
    """)
    conn.commit()
    conn.close()

def normalize_habit_name(name: str) -> str:
    return " ".join(name.strip().split()).lower()

def get_today_str():
    return datetime.now().strftime("%Y-%m-%d")

def get_yesterday_str():
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

def format_habit_name(name: str) -> str:
    return name.strip()

# -----------------------------
# Habit logic
# -----------------------------
def add_habit(user_id: int, habit_name: str) -> str:
    name = format_habit_name(habit_name)
    if not name:
        return "Odatiy nom yozing. Masalan: /add Yuraqda yurish"

    normalized = normalize_habit_name(name)
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM habits WHERE user_id = ? AND LOWER(name) = ?",
        (user_id, normalized),
    ).fetchone()

    if existing:
        conn.close()
        return f"'{name}' odati allaqachon mavjud."

    conn.execute(
        "INSERT INTO habits (user_id, name, streak, last_done) VALUES (?, ?, 0, NULL)",
        (user_id, name),
    )
    conn.commit()
    conn.close()
    return f"Yangi odat qo'shildi: {name}"

def remove_habit(user_id: int, habit_name: str) -> str:
    name = format_habit_name(habit_name)
    if not name:
        return "O'chirmoqchi bo'lgan odatingizni yozing."

    normalized = normalize_habit_name(name)
    conn = get_connection()
    deleted = conn.execute(
        "DELETE FROM habits WHERE user_id = ? AND LOWER(name) = ?",
        (user_id, normalized),
    )
    conn.commit()
    conn.close()

    if deleted.rowcount == 0:
        return f"'{name}' odati topilmadi."
    return f"'{name}' odati o'chirildi."

def list_habits(user_id: int) -> list:
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT name, streak, last_done
        FROM habits
        WHERE user_id = ?
        ORDER BY name ASC
        """,
        (user_id,),
    ).fetchall()
    conn.close()
    return rows

def mark_done(user_id: int, habit_name: str) -> str:
    name = format_habit_name(habit_name)
    if not name:
        return "Qaysi odatni bajarilgan deb belgilamoqchisiz? Masalan: /done Yuraqda yurish"

    normalized = normalize_habit_name(name)
    today = get_today_str()

    conn = get_connection()
    habit = conn.execute(
        "SELECT id, name, streak, last_done FROM habits WHERE user_id = ? AND LOWER(name) = ?",
        (user_id, normalized),
    ).fetchone()

    if not habit:
        conn.close()
        return f"'{name}' odati topilmadi. Avval /add bilan qo'shing."

    already_done = conn.execute(
        "SELECT 1 FROM completions WHERE user_id = ? AND LOWER(habit_name) = ? AND done_date = ?",
        (user_id, normalized, today),
    ).fetchone()

    if already_done:
        conn.close()
        return f"Bugun '{habit['name']}' allaqachon bajarilgan."

    conn.execute(
        "INSERT INTO completions (user_id, habit_name, done_date) VALUES (?, ?, ?)",
        (user_id, habit["name"], today),
    )

    last_done = habit["last_done"]
    if not last_done:
        new_streak = 1
    else:
        last_dt = datetime.strptime(last_done, "%Y-%m-%d")
        today_dt = datetime.strptime(today, "%Y-%m-%d")
        if (today_dt - last_dt).days == 1:
            new_streak = habit["streak"] + 1
        elif (today_dt - last_dt).days == 0:
            new_streak = habit["streak"]
        else:
            new_streak = 1

    conn.execute(
        "UPDATE habits SET streak = ?, last_done = ? WHERE id = ?",
        (new_streak, today, habit["id"]),
    )
    conn.commit()
    conn.close()

    return (
        f"Zo'r! '{habit['name']}' bajarildi.\n"
        f"Streak: {new_streak}"
    )

def get_stats(user_id: int) -> str:
    rows = list_habits(user_id)
    if not rows:
        return "Hali hech qanday odat qo'shmagansiz. /add bilan boshlang."

    total_habits = len(rows)
    active_streak = sum(r["streak"] for r in rows)
    today = get_today_str()

    conn = get_connection()
    today_done = conn.execute(
        """
        SELECT COUNT(DISTINCT LOWER(habit_name))
        FROM completions
        WHERE user_id = ? AND done_date = ?
        """,
        (user_id, today),
    ).fetchone()[0]
    conn.close()

    msg = []
    msg.append(f"Jami odatlar: {total_habits}")
    msg.append(f"Bugun bajarilgan: {today_done}")
    msg.append(f"Umumiy streak: {active_streak}")
    msg.append("")
    msg.append("Odatlaringiz:")
    for r in rows:
        msg.append(f"- {r['name']} | streak: {r['streak']} | oxirgi: {r['last_done'] or 'hech qachon'}")
    return "\n".join(msg)

# -----------------------------
# Telegram handlers
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user 
    schedule_reminder(context.application.job_queue, user.id)
    text = (
        "Salom! Men Looptrecker, habit tracker botman.\n\n"
        "Mavjud buyruqlar:\n"
        "/add <odat_nomi> - yangi odat qo'shish\n"
        "/done <odat_nomi> - bugun bajarildi deb belgilash\n"
        "/list - barcha odatlar\n"
        "/stats - statistikalar\n"
        "/remove <odat_nomi> - odatni o'chirish\n"
        "/help - yordam\n"
    )
    await update.message.reply_text(f"Salom, {user.first_name}! \n\n{text}")

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Iltimos, odat nomini kiriting. Masalan: /add Yuraqda yurish")
        return
    name = " ".join(context.args)
    msg = add_habit(update.effective_user.id, name)
    await update.message.reply_text(msg)

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Iltimos, odat nomini kiriting. Masalan: /done Yuraqda yurish")
        return
    name = " ".join(context.args)
    msg = mark_done(update.effective_user.id, name)
    await update.message.reply_text(msg)

async def list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = list_habits(update.effective_user.id)
    if not items:
        await update.message.reply_text("Hali odat qo'shmagansiz. /add bilan boshlang.")
        return

    lines = ["Sizning odatlar:"]
    for i, item in enumerate(items, start=1):
        lines.append(f"{i}. {item['name']} | streak: {item['streak']} | last: {item['last_done'] or '—'}")
    await update.message.reply_text("\n".join(lines))

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_stats(update.effective_user.id))

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("O'chirmoqchi bo'lgan odatingizni yozing. Masalan: /remove Yuraqda yurish")
        return
    name = " ".join(context.args)
    msg = remove_habit(update.effective_user.id, name)
    await update.message.reply_text(msg)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Buyruqlar:\n"
        "/add <odat_nomi>\n"
        "/done <odat_nomi>\n"
        "/list\n"
        "/stats\n"
        "/remove <odat_nomi>\n"
        "/help"
    )

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Noma'lum buyruq. /help buyrug'ini ishlating."
    )

def get_user_ids():
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT user_id FROM habits"
    ).fetchall()
    conn.close()
    return [row["user_id"] for row in rows]


def schedule_reminder(job_queue, user_id):
    job_name = f"daily_reminder_{user_id}"

    for job in job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()

    job_queue.run_daily(
        daily_reminder,
        time=datetime.strptime("21:00", "%H:%M").time(),
        user_id=user_id,
        name=job_name,
    )


async def post_init(application):
    for user_id in get_user_ids():
        schedule_reminder(application.job_queue, user_id)


async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    user_id = context.job.user_id
    habits = list_habits(user_id)

    if not habits:
        return

    names = ", ".join(h["name"] for h in habits)

    await context.bot.send_message(
        chat_id=user_id,
        text=(
            f"Salom! Bugun qaysi odatlarni bajardingiz?\n"
            f"Odatlaringiz: {names}\n\n"
            f"Yodda tuting: /done <odat_nomi>"
        )
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Botda xatolik yuz berdi: %s", context.error)

    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(
            "Kechirasiz, botda xatolik yuz berdi. Iltimos, keyinroq urinib ko'ring."
        )
# -----------------------------
# Main
def main():
    init_db()

    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("add", add_command))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("list", list_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("remove", remove_command))
    app.add_handler(CommandHandler("help", help_command))

    app.add_handler(MessageHandler(
        filters.COMMAND & ~filters.Regex(
            r"^/(start|add|done|list|stats|remove|help)$"
        ),
        unknown_command
    ))

    app.add_error_handler(error_handler)

    logger.info("Looptrecker bot ishga tushdi.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
