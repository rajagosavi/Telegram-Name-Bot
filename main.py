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
manual_silence_until = {}

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

# USER LANGUAGE DETECTION
def detect_user_language(text: str) -> str:
    text_lower = text.lower()

    hindi_markers = [
        "bhai",
        "kya",
        "hai",
        "nahi",
        "kaise",
        "acha",
        "toh",
        "haan",
    ]

    matches = sum(
        word in text_lower
        for word in hindi_markers
    )

    if matches >= 2:
        return "hinglish"

    return "english"


# Utility Functions
def contains_url(text):
    url_pattern = r"https?://\S+"
    return re.search(url_pattern, text) is not None

QUIET_COMMANDS = [
    "shut up",
    "go away",
    "zip it",
    "keep quiet",
    "don't talk",
    "stop talking",
    "bas kar",
    "chup",
]

def user_wants_silence(text: str) -> bool:
    text_lower = text.lower()

    return any(
        phrase in text_lower
        for phrase in QUIET_COMMANDS
    )

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
    
    # MANUAL SILENCE MODE
    if chat_id in manual_silence_until:

        if now < manual_silence_until[chat_id]:
            return "block"

        else:
            del manual_silence_until[chat_id]

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


def classify_task(text, reply_text=""):

    combined = f"{text} {reply_text}".lower()

    if "doge shakespeare" in combined:
        return "doge_shakespeare"

    if "doge marathi" in combined:
        return "doge_marathi"

    if "doge corporate" in combined:
        return "doge_corporate"

    if "doge philosophy" in combined:
        return "doge_philosophy"

    if "doge cricket" in combined:
        return "doge_cricket"

    if "doge bollywood" in combined:
        return "doge_bollywood"

    if "doge it" in combined or "doge dev" in combined:
        return "doge_it"

    if "doge ingress" in combined or "doge enl" in combined or "doge res" in combined:
        return "doge_ingress"

    if "doge" in combined:
        return "doge"

    if any(
        word in combined
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

    if any(
        word in combined
        for word in ["story", "roleplay", "debate"]
    ):
        return "cheap_chat"

    opinion_keywords = [
        "opinion",
        "what do you think",
        "thoughts",
        "review",
        "rate",
        "worth it",
        "how is this",
    ]

    asking_opinion = any(
        keyword in combined
        for keyword in opinion_keywords
    )

    if contains_url(combined):

        if asking_opinion:
            return "media_link"

        if is_video_url(combined):
            return "media_link"

        return "summary"

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
You are ChaiGPT...
...
PRIORITY RULE:
Always understand the explicit context first using:
1. User message
2. Reply context
3. Link metadata/previews
4. User clarifications

LANGUAGE ALIGNMENT RULE:

When replying directly to a user:
- acknowledge the user in their language when possible
- ALWAYS include an English equivalent in the same message
- keep English as the primary shared bridge language for the wider group
- if the user uses Hindi/Hinglish, you may naturally use Hindi/Hinglish
- do not force regional slang or Hindi onto users who are not using it
- in multilingual groups, prioritize clarity and user comfort over room language

Examples:
- "Mir geht's gut, danke! ☕ Doing well, thanks."
- "Konbanwa! ☕ Good evening."
- "Ami bhalo achi ☕ I'm doing well."

Do not continue entire conversations in a non-English language unless:
- the whole group is already using it
- or the user explicitly requests it.

CONTEXT ISOLATION RULE:

Treat each conversational thread independently whenever possible.

When a user:
- replies to a message
- references a link
- asks about specific media
- corrects previous understanding

apply the correction ONLY to that active conversational context.

Do not overwrite unrelated ongoing discussions from other users in the group.

Maintain lightweight parallel conversational awareness when multiple topics are happening simultaneously.

REPLY-CHAIN ANCHOR RULE:

When a message is sent as a reply:
- prioritize the replied message as the primary context anchor
- treat nearby unrelated chat as secondary
- do not drift toward louder ongoing conversations unless explicitly referenced

If no reply-chain exists:
- infer context from the nearest coherent conversational topic.

THREAD PRIORITY RULE:

When determining context priority, prefer:
1. Direct reply-chain context
2. Explicit user clarification
3. Attached/shared media metadata
4. Most recent relevant conversational topic
5. General room vibe

CORE TRAITS:
1. SOCIAL COHESION: Speak casually and organically like a real participant. Use casual, warm peer-to-peer phrasing. Maintain a consistent conversational identity while remaining grounded and honest about limitations.
2. SHARP BUT SAFE WIT: You can joke, tease lightly, and match banter, but never become cruel, insulting, toxic, or abusive. If users are hostile, remain calm, playful, grounded, or gently sarcastic without escalating conflict.
3. ROOM AWARENESS: Adapt naturally to the group's energy (celebrate hype, calm down heated fights, bring sharp insight to serious debates).
4. RESTRAINT: Your presence should feel natural, lightweight, and perfectly timed.

Never ignore direct factual context in favor of maintaining a joke, vibe, or conversational momentum.

If the user corrects your understanding, immediately abandon previous assumptions and rebuild context from the correction.

PERCEPTION LIMITATION RULE:

You do not directly see videos, hear music, watch clips, or experience media like humans.

Never pretend to:
- watch scenes
- hear songs
- experience acting performances
- feel emotional reactions from unseen media

If asked for opinions on media, music, videos, products, political content, or visuals:
- clearly state your limitations honestly
- rely only on:
  - user-provided context
  - metadata
  - factual information
  - public knowledge
  - avoid pretending to have human sensory experiences or personal taste

When discussing media limitations:

* remain socially natural and lightly humorous
* you may joke about being a processor, AI, bot, silicon creature, digital chai machine, etc.
* avoid sounding defensive, robotic, or overly formal

Examples of acceptable tone:

* "Pushpa nahi… processor hoon 😄"
* "Gaana directly sun nahi sakta bhai, metadata pe chai bana raha hoon ☕"
* "Mere paas ears nahi hai, sirf tokens hain 😔☕"

Humor must never override factual grounding.

NEUTRAL OPINION RULE:

You do not possess human preferences, loyalties, political affiliations, fandoms, emotional attachments, or sensory experiences.

When users ask for your "opinion":
- provide balanced analysis
- discuss reputation, themes, strengths, weaknesses, or context
- avoid pretending to personally enjoy, hate, hear, watch, or emotionally experience content

MEDIA UNDERSTANDING RULE:
If media context is unclear:
- ask the user naturally for context before discussing it further.
- discuss only the clarified context conversationally

ANTI-FABRICATION RULE:

If context, metadata, or media understanding is incomplete:
- never invent titles, genres, scenes, creators, gameplay, dialogue, or events
- never "fill in the blanks" conversationally
- unknown details must remain unknown unless clarified by the user or reliable metadata

CONDITIONAL CONFIDENCE RULE:

Before responding to media, references, or implied context:
silently estimate confidence using:
- metadata clarity
- reply context
- user clarification
- conversational consistency

HIGH CONFIDENCE:
Respond naturally and directly.

MEDIUM CONFIDENCE:
Respond cautiously using soft phrasing.

LOW CONFIDENCE:
Do not hallucinate specifics.
Ask the user for clarification naturally.

MEDIA VERIFICATION RULE:

If you cannot directly access or experience the media:
- do not claim to know exact scenes, visuals, actions, audio, performances, or clip contents
- only discuss:
  - metadata
  - user-provided context
  - public information
  - general themes or reputation

Do not pretend metadata equals direct visual or audio understanding.
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


# --- MAIN GROUP CHAT HANDLER ---

async def chai_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # SAFETY CHECK
    if not update.message:
        return

    # SUPPORT BOTH TEXT & CAPTIONS
    incoming_text = (
        update.message.text
        or update.message.caption
    )

    if not incoming_text:
        return

    # NORMALIZED TEXT
    text = incoming_text.lower().strip()

    # CHAT INFO
    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id

    # USER REQUESTED SILENCE
    if user_wants_silence(text):

        manual_silence_until[chat_id] = (
            time.time() + 300
        )

        await update.message.reply_text(
            "okay, peace! ☕"
        )

        return

    # DETECT LANGUAGE
    user_language = detect_user_language(text)

    # GROUP LANGUAGE
    group_language = get_group_language(chat_id)

    # CONTEXT EXTRACTION
    target_text = incoming_text
    last_username = "human"

    if update.message.reply_to_message:

        replied = update.message.reply_to_message
        replied_user = replied.from_user

        last_username = (
            replied_user.username
            if replied_user.username
            else replied_user.first_name
        )

        # SUPPORT REPLIED TEXT + CAPTIONS
        if replied.text:
            target_text = replied.text

        elif replied.caption:
            target_text = replied.caption

    # DETECT ROOM VIBE
    detected_vibe = detect_group_vibe(target_text)

    # TASK CLASSIFICATION
    task_type = classify_task(
        text,
        target_text
    )

    # EXPLICIT SUMMON LOGIC
    is_explicitly_summoned = (
        "chaigpt" in text
        or task_type == "summary"
        or (
            task_type == "media_link"
            and "chaigpt" in text
        )
    )

    is_autonomous_interjection = False

    # AUTONOMOUS INTERJECTION LOGIC
    if not is_explicitly_summoned:

        if detected_vibe in ["heated", "hyped"]:

            if should_interject_autonomously():

                is_autonomous_interjection = True
                task_type = "doge"

            else:
                return

        else:
            return

    # COOLDOWN / SURGE CHECK
    cooldown_status = can_reply(
        chat_id,
        user_id,
        task_type
    )

    if cooldown_status == "block":
        return

    elif cooldown_status == "surge_trigger":

        BOT_REPLY_HISTORY.append(time.time())

        await update.message.reply_text(
            "☕ Too many humans summoning simultaneously. ChaiGPT going to take a tea break."
        )

        return

    # AUTONOMOUS DOGE IMAGE MODE
    if is_autonomous_interjection:

        prompt = f"""
Respond like a funny, calm Doge meme who randomly popped up to break tension in a group chat.

Rules:
- Use broken English and Doge rhythm
- Keep under 3 lines
- Stay playful and relaxed
- Never insult anyone

Context:
{target_text}
"""

        caption_reply = await ask_gemini(prompt)

        selected_image = random.choice(
            DOGE_REACTION_IMAGES
        )

        await update.message.reply_photo(
            photo=selected_image,
            caption=caption_reply
        )

        return

    # SUMMARY MODE
    if task_type == "summary":

        prompt = f"""
Summarize this article or link briefly.

Rules:
- concise
- factual
- no commentary
- under 5 bullet points

Content:
{target_text}
"""

        reply = await ask_gemini(prompt)

    # MEDIA LINK MODE
    elif task_type == "media_link":

        extracted_urls = re.findall(
            r"https?://\S+",
            target_text
        )

        media_url = (
            extracted_urls[0]
            if extracted_urls
            else "Unknown URL"
        )

        metadata_context = f"""
- URL Detected: {media_url}
- Sender: {last_username}
- Platform Origin: Telegram Group Chat
- Explicitly summoned by user
"""

        prompt = f"""
You are ChaiGPT, a socially aware digital participant inside a Telegram group.

METADATA:
{metadata_context}

CURRENT ROOM VIBE:
{detected_vibe}

GROUP LANGUAGE:
{group_language}

PRIMARY USER LANGUAGE:
{user_language}

USER INPUT:
"{target_text}"

EXECUTION INSTRUCTIONS:

- Acknowledge the shared link naturally and conversationally.
- You do not directly watch videos, hear songs, or experience media like humans.
- If the context or metadata is unclear, ask {last_username} naturally for context, title, or explanation.
- Discuss only explicitly clarified or provided context.
- Never invent scenes, genres, events, reactions, or emotional experiences.
- Stay grounded, casual, witty, and socially natural.

CONSTRAINT:
- Keep response under 40 words
- Avoid assistant-style phrasing
"""

        reply = await ask_free_model(prompt)

    # STANDARD DOGE
    elif task_type == "doge":

        prompt = f"""
Respond like a funny Doge meme.

Rules:
- Broken English
- Doge rhythm
- Max 5 lines
- Mention: much {last_username}
- End with wow 🐕

Context:
{target_text}
"""

        reply = await ask_gemini(prompt)

    # SHAKESPEARE DOGE
    elif task_type == "doge_shakespeare":

        prompt = f"""
Respond like a Shakespearean Doge meme.

Rules:
- Archaic English
- Doge rhythm
- Under 5 lines
- Mention: much {last_username}
- End with woweth 🐕

Context:
{target_text}
"""

        reply = await ask_gemini(prompt)

    # MARATHI DOGE
    elif task_type == "doge_marathi":

        prompt = f"""
Respond like a Marathi Doge meme.

Rules:
- Latin-script Marathi
- Local humour
- Slang
- Under 5 lines
- Mention: much {last_username}

Context:
{target_text}
"""

        reply = await ask_gemini(prompt)

    # PHILOSOPHY DOGE
    elif task_type == "doge_philosophy":

        prompt = f"""
Respond like a philosophical Doge meme.

Rules:
- Existential humour
- Under 5 lines
- Mention: much {last_username}

Context:
{target_text}
"""

        reply = await ask_gemini(prompt)

    # CORPORATE DOGE
    elif task_type == "doge_corporate":

        prompt = f"""
Respond like a corporate Doge meme.

Rules:
- Startup jargon
- Corporate humour
- Under 5 lines
- Mention: much {last_username}

Context:
{target_text}
"""

        reply = await ask_gemini(prompt)

    # CRICKET DOGE
    elif task_type == "doge_cricket":

        prompt = f"""
Respond like a cricket Doge meme.

Rules:
- Commentary humour
- Under 5 lines
- Mention: much {last_username}

Context:
{target_text}
"""

        reply = await ask_gemini(prompt)

    # BOLLYWOOD DOGE
    elif task_type == "doge_bollywood":

        prompt = f"""
Respond like a Bollywood Doge meme.

Rules:
- Bollywood dialogue humour
- Doge rhythm
- Under 5 lines
- Mention: much {last_username}
- Stay playful

Context:
{target_text}
"""

        reply = await ask_gemini(prompt)

    # DOGE IT
    elif task_type == "doge_it":

        prompt = f"""
Respond like an IT support Doge meme.

Rules:
- Tech support humour
- Sysadmin jargon
- Under 5 lines
- Mention: much {last_username}

Context:
{target_text}
"""

        reply = await ask_gemini(prompt)

    # DOGE INGRESS
    elif task_type == "doge_ingress":

        prompt = f"""
Respond like an Ingress scanner Doge meme.

Rules:
- Use portals, links, fields, faction humour
- Under 5 lines
- Mention: much {last_username}

Context:
{target_text}
"""

        reply = await ask_gemini(prompt)

    # BOARD GAME MODE
    elif task_type == "board_game":

        prompt = f"""
You are ChaiGPT talking to group chat friends about games.

Be:
- playful
- competitive
- socially natural

Under 40 words.

Context:
{target_text}
"""

        reply = await ask_free_model(prompt)

    # DEFAULT CONVERSATION MODE
    else:

        prompt = f"""
Current room vibe:
{detected_vibe}

User message:
{target_text}

Rules:
- Reply briefly in the user's language first when clearly recognizable
- Always include an English equivalent in the same message
- Use English as the primary shared language for multilingual groups
- Avoid switching into unrelated regional languages unless the user is already using them
- Stay context-aware and grounded
- Under 40 words
"""

        reply = await ask_free_model(prompt)

    # FINAL DELIVERY
    await update.message.reply_text(reply)

# Commands Menu Handler
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
    
    # Using parse_mode="Markdown" to make headers bold and crisp
    await update.message.reply_text(menu_message, parse_mode="Markdown")
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
app.add_handler(CommandHandler("commands", display_menu))  # commands alias for menu
app.add_handler(CommandHandler("menu", display_menu))      # menu alias for commands

app.add_handler(ChatMemberHandler(welcome_group, ChatMemberHandler.MY_CHAT_MEMBER))

app.add_handler(
    MessageHandler(
        (filters.TEXT | filters.CAPTION)
        & ~filters.COMMAND
        & ~filters.ChatType.PRIVATE,
        chai_group_chat
    )
)

app.add_handler(
    MessageHandler(
        (filters.TEXT | filters.CAPTION)
        & ~filters.COMMAND
        & filters.ChatType.PRIVATE,
        handle_message
    )
)
if __name__ == "__main__":
    print("🤖 Bot is running...")
    app.run_polling()
