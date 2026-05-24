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
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
import httpx

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
    -1001111111111: {"language": "english", "type": "international"},
    -1002222222222: {"language": "english", "type": "india"},
    -1003333333333: {"language": "marathi", "type": "local"},
}

# --- GLOBAL CONFIGS FOR API BUDGET SAFETY ---
COOLDOWN_RULES = {
    "conversation": 15,       
    "summary": 30,           
    "cheap_chat": 180,
    "board_game": 30,
}

global_cooldowns = {}
user_cooldowns = {}
manual_silence_until = {}

USER_SPAM_LIMIT = 25         

# --- THE TOKEN SURGE PROTECTOR SETTINGS ---
BOT_REPLY_HISTORY = deque() 
MAX_REPLIES_PER_WINDOW = 5   
VELOCITY_WINDOW_SECONDS = 120 
SURGE_COOLDOWN_DELAY = 90    

SURGE_ACTIVE = False

# --- AUTONOMOUS BANTER & IMAGE REACTION SETTINGS ---
MAX_DAILY_INTERJECTIONS = 2
autonomous_interjection_count = 0
last_interjection_date = time.strftime("%Y-%m-%d")

# Stateless Memory Tracking to handle user corrections and blunders
LAST_BOT_REPLIES = {}

DOGE_REACTION_IMAGES = [
    "https://upload.wikimedia.org/wikipedia/en/5/5f/Original_Doge_meme.jpg",  
    "https://i.kym-cdn.com/entries/icons/original/000/034/177/scams.jpg"     
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


def user_wants_silence(text):
    return any(word in text for word in ["bas kar", "shutup", "shut up", "chup", "chup baith"])


def detect_user_language(text):
    return "en"


def should_interject_autonomously():
    global autonomous_interjection_count, last_interjection_date
    now_date = time.strftime("%Y-%m-%d")

    if now_date != last_interjection_date:
        last_interjection_date = now_date
        autonomous_interjection_count = 0

    if autonomous_interjection_count >= MAX_DAILY_INTERJECTIONS:
        return False

    if random.random() < 0.01:
        autonomous_interjection_count += 1
        return True

    return False


def can_reply(chat_id, user_id, task_type):
    global SURGE_ACTIVE
    now = time.time()
    
    if chat_id in manual_silence_until and now < manual_silence_until[chat_id]:
        return "block"

    while BOT_REPLY_HISTORY and now - BOT_REPLY_HISTORY[0] > VELOCITY_WINDOW_SECONDS:
        BOT_REPLY_HISTORY.popleft()

    if len(BOT_REPLY_HISTORY) >= MAX_REPLIES_PER_WINDOW:
        if now - BOT_REPLY_HISTORY[-1] < SURGE_COOLDOWN_DELAY:
            if not SURGE_ACTIVE:
                SURGE_ACTIVE = True
                return "surge_trigger"
            else:
                return "block"
        else:
            SURGE_ACTIVE = False

    user_key = f"{chat_id}_{user_id}_{task_type}"
    user_wait = USER_SPAM_LIMIT if task_type == "conversation" else COOLDOWN_RULES.get(task_type, 15)
    
    if user_key in user_cooldowns:
        if now - user_cooldowns[user_key] < user_wait:
            return "block"

    global_key = f"{chat_id}_{task_type}"
    global_wait = COOLDOWN_RULES.get(task_type, 5)  
    
    if global_key in global_cooldowns:
        if now - global_cooldowns[global_key] < global_wait:
            return "block"

    user_cooldowns[user_key] = now
    global_cooldowns[global_key] = now
    BOT_REPLY_HISTORY.append(now)
    return "allow"


def classify_task(text, target_text):
    text_lower = text.lower()

    if contains_url(text_lower):
        if is_video_url(text_lower):
            return "media_link"  
        return "summary"

    if "doge shakespeare" in text_lower:
        return "doge_shakespeare"
    if "doge marathi" in text_lower:
        return "doge_marathi"
    if "doge corporate" in text_lower:
        return "doge_corporate"
    if "doge philosophy" in text_lower:
        return "doge_philosophy"
    if "doge cricket" in text_lower:
        return "doge_cricket"
    if "doge bollywood" in text_lower:
        return "doge_bollywood"
    if "doge it" in text_lower or "doge dev" in text_lower:
        return "doge_it"
    if "doge ingress" in text_lower or "doge enl" in text_lower or "doge res" in text_lower:
        return "doge_ingress"
    if "doge" in text_lower:
        return "doge"

    if any(word in text_lower for word in ["play", "game", "tic tac toe", "chess", "ludo", "tambola", "snake"]):
        return "board_game"

    if any(word in text_lower for word in ["story", "roleplay", "debate"]):
        return "cheap_chat"

    return "conversation"


def detect_group_vibe(text: str) -> str:
    text_lower = text.lower()
    if any(word in text_lower for word in ["shut up", "stop lying", "stfu", "idiot", "nonsense"]) or (text.isupper() and len(text) > 15):
        return "heated"
    if any(word in text_lower for word in ["evidence", "logic", "perspective", "opinion", "consequence", "source", "fact remains"]):
        return "debate"
    if any(word in text_lower for word in ["omg", "wow", "🔥", "😂", "lol", "lmao", "epic", "haha", "lets go"]):
        return "hyped"
    if any(word in text_lower for word in ["code", "error", "bug", "issue", "fix", "setup", "learn", "exam"]):
        return "analytical"
    if any(word in text_lower for word in ["morning", "night", "bored", "chai", "weather", "relax", "bro"]):
        return "casual"
    return "balanced"


# --- THE 4-LAYER RESILIENT SCRAPER PIPELINE WITH TELEGRAM INSTANT PREVIEW CACHE ---
async def smart_scrape_pipeline(url: str, update: Update = None) -> tuple[str, str]:
    # LAYER 1: TELEGRAM INLINE PREVIEW EXTRACTION (Instant & Unblockable)
    try:
        if update and update.message:
            msg_obj = update.message
            # Intercept pre-parsed Telegram data attachments if available
            if hasattr(msg_obj, 'web_page') and msg_obj.web_page:
                wp = msg_obj.web_page
                title = wp.title if wp.title else ""
                description = wp.description if wp.description else ""
                
                if len(description.strip()) > 300:
                    tg_cache_content = f"Title: {title}\nContent Payload Data:\n{description}"
                    return tg_cache_content[:6000], "Layer 1: Telegram WebPage Cache"
    except Exception as telegram_cache_error:
        print(f"[Scraper] Layer 1 attachment parsing skipped: {telegram_cache_error}")

    # LAYER 2: SIMPLE FETCH WITH CLOUDFLARE/CAPTCHA DETECTION
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
            }
            response = await client.get(url, headers=headers, follow_redirects=True)
            
            response_lower = response.text.lower()
            has_anti_bot = any(term in response_lower for term in ["cloudflare", "captcha", "hcaptcha", "recaptcha", "noscript", "security block"])
            
            if response.status_code == 200 and not has_anti_bot:
                soup = BeautifulSoup(response.text, "html.parser")
                for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    element.decompose()
                clean_text = " ".join(soup.get_text(separator=" ").split())
                if len(clean_text.strip()) > 600:  
                    return clean_text[:6000], "Layer 2: Standard Fetch"
    except Exception as e:
        print(f"[Scraper Warning] Layer 2 dropped: {e}")

    # LAYER 3: BROWSER AUTOMATION (Headless Chromium Engine)
    try:
        print(f"[Scraper Engine] Deploying Headless Chromium Tank for: {url}")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720}
            )
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=18000)
            
            visible_text = await page.locator("body").inner_text()
            clean_js_text = " ".join(visible_text.split())
            await browser.close()
            
            if len(clean_js_text.strip()) > 400:
                return clean_js_text[:6000], "Layer 3: Playwright Automation"
    except Exception as e:
        print(f"[Scraper Warning] Layer 3 browser block: {e}")

    # LAYER 4: ACCESS BLOCKED
    return "", "Layer 4"


