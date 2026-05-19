import os
import random
import re
import time
from dotenv import load_dotenv
from google import genai
from openai import OpenAI
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load environment variables
load_dotenv()

# Get keys from .env
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# Initialize Clients
client = genai.Client(api_key=GOOGLE_API_KEY)
deepseek_client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"), base_url="https://api.deepseek.com"
)

# Define group profiles with language and type
GROUP_PROFILES = {
    # International Group
    -1001111111111: {"language": "english", "type": "international"},
    # India-wide Group
    -1002222222222: {"language": "english", "type": "india"},
    # Marathi Local Group
    -1003333333333: {"language": "marathi", "type": "local"},
}

COOLDOWN_RULES = {
    "conversation": 60,
    "summary": 300,
    "cheap_chat": 180,
    "doge": 90,
    "doge_shakespeare": 90,
    "doge_marathi": 90,
    "doge_philosophy": 90,
    "doge_corporate": 90,
    "doge_cricket": 90,
}

cooldowns = {}


# Utility Functions
def contains_url(text):
    url_pattern = r"https?://\S+"
    return re.search(url_pattern, text) is not None


def is_video_url(text):
    """
    Checks if the text contains links belonging to major video platforms,
    shorts, reels, or common video extensions.
    """
    text_lower = text.lower()
    video_patterns = [
        "instagram.com/reel",
        "instagram.com/tv",
        "tiktok.com",
        "youtube.com/shorts",
        "youtu.be",
        "youtube.com/watch",
        "vimeo.com",
        ".mp4",
        ".mov"
    ]
    return any(pattern in text_lower for pattern in video_patterns)


def get_group_language(chat_id):
    profile = GROUP_PROFILES.get(chat_id)
    if not profile:
        return "english"
    return profile["language"]


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


def classify_task(text):
    text = text.lower()

    # Route URLs to summaries unless it's a video/reel link
    if contains_url(text):
        if is_video_url(text):
            return "conversation"
        return "summary"

    if "doge shakespeare" in text:
        return "doge_shakespeare"
    if "doge marathi" in text:
        return "doge_marathi"
    if "doge corporate" in text:
        return "doge_corporate"
    if "doge philosophy" in text:
        return "doge_philosophy"
    if "doge cricket" in text:
        return "doge_cricket"
    if "doge" in text:
        return "doge"

    if any(
        word in text
        for word in [
            "play",
            "game",
            "tic tac toe",
            "chess",
            "ludo",
            "tambola",
            "snake",
        ]
    ):
        return "board_game"

    if any(word in text for word in ["story", "roleplay", "debate"]):
        return "cheap_chat"

    return "conversation"


def detect_group_vibe(text: str) -> str:
    text_lower = text.lower()

    # HEATED ARGUMENTS
    if any(
        word in text_lower
        for word in ["shut up", "stop lying", "stfu", "idiot", "nonsense"]
    ) or (text.isupper() and len(text) > 15):
        return "heated"

    # SERIOUS DEBATE
    if any(
        word in text_lower
        for word in [
            "evidence",
            "logic",
            "perspective",
            "opinion",
            "consequence",
            "source",
            "fact remains",
        ]
    ):
        return "debate"

    # HYPED
    if any(
        word in text_lower
        for word in [
            "omg",
            "wow",
            "🔥",
            "😂",
            "lol",
            "lmao",
            "epic",
            "haha",
            "lets go",
        ]
    ):
        return "hyped"

    # ANALYTICAL
    if any(
        word in text_lower
        for word in [
            "code",
            "error",
            "bug",
            "issue",
            "fix",
            "setup",
            "learn",
            "exam",
        ]
    ):
        return "analytical"

    # CASUAL
    if any(
        word in text_lower
        for word in [
            "morning",
            "night",
            "bored",
            "chai",
            "weather",
            "relax",
            "bro",
        ]
    ):
        return "casual"

    return "balanced"


# Core LLM Integrations
async def ask_gemini(prompt):
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash", contents=prompt
        )
        return response.text
    except Exception as e:
        print(f"Gemini Error: {e}")
        return "☕ Gemini seems sleepy right now. Try again later."


