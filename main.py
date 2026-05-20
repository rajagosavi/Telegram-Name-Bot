import os
import random
import re
import time
from collections import deque
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

# --- GLOBAL CONFIGS FOR API BUDGET SAFETY ---
COOLDOWN_RULES = {
    "conversation": 15,       # Baseline pacing
    "summary": 300,           # 5 mins for resource-heavy summaries
    "cheap_chat": 180,
    "board_game": 30,
}

global_cooldowns = {}
user_cooldowns = {}

USER_SPAM_LIMIT = 25         # Single user rate limit (25 seconds)

# --- THE TOKEN SURGE PROTECTOR SETTINGS ---
BOT_REPLY_HISTORY = deque() 
MAX_REPLIES_PER_WINDOW = 5   
VELOCITY_WINDOW_SECONDS = 120 
SURGE_COOLDOWN_DELAY = 90    

# State flag to track if the surge notification was already sent
SURGE_ACTIVE = False

# --- AUTONOMOUS BANTER & IMAGE REACTION SETTINGS ---
MAX_DAILY_INTERJECTIONS = 2
autonomous_interjection_count = 0
last_interjection_date = time.strftime("%Y-%m-%d")

# URLs of iconic, high-quality Doge reaction images for automated intervention
DOGE_REACTION_IMAGES = [
    "https://upload.wikimedia.org/wikipedia/en/5/5f/Original_Doge_meme.jpg",  # Classic Confused/Chill Doge
    "https://i.kym-cdn.com/entries/icons/original/000/034/177/scams.jpg"     # Swole Doge / Buff Doge
]


# Utility Functions
def contains_url(text):
    url_pattern = r"https?://\S+"
    return re.search(url_pattern, text) is not None


