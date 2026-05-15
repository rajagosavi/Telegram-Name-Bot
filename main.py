import os
from dotenv import load_dotenv
from google import genai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ChatMemberHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import random
import time

# Define group profiles with language and type
GROUP_PROFILES = {

    # International Group
    -1001111111111: {
        "language": "english",
        "type": "international"
    },

    # India-wide Group
    -1002222222222: {
        "language": "english",
        "type": "india"
    },

    # Marathi Local Group
    -1003333333333: {
        "language": "marathi",
        "type": "local"
    }
}

def get_group_language(chat_id):

    profile = GROUP_PROFILES.get(chat_id)

    if not profile:
        return "english"

    return profile["language"]

# Welcome message when bot is added to a group
async def welcome_group(update: Update, context: ContextTypes.DEFAULT_TYPE):

    result = update.my_chat_member

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status

    if old_status in ["left", "kicked"] and new_status in ["member", "administrator"]:

        intro_message = """
☕ Hey everyone! I'm ChaiGPT.

I:
• reply when summoned
• summarize articles
• understand multiple languages
• try not to interrupt humans 😄

Summon me using:
chaigpt
        """

        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=intro_message
        )

cooldowns = {}

COOLDOWN_RULES = {
    "conversation": 60,
    "summary": 300,
    "cheap_chat": 180,
    "meme": 90,
}

def can_reply(chat_id, task_type):

    now = time.time()

    key = f"{chat_id}_{task_type}"

    cooldown_seconds = COOLDOWN_RULES.get(task_type, 60)

    if key not in cooldowns:
        cooldowns[key] = 0

    if now - cooldowns[key] > cooldown_seconds:

        cooldowns[key] = now

        return True

    return False
    
# Load environment variables
load_dotenv()

# Get keys from .env
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

#print("TOKEN:", TELEGRAM_TOKEN)

client = genai.Client(api_key=GOOGLE_API_KEY)

#handle messages that mention the bot's name

def classify_task(text):

    text = text.lower()

    if "http" in text:
        return "summary"

    if any(word in text for word in [
        "play",
        "game",
        "story",
        "roleplay",
        "debate"
    ]):
        return "cheap_chat"

    return "conversation"

async def chai_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:
        return

    text = update.message.text.lower().strip()

    chat_id = update.effective_chat.id

    group_language = get_group_language(chat_id)

    task_type = classify_task(text)

    is_triggered = (
        "chaigpt" in text
        or task_type == "summary"
                )

    if not is_triggered:
        return


    if not can_reply(chat_id, task_type):
        return

    prompt = f"""
    You are ChaiGPT inside a Telegram group.

    User message:
    {text}

    Rules:
    - Understand any language
    - Reply briefly in user's input language first
    - Then continue in {group_language}
    - Keep concise
    - Under 40 words
    - Friendly and witty
    - Avoid cringe
    """

    if task_type == "summary":
        reply = await ask_gemini(prompt)

    elif task_type == "cheap_chat":
        reply = await ask_free_model(prompt)

    else:
        reply = await ask_free_model(prompt)

    await update.message.reply_text(reply)

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! Send me your name or try commands like /roast /fortune /meme"
    )

async def ask_gemini(prompt):

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return response.text


async def ask_free_model(prompt):

    return await ask_gemini(prompt)

async def love_meter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names = context.args

    if len(names) < 2:
        await update.message.reply_text(
            "❤️ Usage: /lovemeter Name1 Name2"
        )
        return

    person1 = names[0]
    person2 = names[1]

    combined = "".join(sorted([person1.lower(), person2.lower()]))

    score = (sum(ord(c) for c in combined) % 51) + 50

    funny_lines = (
        "Chemistry detected 🧪",
        "Bollywood soundtrack loading 🎶",
        "Cupid seems interested 👀",
        "This could become marriage or a playlist 💿",
        "Love is in the air... or is it just pollen? 🌸",
        "A match made in the cloud ☁️",
        "This could be the start of a beautiful friendship... or a rom-com 🎬",
    )
    result = random.choice(funny_lines)

    await update.message.reply_text(
        f"❤️ Love Score for {person1} & {person2}: {score}%\n\n{result}"
    )


async def roast(update: Update, context: ContextTypes.DEFAULT_TYPE):

    prompt = """
    Give a funny harmless roast under 40 words.
    Keep it playful and friendly.
    Use emojis.
    """

    reply = await ask_gemini(prompt)

    await update.message.reply_text(reply)

async def meme(update: Update, context: ContextTypes.DEFAULT_TYPE):

    prompt = """
    Give a short funny meme-style one liner.
    Keep it under 25 words.
    Use emojis.
    """

    reply = await ask_gemini(prompt)

    await update.message.reply_text(reply)

# Handle user messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    chat_type = update.effective_chat.type

    if chat_type != "private":
        return

    user_name = update.message.text

    prompt = f"""
    The user's name is '{user_name}'.

    1. Tell one short interesting or cultural fact about the name.
    2. Make a witty, playful pun or joke using the name.

    Rules:
    - Keep response under 80 words
    - Be fun and friendly
    - Use emojis
    """

    reply = await ask_gemini(prompt)

    await update.message.reply_text(
    f"✨ {reply}"
    )

async def zodiac(update: Update, context: ContextTypes.DEFAULT_TYPE):

    prompt = """
    Give a short fun zodiac prediction for today.
    Keep it playful and under 40 words.
    Use emojis.
    """

    reply = await ask_gemini(prompt)

    await update.message.reply_text(reply)
    
async def marathi(update: Update, context: ContextTypes.DEFAULT_TYPE):

    prompt = """
    Tell a funny Marathi joke in Marathi.
    Keep it short.
    """

    reply = await ask_gemini(prompt)

    await update.message.reply_text(reply)

async def studytip(update: Update, context: ContextTypes.DEFAULT_TYPE):

    prompt = """
    Give one powerful study tip for students.
    Keep it short and motivating.
    """

    reply = await ask_gemini(prompt)

    await update.message.reply_text(reply)

async def fortune(update: Update, context: ContextTypes.DEFAULT_TYPE):

    prompt = """
    Give a funny fortune-cookie style prediction.
    Keep it short and witty.
    Use emojis.
    """

    reply = await ask_gemini(prompt)

    await update.message.reply_text(reply)

# For URL detection in messages
import re


def contains_url(text):
    url_pattern = r"https?://\S+"
    return re.search(url_pattern, text) is not None

app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("lovemeter", love_meter))
app.add_handler(CommandHandler("roast", roast))
app.add_handler(CommandHandler("zodiac", zodiac))
app.add_handler(CommandHandler("studytip", studytip))
app.add_handler(CommandHandler("fortune", fortune))
app.add_handler(CommandHandler("marathi", marathi))
app.add_handler(CommandHandler("meme", meme))

app.add_handler(
    ChatMemberHandler(
        welcome_group,
        ChatMemberHandler.MY_CHAT_MEMBER
    )
)

app.add_handler(
    MessageHandler(
        filters.TEXT
        & ~filters.COMMAND
        & ~filters.ChatType.PRIVATE,
        chai_group_chat
    )
)

app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_message
    )
)


# Run bot
print("🤖 Bot is running...")
app.run_polling()