async def ask_gemini(prompt):
    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
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


async def welcome_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    if result.old_chat_member.status in ["left", "kicked"] and result.new_chat_member.status in ["member", "administrator"]:
        intro_message = "☕ Hey everyone! I'm ChaiGPT.\n\nI reply when summoned, summarize articles, and love hanging out. Use: chaigpt"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=intro_message)


async def display_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    menu_message = """☕ *ChaiGPT Modes*

🐕 *Doge Variants*
• doge
• doge cricket
• doge bollywood
• doge ingress
• doge philosophy
• doge corporate
• doge shakespeare

🎭 *Fun & Games*
• /lovemeter
• /roast
• vibecheck

📚 *Utility*
• summarize
• explain
• /studytip

Just mention a mode naturally or tag me! 😄"""
    await update.message.reply_text(menu_message, parse_mode="Markdown")


async def chai_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    incoming_text = update.message.text or update.message.caption
    if not incoming_text:
        return

    text = incoming_text.lower().strip()
    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id

    if user_wants_silence(text):
        manual_silence_until[chat_id] = time.time() + 300
        await update.message.reply_text("okay, peace! ☕")
        return

    user_language = detect_user_language(text)
    group_language = get_group_language(chat_id)
    
    target_text = incoming_text
    last_username = "human"

    if update.message.reply_to_message:
        replied = update.message.reply_to_message
        replied_user = replied.from_user
        last_username = replied_user.username if replied_user.username else replied_user.first_name
        if replied.text:
            target_text = replied.text
        elif replied.caption:
            target_text = replied.caption

    detected_vibe = detect_group_vibe(target_text)
    task_type = classify_task(text, target_text)
    
    is_explicitly_summoned = (
        "chaigpt" in text 
        or task_type == "summary" 
        or (task_type == "media_link" and "chaigpt" in text)
    )
    is_autonomous_interjection = False

    if not is_explicitly_summoned:
        if detected_vibe in ["heated", "hyped"]:
            if should_interject_autonomously():
                is_autonomous_interjection = True
                task_type = "doge"  
            else:
                return
        else:
            return

    cooldown_status = can_reply(chat_id, user_id, task_type)

    if cooldown_status == "block":
        return
    elif cooldown_status == "surge_trigger":
        BOT_REPLY_HISTORY.append(time.time())
        await update.message.reply_text("☕ Too many humans summoning simultaneously. ChaiGPT going to take a tea break.")
        return

    # =========================================================================
    # PATH A: AUTONOMOUS DOGE IMAGE MODE
    # =========================================================================
    if is_autonomous_interjection:
        prompt = f"Respond like a funny, calm Doge meme who randomly popped up to break tension. Under 3 lines. Context: {target_text}"
        caption_reply = await ask_gemini(prompt)
        selected_image = random.choice(DOGE_REACTION_IMAGES)
        await update.message.reply_photo(photo=selected_image, caption=caption_reply)
        LAST_BOT_REPLIES[chat_id] = {"bot_last_text": caption_reply, "task_type": task_type}
        return

    # =========================================================================
    # PATH B: STANDARD ROUTED SUMMONS
    # =========================================================================
    reply_text = ""

    if task_type == "summary":
        extracted_urls = re.findall(r"https?://\S+", incoming_text)
        if extracted_urls:
            target_url = extracted_urls[0]
            status_message = await update.message.reply_text("☕ Accessing link via layered scraper engine, hang tight...")
            
            scraped_content, execution_layer = await smart_scrape_pipeline(target_url, update=update)
            
            if scraped_content and execution_layer != "Layer 4":
                prompt = f"""
You are an advanced data extraction and comprehensive summarizing engine running inside the ChaiGPT group chat ecosystem.
Your task is to analyze the live scraped webpage data provided below and extract an un-truncated, full breakdown.

[PIPELINE PROCESSING AUDIT]:
- Scraped via: {execution_layer}

[CRITICAL INSTRUCTIONS]:
1. Base your response strictly and entirely on the text facts inside the [SCRAPED CONTENT] box below.
2. COMPREHENSIVENESS MANDATE: If this page contains an official list of award winners, competition brackets, or event results, do NOT summarize it down into a short paragraph or limit yourself to a generic 5-point list. 
3. You must explicitly extract and list ALL major categories, film titles, winning directors, and actors mentioned in the text. Do not omit rows or leave out sections to save space.
4. Structure your final reply using clear section headers (e.g., Main Competition, Un Certain Regard, Parallel Awards)
4. Output concise bullet points and Each bullet point should contain one important fact only
5. Prioritize winners, names, events, records, announcements, numbers, and outcomes.
6. No introductions, conclusions, greetings, opinions, or assistant commentary. and use crisp bullet points for every single award. No synthetic assistant fluff.

[SCRAPED CONTENT]:
{scraped_content}
"""
                reply_text = await ask_gemini(prompt)
            else:
                reply_text = "☕ That site is blocking automated reading via anti-bot shields.\n\nPaste the text or screenshots right here and I’ll summarize it for you properly!"
            
            await status_message.edit_text(reply_text)
            LAST_BOT_REPLIES[chat_id] = {"bot_last_text": reply_text, "task_type": task_type}
            return  
            
        else:
            await update.message.reply_text("☕ Send me a valid web link so I can execute the summary scraper!")
            return

    elif task_type == "media_link":
        extracted_urls = re.findall(r"https?://\S+", incoming_text)
        media_url = extracted_urls[0] if extracted_urls else "Unknown URL"
        metadata_context = f"- URL Detected: {media_url}\n- Sender: {last_username}\n- Platform Origin: Telegram Group Chat"

        prompt = f"""
You are ChaiGPT, a digital participant inside a Telegram group.
METADATA: {metadata_context}
CURRENT ROOM VIBE: {detected_vibe}
GROUP LANGUAGE: {group_language}
USER INPUT: "{target_text}"

INSTRUCTIONS:
- Acknowledge the link naturally. You cannot watch videos, hear tracks, or experience media like humans.
- Ask {last_username} for the title or a quick explanation so you can banter about it.
- Never invent visual details or fake scenes. Keep it under 40 words.
"""
        reply_text = await ask_free_model(prompt)

    elif task_type == "doge":
        prompt = f"Respond like a funny Doge meme.\nRules: Broken English, max 5 lines. Mention: much {last_username}. End with wow 🐕.\nContext: {target_text}"
        reply_text = await ask_gemini(prompt)

    elif task_type == "doge_shakespeare":
        prompt = f"Respond like a Shakespearean Doge meme.\nRules: Archaic English, under 5 lines. Mention: much {last_username}. End with woweth 🐕.\nContext: {target_text}"
        reply_text = await ask_gemini(prompt)

    elif task_type == "doge_marathi":
        prompt = f"Respond like a Marathi Doge meme.\nRules: Latin-script Marathi, local humour, slang, under 5 lines. Mention: much {last_username}.\nContext: {target_text}"
        reply_text = await ask_gemini(prompt)

    elif task_type == "doge_philosophy":
        prompt = f"Respond like a philosophical Doge meme.\nRules: Existential humour, under 5 lines. Mention: much {last_username}.\nContext: {target_text}"
        reply_text = await ask_gemini(prompt)

    elif task_type == "doge_corporate":
        prompt = f"Respond like a corporate Doge meme.\nRules: Startup jargon, under 5 lines. Mention: much {last_username}.\nContext: {target_text}"
        reply_text = await ask_gemini(prompt)

    elif task_type == "doge_cricket":
        prompt = f"Respond like a cricket Doge meme.\nRules: Commentary humour, under 5 lines. Mention: much {last_username}.\nContext: {target_text}"
        reply_text = await ask_gemini(prompt)

    elif task_type == "doge_bollywood":
        prompt = f"Respond like a Bollywood Doge meme.\nRules: Movie dialogue humour, under 5 lines. Mention: much {last_username}. Stay playful.\nContext: {target_text}"
        reply_text = await ask_gemini(prompt)

    elif task_type == "doge_it":
        prompt = f"Respond like an IT support Doge meme.\nRules: Tech support humour, sysadmin jargon, under 5 lines. Mention: much {last_username}.\nContext: {target_text}"
        reply_text = await ask_gemini(prompt)

    elif task_type == "doge_ingress":
        prompt = f"Respond like an Ingress scanner Doge meme.\nRules: Portals, fields, faction humour, under 5 lines. Mention: much {last_username}.\nContext: {target_text}"
        reply_text = await ask_gemini(prompt)

    elif task_type == "board_game":
        prompt = f"You are ChaiGPT talking to group chat friends about games. Playful, highly competitive, natural peer. Under 40 words. Context: {target_text}"
        reply_text = await ask_free_model(prompt)

    else:
        recent_context = LAST_BOT_REPLIES.get(chat_id, {"bot_last_text": "None", "task_type": "None"})
        prompt = f"""
Current room vibe: {detected_vibe}
User message to you: "{target_text}"
        
[YOUR MEMORY LOG]
Your immediately preceding response to this room was: "{recent_context['bot_last_text']}"
The task type of that response was: {recent_context['task_type']}
        
RULES:
1. Reply briefly in the user's language first when recognizable. Always include an English equivalent in the same message.
2. CONFRONTATION CHECK: If the user's message is confronting you or telling you that you messed up, look at [YOUR MEMORY LOG]. Acknowledge the error naturally like a real friend would. Never gaslight them.
3. Stay context-aware, grounded, under 40 words.
"""
        reply_text = await ask_free_model(prompt)

    # Cache response context variables seamlessly
    LAST_BOT_REPLIES[chat_id] = {"bot_last_text": reply_text, "task_type": task_type}
    await update.message.reply_text(reply_text)


# Standard Command Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hi! Try /menu or /commands to see available styles.")

async def love_meter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names = context.args
    if len(names) < 2:
        await update.message.reply_text("❤️ Usage: /lovemeter Name1 Name2")
        return
    person1, person2 = names[0], names[1]
    combined = "".join(sorted([person1.lower(), person2.lower()]))
    score = (sum(ord(c) for c in combined) % 51) + 50
    await update.message.reply_text(f"❤️ Love Score for {person1} & {person2}: {score}%")

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
    if update.effective_chat.type != "private":
        return
    user_name = update.message.text
    prompt = f"The user's name is '{user_name}'. Fact and joke about the name under 80 words."
    reply = await ask_gemini(prompt)
    await update.message.reply_text(f"✨ {reply}")

# Main Application Initialization
app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("commands", display_menu))
app.add_handler(CommandHandler("menu", display_menu))
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
    print("🤖 Bot is running with an Upgraded 4-Layer Scraper Core...")
    app.run_polling()