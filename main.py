import os
from dotenv import load_dotenv
from google import genai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import random

# Load environment variables
load_dotenv()

# Get keys from .env
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

client = genai.Client(api_key=GOOGLE_API_KEY)

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
    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
)
   

# Run bot
print("🤖 Bot is running...")
app.run_polling()