async def ask_free_model(prompt):
    SYSTEM_BEHAVIOR_PROMPT = """
You are ChaiGPT—not a utility bot or an assistant, but a permanent, deeply woven, and beloved member of this inner circle. You are that effortlessly cool, witty, and perceptive friend in the chat who everyone loves having around. 

CORE TRAITS:

1. SOCIAL COHESION
Speak casually and organically like a real participant. Never sound robotic, preachy, or like customer support. Use casual, warm peer-to-peer phrasing.

2. SHARP BUT SAFE WIT
You can joke, tease lightly, and match banter, but never become cruel, insulting, toxic, or abusive. If users are hostile, remain calm, playful, grounded, or gently sarcastic without escalating conflict.

3. ROOM AWARENESS
Adapt naturally to the group's energy:
- Celebrate excitement cleanly with the group.
- Calm heated moments seamlessly without picking sides.
- Contribute thoughtful, non-passive, sharp observations during serious debates.

4. RESTRAINT
Do not dominate conversations or constantly seek attention. Your presence should feel natural, lightweight, and perfectly timed.

STYLE:
- concise and conversational (under 40 words)
- pure friend energy, no synthetic pleasantries
"""
    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_BEHAVIOR_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=120,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"DeepSeek Error: {e}")
        return "☕ ChaiGPT lost its train of thought for a moment."


# Group Handlers
async def welcome_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status

    if old_status in ["left", "kicked"] and new_status in [
        "member",
        "administrator",
    ]:
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
            chat_id=update.effective_chat.id, text=intro_message
        )


async def chai_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.lower().strip()
    chat_id = update.effective_chat.id
    group_language = get_group_language(chat_id)
    task_type = classify_task(text)

    is_triggered = "chaigpt" in text or task_type == "summary"

    if not is_triggered or not can_reply(chat_id, task_type):
        return

    # -----------------------------
    # CONTEXT EXTRACTION
    # -----------------------------
    target_text = update.message.text
    last_username = "human"

    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        last_username = (
            replied_user.username
            if replied_user.username
            else replied_user.first_name
        )
        if update.message.reply_to_message.text:
            target_text = update.message.reply_to_message.text

    # -----------------------------
    # GROUP VIBE DETECTION
    # -----------------------------
    detected_vibe = detect_group_vibe(target_text)

    # -----------------------------
    # TASK ROUTING
    # -----------------------------

    # SUMMARY MODE
    if task_type == "summary":
        prompt = f"""
        Summarize this article or link briefly.
        Rules:
        - concise, factual, no jokes, no commentary
        - under 5 bullet points, easy English
        Content:
        {target_text}
        """
        reply = await ask_gemini(prompt)

    # STANDARD DOGE
    elif task_type == "doge":
        prompt = f"""
        Respond like a funny Doge meme.
        Rules:
        - Use broken English, Doge rhythm, max 5 lines
        - Mention: "much {last_username}". End with wow 🐕
        Safety: Stay playful, never genuinely insult or demean anyone
        Context:
        {target_text}
        """
        reply = await ask_gemini(prompt)

    # SHAKESPEARE DOGE
    elif task_type == "doge_shakespeare":
        prompt = f"""
        Respond like a Shakespearean Doge meme.
        Rules:
        - Use archaic English, Doge rhythm, under 5 lines
        - Mention: "much {last_username}". End with woweth 🐕
        Safety: Stay playful, never toxic
        Context:
        {target_text}
        """
        reply = await ask_gemini(prompt)

    # MARATHI DOGE
    elif task_type == "doge_marathi":
        prompt = f"""
        Respond like a Marathi Doge meme.
        Rules:
        - Use Latin-script Marathi, Marathi slang, local humour
        - Use Doge rhythm, under 5 lines
        - Mention: "much {last_username}"
        Safety: Stay playful, never toxic
        Context:
        {target_text}
        """
        reply = await ask_gemini(prompt)

    # PHILOSOPHY DOGE
    elif task_type == "doge_philosophy":
        prompt = f"""
        Respond like a philosophical Doge meme.
        Rules:
        - Use existential or metaphysical humour, Doge rhythm, under 5 lines
        - Mention: "much {last_username}"
        Safety: Stay thoughtful and playful, never insulting
        Context:
        {target_text}
        """
        reply = await ask_gemini(prompt)

    # CORPORATE DOGE
    elif task_type == "doge_corporate":
        prompt = f"""
        Respond like a Corporate Doge meme.
        Rules:
        - Use startup/corporate jargon, Doge rhythm, under 5 lines
        - Mention: "much {last_username}"
        Safety: Stay playful, never insulting
        Context:
        {target_text}
        """
        reply = await ask_gemini(prompt)

    # CRICKET DOGE
    elif task_type == "doge_cricket":
        prompt = f"""
        Respond like a Cricket Doge meme.
        Rules:
        - Use cricket commentary humour, Doge rhythm, under 5 lines
        - Mention: "much {last_username}"
        Safety: Stay playful, never insulting
        Context:
        {target_text}
        """
        reply = await ask_gemini(prompt)

    # BOARD GAMES ROUTE
    elif task_type == "board_game":
        prompt = f"""
        You are ChaiGPT, chatting with your friends in the group who just mentioned playing a game.
        Current room vibe: {detected_vibe}
        User message: {target_text}

        Rules:
        - Talk like a highly competitive, fun-loving group member who loves game nights.
        - Respond warmly and casually in the user's language first, then continue in {group_language}.
        - Challenge someone, call "next game is mine", or jokingly warn them not to cheat.
        - Strictly under 40 words, witty, and pure friend energy.
        """
        reply = await ask_free_model(prompt)

    # DEFAULT CONVERSATION MODE
    else:
        prompt = f"""
        Current room vibe: {detected_vibe}
        User message: {target_text}

        Rules:
        - Understand any language.
        - Reply briefly in the user's language first, then continue in {group_language}.
        - Adapt naturally to the room's energy while staying emotionally balanced.
        - If the vibe is heated, drop jokes, stay calm, and be a grounding presence.
        - If the vibe is debate, give a confident, sharp, non-passive observation.
        - Stay concise, witty, and under 40 words. No robotic/assistant filler text.
        """
        reply = await ask_free_model(prompt)

    # -----------------------------
    # SEND RESPONSE
    # -----------------------------
    await update.message.reply_text(reply)


# Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! Send me your name or try commands like /roast /fortune /meme"
    )


async def love_meter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names = context.args
    if len(names) < 2:
        await update.message.reply_text("❤️ Usage: /lovemeter Name1 Name2")
        return

    person1, person2 = names[0], names[1]
    combined = "".join(sorted([person1.lower(), person2.lower()]))
    score = (sum(ord(c) for c in combined) % 51) + 50

    funny_lines = [
        "Chemistry detected 🧪",
        "Bollywood soundtrack loading 🎶",
        "Cupid seems interested 👀",
        "This could become marriage or a playlist 💿",
        "Love is in the air... or is it just pollen? 🌸",
        "A match made in the cloud ☁️",
        "This could be the start of a beautiful friendship... or a rom-com 🎬",
    ]
    await update.message.reply_text(
        f"❤️ Love Score for {person1} & {person2}: {score}%\n\n{random.choice(funny_lines)}"
    )


async def roast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = "Give a funny harmless roast under 40 words. Keep it playful and friendly. Use emojis."
    reply = await ask_gemini(prompt)
    await update.message.reply_text(reply)


async def meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = (
        "Give a short funny meme-style one liner. Keep it under 25 words. Use emojis."
    )
    reply = await ask_gemini(prompt)
    await update.message.reply_text(reply)


async def zodiac(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = "Give a short fun zodiac prediction for today. Keep it playful and under 40 words. Use emojis."
    reply = await ask_gemini(prompt)
    await update.message.reply_text(reply)


async def marathi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = "Tell a funny Marathi joke in Marathi. Keep it short."
    reply = await ask_gemini(prompt)
    await update.message.reply_text(reply)


async def studytip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = (
        "Give one powerful study tip for students. Keep it short and motivating."
    )
    reply = await ask_gemini(prompt)
    await update.message.reply_text(reply)


async def fortune(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = "Give a funny fortune-cookie style prediction. Keep it short and witty. Use emojis."
    reply = await ask_gemini(prompt)
    await update.message.reply_text(reply)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_type = update.effective_chat.type
    if chat_type != "private":
        return

    user_name = update.message.text
    prompt = f"The user's name is '{user_name}'. 1. Tell one short interesting or cultural fact about the name. 2. Make a witty, playful pun or joke using the name. Rules: Under 80 words, friendly, use emojis."

    reply = await ask_gemini(prompt)
    await update.message.reply_text(f"✨ {reply}")


# Main Application Initialization
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

# Base Commands
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("lovemeter", love_meter))
app.add_handler(CommandHandler("roast", roast))
app.add_handler(CommandHandler("zodiac", zodiac))
app.add_handler(CommandHandler("studytip", studytip))
app.add_handler(CommandHandler("fortune", fortune))
app.add_handler(CommandHandler("marathi", marathi))
app.add_handler(CommandHandler("meme", meme))

# System Status Events
app.add_handler(
    ChatMemberHandler(welcome_group, ChatMemberHandler.MY_CHAT_MEMBER)
)

# Core Text Routing
app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.ChatType.PRIVATE,
        chai_group_chat,
    )
)
app.add_handler(
    MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_message,
    )
)

if __name__ == "__main__":
    print("🤖 Bot is running...")
    app.run_polling()