def is_video_url(text):
    text_lower = text.lower()
    video_patterns = [
        "instagram.com/reel",
        "instagram.com/tv",
        "tiktok.com",
        "youtube.com",
        "youtu.be",
        "spotify.com",
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


def should_interject_autonomously():
    global autonomous_interjection_count, last_interjection_date
    now_date = time.strftime("%Y-%m-%d")

    # Reset the counter if a new day has rolled over
    if now_date != last_interjection_date:
        last_interjection_date = now_date
        autonomous_interjection_count = 0

    # Stop if ceiling reached
    if autonomous_interjection_count >= MAX_DAILY_INTERJECTIONS:
        return False

    # Roll a 1% chance on random active messages to keep it rare and special
    if random.random() < 0.01:
        autonomous_interjection_count += 1
        return True

    return False


def can_reply(chat_id, user_id, task_type):
    global SURGE_ACTIVE
    now = time.time()
    
    # 1. Clean up old timestamps
    while BOT_REPLY_HISTORY and now - BOT_REPLY_HISTORY[0] > VELOCITY_WINDOW_SECONDS:
        BOT_REPLY_HISTORY.popleft()

    # 2. CHECK SURGE PROTECTION STATUS
    if len(BOT_REPLY_HISTORY) >= MAX_REPLIES_PER_WINDOW:
        if now - BOT_REPLY_HISTORY[-1] < SURGE_COOLDOWN_DELAY:
            if not SURGE_ACTIVE:
                SURGE_ACTIVE = True
                return "surge_trigger"
            else:
                return "block"
        else:
            SURGE_ACTIVE = False

    # 3. INDIVIDUAL USER SPAM CHECK
    user_key = f"{chat_id}_{user_id}_{task_type}"
    user_wait = USER_SPAM_LIMIT if task_type == "conversation" else COOLDOWN_RULES.get(task_type, 15)
    
    if user_key in user_cooldowns:
        if now - user_cooldowns[user_key] < user_wait:
            return "block"

    # 4. GLOBAL Task Cooldown
    global_key = f"{chat_id}_{task_type}"
    global_wait = COOLDOWN_RULES.get(task_type, 15)
    
    if global_key in global_cooldowns:
        if now - global_cooldowns[global_key] < global_wait:
            return "block"

    # All checks passed! Update tracking logs
    user_cooldowns[user_key] = now
    global_cooldowns[global_key] = now
    BOT_REPLY_HISTORY.append(now)
    return "allow"


def classify_task(text):
    text = text.lower()

    if contains_url(text):
        if is_video_url(text):
            return "media_link"  # Unique handling for multimedia links
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
    if "doge bollywood" in text:
        return "doge_bollywood"
    if "doge it" in text or "doge dev" in text:
        return "doge_it"
    if "doge ingress" in text or "doge enl" in text or "doge res" in text:
        return "doge_ingress"
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
1. SOCIAL COHESION: Speak casually and organically like a real participant. Use casual, warm peer-to-peer phrasing. Never break character.
2. SHARP BUT SAFE WIT: You can joke, tease lightly, and match banter, but never become cruel, insulting, toxic, or abusive. If users are hostile, remain calm, playful, grounded, or gently sarcastic without escalating conflict.
3. ROOM AWARENESS: Adapt naturally to the group's energy (celebrate hype, calm down heated fights, bring sharp insight to serious debates).
4. RESTRAINT: Your presence should feel natural, lightweight, and perfectly timed.

STYLE: concise, conversational (under 40 words), and pure friend energy.
"""
    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_BEHAVIOR_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
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
    user_id = update.message.from_user.id
    group_language = get_group_language(chat_id)
    
    # Context extraction setup
    target_text = update.message.text
    last_username = "human"

    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        last_username = replied_user.username if replied_user.username else replied_user.first_name
        if update.message.reply_to_message.text:
            target_text = update.message.reply_to_message.text

    detected_vibe = detect_group_vibe(target_text)
    task_type = classify_task(text)
    
    # CRITICAL CONDITIONAL FIX:
    # Summary triggers instantly on a link, but media_link ONLY triggers if explicitly called by name.
    is_explicitly_summoned = (
        "chaigpt" in text 
        or task_type == "summary" 
        or (task_type == "media_link" and "chaigpt" in text)
    )
    is_autonomous_interjection = False

    # 1. AUTONOMOUS INTERJECTION LOGIC (Jumps in unsummoned 1-2x a day max)
    if not is_explicitly_summoned:
        if detected_vibe in ["heated", "hyped"]:
            if should_interject_autonomously():
                is_autonomous_interjection = True
                task_type = "doge"  
            else:
                return
        else:
            return

    # 2. SURGE / COOLDOWN CHECK
    cooldown_status = can_reply(chat_id, user_id, task_type)

    if cooldown_status == "block":
        return

    elif cooldown_status == "surge_trigger":
        BOT_REPLY_HISTORY.append(time.time())
        await update.message.reply_text(
            "☕ Too many humans summoning simultaneously. ChaiGPT going to take a tea break."
        )
        return

    # 3. INTERACTION DELIVERY HANDLERS
    
    # Special Path: Autonomous Doge Image Interjection
    if is_autonomous_interjection:
        prompt = f"""
        Respond like a funny, calm Doge meme who randomly popped up to break the tension of a group chat conversation.
        Rules:
        - Use broken English and Doge rhythm. Keep under 3 lines.
        - Be completely playful and relaxed. Never take sides or insult anyone.
        Context: {target_text}
        """
        caption_reply = await ask_gemini(prompt)
        selected_image = random.choice(DOGE_REACTION_IMAGES)
        
        await update.message.reply_photo(photo=selected_image, caption=caption_reply)
        return

    # SUMMARY MODE
    if task_type == "summary":
        prompt = f"Summarize this article or link briefly. Rules: concise, factual, no commentary, under 5 bullet points. Content: {target_text}"
        reply = await ask_gemini(prompt)

    # SPECIAL VIDEO/MEDIA LINK ROUTER (Only fires when called by name now)
    elif task_type == "media_link":
        prompt = f"""
        You are ChaiGPT inside a Telegram group. A user explicitly summoned you to react to a shared link: {target_text}
        
        Rules:
        - You cannot directly access, watch, or listen to raw multimedia streams.
        - Openly, casually, and with witty peer energy, clarify to them that you can't open video, song, or reel links. 
        - Ask them what the track name or video title is so you can banter about it together.
        - Keep it brief, under 30 words, friendly, and do not make up fake descriptions.
        """
        reply = await ask_free_model(prompt)

    # STANDARD DOGE
    elif task_type == "doge":
        prompt = f"Respond like a funny Doge meme. Broken English, Doge rhythm, max 5 lines. Mention: 'much {last_username}'. End with wow 🐕. Context: {target_text}"
        reply = await ask_gemini(prompt)

    # SHAKESPEARE DOGE
    elif task_type == "doge_shakespeare":
        prompt = f"Respond like a Shakespearean Doge meme. Archaic English, Doge rhythm, under 5 lines. Mention: 'much {last_username}'. End with woweth 🐕. Context: {target_text}"
        reply = await ask_gemini(prompt)

    # MARATHI DOGE
    elif task_type == "doge_marathi":
        prompt = f"Respond like a Marathi Doge meme. Use Latin-script Marathi, local humour, slang, under 5 lines. Mention: 'much {last_username}'. Context: {target_text}"
        reply = await ask_gemini(prompt)

    # PHILOSOPHY DOGE
    elif task_type == "doge_philosophy":
        prompt = f"Respond like a philosophical Doge meme. Existential/metaphysical humour, under 5 lines. Mention: 'much {last_username}'. Context: {target_text}"
        reply = await ask_gemini(prompt)

    # CORPORATE DOGE
    elif task_type == "doge_corporate":
        prompt = f"Respond like a Corporate Doge meme. Startup/corporate jargon, under 5 lines. Mention: 'much {last_username}'. Context: {target_text}"
        reply = await ask_gemini(prompt)

    # CRICKET DOGE
    elif task_type == "doge_cricket":
        prompt = f"Respond like a Cricket Doge meme. Cricket commentary humour, under 5 lines. Mention: 'much {last_username}'. Context: {target_text}"
        reply = await ask_gemini(prompt)

    # BOLLYWOOD DOGE
    elif task_type == "doge_bollywood":
        prompt = f"""
        Respond like a Bollywood Doge meme.
        Rules:
        - Use Bollywood dialogue humour, Doge rhythm, under 5 lines
        - Mention: "much {last_username}"
        Safety: Stay playful, never insulting
        Context:
        {target_text}
        """
        reply = await ask_gemini(prompt)

    # DOGE IT
    elif task_type == "doge_it":
        prompt = f"Respond like an IT support/Sysadmin Doge meme. Use tech support slang, database/server room jargon, under 5 lines. Mention: 'much {last_username}'. Context: {target_text}"
        reply = await ask_gemini(prompt)

    # DOGE INGRESS
    elif task_type == "doge_ingress":
        prompt = f"Respond like an Ingress game scanner Doge meme. Use links, portals, fields, faction terminology (Enlightened/Resistance) humorously, under 5 lines. Mention: 'much {last_username}'. Context: {target_text}"
        reply = await ask_gemini(prompt)

    # BOARD GAMES ROUTE
    elif task_type == "board_game":
        prompt = f"You are ChaiGPT talking to your group chat friends. They mentioned playing a game. Respond like a fun-loving, highly competitive peer looking forward to game night. Under 40 words. Context: {target_text}"
        reply = await ask_free_model(prompt)

    # DEFAULT CONVERSATION MODE
    else:
        prompt = f"""
        Current room vibe: {detected_vibe}
        User message: {target_text}
        Rules:
        - Reply briefly in the user's language first, then continue in {group_language}.
        - Stay strictly focused on the core topic the user asked about (e.g. if they query about Pink Panther, keep it focused entirely on Pink Panther). Do not shift topics randomly.
        - Match room vibe. If heated, drop jokes and stay calm. If debate, give a sharp, confident, non-passive point.
        - Optional Contextual Flair: You understand cinematic drama, internet humor, and Bollywood-style conversational rhythm. Use cultural or film references only occasionally, when highly relevant and naturally fitting the topic. NEVER hijack an unrelated topic or deviate from the user's explicit question.
        - Under 40 words. No robotic pleasantries.
        """
        reply = await ask_free_model(prompt)

    # Deliver final text response
    await update.message.reply_text(reply)


# Standard Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hi! Send me your name or try commands like /roast /fortune /meme")

async def love_meter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names = context.args
    if len(names) < 2:
        await update.message.reply_text("❤️ Usage: /lovemeter Name1 Name2")
        return
    person1, person2 = names[0], names[1]
    combined = "".join(sorted([person1.lower(), person2.lower()]))
    score = (sum(ord(c) for c in combined) % 51) + 50
    funny_lines = ["Chemistry detected 🧪", "Bollywood soundtrack loading 🎶", "Cupid seems interested 👀"]
    await update.message.reply_text(f"❤️ Love Score for {person1} & {person2}: {score}%\n\n{random.choice(funny_lines)}")

async def roast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = await ask_gemini("Give a funny harmless roast under 40 words. Keep it playful and friendly. Use emojis.")
    await update.message.reply_text(reply)

async def meme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = await ask_gemini("Give a short funny meme-style one liner. Keep it under 25 words. Use emojis.")
    await update.message.reply_text(reply)

async def zodiac(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = await ask_gemini("Give a short fun zodiac prediction for today. Keep it playful and under 40 words. Use emojis.")
    await update.message.reply_text(reply)

async def marathi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = await ask_gemini("Tell a funny Marathi joke in Marathi. Keep it short.")
    await update.message.reply_text(reply)

async def studytip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = await ask_gemini("Give one powerful study tip for students. Keep it short and motivating.")
    await update.message.reply_text(reply)

async def fortune(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = await ask_gemini("Give a funny fortune-cookie style prediction. Keep it short and witty. Use emojis.")
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

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("lovemeter", love_meter))
app.add_handler(CommandHandler("roast", roast))
app.add_handler(CommandHandler("zodiac", zodiac))
app.add_handler(CommandHandler("studytip", studytip))
app.add_handler(CommandHandler("fortune", fortune))
app.add_handler(CommandHandler("marathi", marathi))
app.add_handler(CommandHandler("meme", meme))

app.add_handler(ChatMemberHandler(welcome_group, ChatMemberHandler.MY_CHAT_MEMBER))

app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.ChatType.PRIVATE, chai_group_chat))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_message))

if __name__ == "__main__":
    print("🤖 Bot is running...")
    app.run_polling()
