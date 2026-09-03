"""
Telegram Search Bot — Bot API version (no OTP/session needed)
================================================================
Ye bot ko apne saare deal-channels mein ADMIN banao (member se nahi chalega).
Jab se add hoga, tab se har naya post automatically database mein save hota
rahega. Search usi database mein hota hai — Telegram history API se nahi,
isliye add hone SE PEHLE ka purana data isme nahi milega.

Commands:
    /start            → welcome + all commands
    /help             → same as /start
    /plans            → show all plans with channel list
    /a <keyword>      → search Plan A
    /b <keyword>      → search Plan B
    /c <keyword>      → search Plan C
    /debug            → check which channels bot has seen posts from
"""

import asyncio
import requests as http_requests
import uuid
import threading
import re
import base64
import logging
import sqlite3
import subprocess
from io import BytesIO
from datetime import timezone, timedelta, datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

try:
    from telethon import TelegramClient, events
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)
import os

# Auto-install chromium with all deps on Railway
def ensure_chromium():
    try:
        result = subprocess.run(
            ["playwright", "install", "chromium", "--with-deps"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("✅ Chromium ready!")
        else:
            print(f"Chromium install output: {result.stdout}")
    except Exception as e:
        print(f"Chromium install error: {e}")

ensure_chromium()

# ─────────────────────────────────────────────
#  STEP 1 — Bot credentials
# ─────────────────────────────────────────────
BOT_TOKEN     = os.environ["BOT_TOKEN"]
YOUR_USER_ID  = [int(x.strip()) for x in os.environ.get("AUTHORIZED_USERS", "").split(",") if x.strip()]

# ─────────────────────────────────────────────
#  OPTIONAL — Hybrid Telethon listener
#  Bot API sirf un channels ka data dekh sakta hai jinme bot ADMIN hai.
#  Agar kisi channel ka owner bot ko admin nahi banata, ye personal-account
#  listener us channel ko bhi cover kar leta hai (sirf MEMBER hona kaafi hai).
#  Agar TELETHON_API_ID/HASH/PHONE set nahi hain, ye feature simply skip
#  ho jata hai — Bot API wala hissa bina kisi dikkat ke chalta rehta hai.
# ─────────────────────────────────────────────
TELETHON_API_ID       = os.environ.get("TELETHON_API_ID", "")
TELETHON_API_HASH     = os.environ.get("TELETHON_API_HASH", "")
TELETHON_PHONE        = os.environ.get("TELETHON_PHONE", "")
TELETHON_SESSION_PATH = os.environ.get("TELETHON_SESSION_PATH", "/data/user_session")

# ─────────────────────────────────────────────
#  STEP 2 — Define your channels
#  (name must match exactly what the bot sees as chat.title once added)
# ─────────────────────────────────────────────
CH1  = ("Trending Loot Deals",                        "https://telegram.me/+CmTgiyYxFC0zMjg1")
CH2  = ("Deals Point",                                "https://telegram.me/+KgUrCwnDny02ZDk1")
CH3  = ("Offer Box Official",                         "https://telegram.me/+Th6aG5Zaxz_i_u7a")
CH4  = ("Lallantop Deals",                            "https://telegram.me/+QtY0L4n6LP01SN2v")
CH5  = ("FRCP (Deals & Offers)",                      "https://telegram.me/+LNRQ0Y1-9RkzZDRl")
CH6  = ("Deals Velocity",                             "https://telegram.me/+-o6XWyLrbTMxMTI1")
CH7  = ("OMG Loot Deals",                             "https://telegram.me/+U0JGtNSiohCClvnC")
CH8  = ("Alibaba Loot Deals",                         "https://t.me/+AdUPh392S6xhNmY1")
CH9  = ("Rapid Deals Unlimited",                      "https://t.me/rapiddeals_unlimited")
CH10 = ("AliBaba Loot Deals (Offers Ki Dunia Official)", "https://t.me/+IHduQpnoHxZlN2Jl")

# ─────────────────────────────────────────────
#  STEP 3 — Assign channels to plans
# ─────────────────────────────────────────────
PLAN_A = [CH1, CH2, CH5, CH10]
PLAN_B = [CH1, CH2, CH5, CH10, CH7, CH3, CH4]
PLAN_C = [CH1, CH2, CH3, CH4, CH5, CH6, CH7, CH8, CH9]

SEARCH_HOURS = 12   # only search posts from last X hours

# ── Hot-Deal Auto-Alert config ─────────────────────────
# Jab bhi neeche wali list ka koi brand/keyword kisi Plan (A/B/C) ke SAARE
# channels mein post ho jaye (AUTO_ALERT_WINDOW_MINUTES ke andar), bot khud
# us plan ka poora screenshot generate karke bhej dega. Link match nahi karta
# (har channel apna alag affiliate link daalta hai) — sirf keyword/brand text
# match karta hai, isliye zyada reliable hai.
AUTO_ALERT_WINDOW_MINUTES = 15

# Ye sirf DEFAULT/starting list hai — pehli baar bot chalne par ye file mein
# save ho jayegi. Uske baad /addkeyword, /removekeyword, /keywords commands
# se seedha Telegram se hi manage kar sakte ho, code edit karne ki zaroorat nahi.
DEFAULT_AUTO_ALERT_KEYWORDS = [
    "aqueria", "urbn", "Bella Vita", "boat", "oscar", "lifelong", "amazon pay",
    "wicked gud", "dubstep", "sirona", "bla bli blu", "plantex", "desidiya", "bigmuscle",
    "fytika", "kapiva", "skullcandy", "orient", "rage", "medibuddy", "exercise",
    "fitness", "abexcerciser", "portonics", "realme", "jockey", "baby care",
    "baby diaper", "flipkart", "epson", "havells", "babur", "halonix", "mcaffeine",
    "dubset", "nutribrust", "tower", "ai+", "mamypoko", "wishcare", "kick scooter",
    "dexogrow", "Stuffcool", "redme", "gold", "bournvita", "dermaco", "baidyanath",
    "my fitness", "pilgrim", "provouge", "kids toys", "beyond", "cheffin", "Toreto",
    "Oziva", "Vervenix", "jabra", "Yogabar", "Nutrabuds", "raxon", "sale post", "apple",
    "powerbank", "cables", "mi powerbank", "vw", "Liposomal", "personal care",
    "detergent", "nutriglow", "eucos", "vega", "liquid", "milton", "tv", "zebronics",
    "spigen cover", "kids scooter", "reuable", "pest control", "royal fusion", "samsung",
    "ayuvana", "lila", "maternity pads", "godrej", "hushbay", "bosch", "hipkoo",
    "bathla", "remote car", "plix", "dr morepen", "naturaltein", "dr seths",
    "himalaya shivang", "car", "kozicare", "cadlec kitchen", "heaven décor", "q device",
    "youva", "sujata", "cred", "shilajit", "hk vitals", "aristocrate", "kuchipoo",
    "exercise cycle", "treadmill", "beardo", "bajaj", "rasayanam", "complan", "forest",
    "neemans", "little anglel", "dermatouch", "sugar", "deconstruct", "ruhe", "volo",
    "qubo", "muscleblase", "nutrabay", "optimum nutrion", "lemorte", "agaro",
    "home kitchen", "branded screen guard", "kesh king", "mirabelle", "bonkasio",
    "art & craft", "GNC", "Miton", "Lattitude", "Herb", "Dolls & Dolls", "Mee Mee",
    "Indoor Ganes", "Fitnnes beach", "Exercise Bike", "Pen", "cycel", "origami",
    "Molecular Company", "velbiorn", "Mush Bamboo", "Board Games earnpe",
    "baby activity earnpe", "philips earnpe", "sycle", "bike", "cycle", "shaker", "iqoo",
    "air fryer", "Syngenta", "lg tv", "crocs", "Wildcraft", "American Tousister",
    "Nirvasa", "Dr. Morepen", "TP link", "camping tent", "back & Abdomen",
    "resistance tube", "fitness epqipment", "Caresmith", "oralB", "Oneplus",
    "Bunny earnpe", "lego earnpe", "kids toy earnpe", "libas", "Optimist",
    "laptop accessories", "sports", "walkpad", "mamaearth", "bblunt", "goodcare",
    "cricket", "fastup", "supradyn", "scoot International", "earnpe", "kids mandi",
    "kraasa", "fubar", "hp tablet", "li ning", "healtyhey", "vlado", "Portronics",
    "Rakhi", "Sanilo", "campus", "CMF", "go boult", "bhim", "Zomato", "Ensure",
    "Bissell", "Purna", "Nutriburst", "A R Ayurveda", "motorola", "plant", "nutrela",
    "magnesium", "joy", "dr truskin", "the derma co", "baben", "ambrane", "kinsco",
    "sugar fit", "miduty", "one 8", "fuelone", "Foxsky", "Lemonn", "little angel",
    "baby walker", "little joy", "beast Life", "liberty", "horlics", "Bear", "noise",
    "parxen", "Navi", "boltt", "vyom", "aquon", "Pw", "nakpro", "cash counting", "beetl",
    "Undenatured", "Copier Paper", "TMC", "Ghangaria", "Modius", "Awsome", "Clarity Lab",
    "Lava",
    # naye keyword (is baar ke request se)
    "loot", "grab", "fast", "loot fast", "grab fast", "lowest", "set of", "weight",
    "management",
]

KEYWORDS_FILE = os.environ.get("KEYWORDS_FILE", "/data/alert_keywords.json")

def load_alert_keywords():
    import json
    try:
        if os.path.exists(KEYWORDS_FILE):
            with open(KEYWORDS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        log.error(f"load_alert_keywords: {e}")
    return list(DEFAULT_AUTO_ALERT_KEYWORDS)

def save_alert_keywords(keywords):
    import json
    try:
        os.makedirs(os.path.dirname(KEYWORDS_FILE), exist_ok=True)
        with open(KEYWORDS_FILE, 'w') as f:
            json.dump(keywords, f, indent=2)
    except Exception as e:
        log.error(f"save_alert_keywords: {e}")

AUTO_ALERT_KEYWORDS = load_alert_keywords()
if not os.path.exists(KEYWORDS_FILE):
    save_alert_keywords(AUTO_ALERT_KEYWORDS)  # pehli baar file bana do

alerted_plan_keywords = set()  # (plan, keyword) pairs jinke liye already alert ja chuka hai
IST          = timezone(timedelta(hours=5, minutes=30))
PLANS        = {"A": PLAN_A, "B": PLAN_B, "C": PLAN_C}

# ─────────────────────────────────────────────
#  BRAND → WhatsApp Group mapping
#  Jab bhi search keyword mein neeche wala brand-word aaye (case-insensitive,
#  keyword ke andar kahin bhi), screenshot ke saath ek extra
#  "📤 Send to <Brand>" button dikhega — us specific WhatsApp group ke liye.
#  Right side ("Orient Deals Group") bilkul EXACT wahi naam hona chahiye
#  jo WhatsApp mein group ka naam hai (case-sensitive match hota hai).
# ─────────────────────────────────────────────
BRAND_GROUPS = {
    "orient": "Orient Deals Group",   # <-- yahan Orient ke actual WA group ka naam daalo
    # "samsung": "Samsung Deals Group",
    # "boat":    "Boat Deals Group",
    # jitne chahiye utne brand: group pairs yahan add karte jao
}

def find_brand_for_keyword(keyword: str):
    """Keyword ke andar koi known brand-word ho toh uska WA group name return karo."""
    kw_lower = keyword.lower()
    for brand, group_name in BRAND_GROUPS.items():
        if brand in kw_lower:
            return brand, group_name
    return None, None

def wa_find_group_by_name(name: str):
    """WA groups list mein se naam match karke group dict {id, name} return karo."""
    groups = wa_get_groups()
    for g in groups:
        if g["name"].strip().lower() == name.strip().lower():
            return g
    return None

# ─────────────────────────────────────────────
#  DATABASE — stores every channel post the bot sees, once added as admin
# ─────────────────────────────────────────────
DB_PATH = os.environ.get("DB_PATH", "/data/messages.db")

def db_init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            chat_id     INTEGER,
            chat_title  TEXT,
            username    TEXT,
            message_id  INTEGER,
            text        TEXT,
            date_utc    TEXT,
            PRIMARY KEY (chat_id, message_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            chat_id     INTEGER PRIMARY KEY,
            chat_title  TEXT,
            username    TEXT,
            photo_b64   TEXT
        )
    """)
    conn.commit()
    conn.close()

def db_save_message(chat_id, chat_title, username, message_id, text, date_utc):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO messages (chat_id, chat_title, username, message_id, text, date_utc) VALUES (?,?,?,?,?,?)",
        (chat_id, chat_title, username, message_id, text, date_utc.isoformat())
    )
    conn.execute(
        "INSERT OR REPLACE INTO channels (chat_id, chat_title, username, photo_b64) VALUES (?,?,?, COALESCE((SELECT photo_b64 FROM channels WHERE chat_id=?), ''))",
        (chat_id, chat_title, username, chat_id)
    )
    conn.commit()
    conn.close()

def db_update_photo(chat_id, photo_b64):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE channels SET photo_b64=? WHERE chat_id=?", (photo_b64, chat_id))
    conn.commit()
    conn.close()

def db_get_known_channels():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT chat_id, chat_title, username, photo_b64 FROM channels").fetchall()
    conn.close()
    return rows

def db_search(chat_title: str, keyword: str, cutoff_utc: datetime):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT chat_id, username, message_id, text, date_utc FROM messages "
        "WHERE chat_title = ? COLLATE NOCASE AND text LIKE ? AND date_utc >= ? "
        "ORDER BY date_utc DESC LIMIT 1",
        (chat_title, f"%{keyword}%", cutoff_utc.isoformat())
    ).fetchone()
    conn.close()
    return row

def db_search_any_channel(keyword: str, cutoff_utc: datetime):
    """Like link-tracker's search: find the latest match in EVERY tracked
    channel (not limited to a plan's fixed channel list). Used when someone
    pastes a link/keyword directly instead of using /a /b /c."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """
        SELECT chat_id, chat_title, username, message_id, text, date_utc FROM messages m
        WHERE text LIKE ? AND date_utc >= ?
          AND date_utc = (
              SELECT MAX(date_utc) FROM messages m2
              WHERE m2.chat_id = m.chat_id AND m2.text LIKE ? AND m2.date_utc >= ?
          )
        ORDER BY date_utc DESC
        """,
        (f"%{keyword}%", cutoff_utc.isoformat(), f"%{keyword}%", cutoff_utc.isoformat())
    ).fetchall()
    conn.close()
    return rows

# ── WhatsApp API Config ──────────────────────────────────
WA_API_URL = os.environ.get('WA_API_URL', '').rstrip('/')
WA_API_KEY = os.environ.get('WA_API_KEY', '')

# ── WhatsApp State ────────────────────────────────────────
user_wa_group = {}
pending_send  = {}
sent_wa       = {}

# ── Plan → WA Group mapping (persistent) ─────────────────
PLAN_GROUPS_FILE = os.environ.get("PLAN_GROUPS_FILE", "/data/plan_groups.json")

def load_plan_groups():
    import json
    try:
        if os.path.exists(PLAN_GROUPS_FILE):
            with open(PLAN_GROUPS_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_plan_groups(data):
    import json
    try:
        with open(PLAN_GROUPS_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        log.error(f'save_plan_groups: {e}')

plan_wa_groups = load_plan_groups()

def wa_headers():
    return {'x-api-key': WA_API_KEY, 'Content-Type': 'application/json'}

def wa_get_groups():
    if not WA_API_URL or not WA_API_KEY:
        return []
    try:
        r = http_requests.get(f'{WA_API_URL}/groups', headers=wa_headers(), timeout=10)
        return r.json().get('groups', [])
    except Exception as e:
        log.error(f'wa_get_groups: {e}')
        return []

def wa_send_image(group_id, img_b64, caption=''):
    r = http_requests.post(f'{WA_API_URL}/send', headers=wa_headers(),
        json={'type': 'image', 'content': img_b64, 'groupId': group_id, 'caption': caption},
        timeout=30)
    return r.json()

def wa_delete(group_id, key):
    r = http_requests.post(f'{WA_API_URL}/delete', headers=wa_headers(),
        json={'groupId': group_id, 'key': key}, timeout=10)
    return r.json().get('success', False)

# ── Helpers ───────────────────────────────────

def to_ist(dt) -> str:
    return dt.astimezone(IST).strftime("%I:%M %p")

def get_initials(name: str) -> str:
    words = name.strip().split()
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    return name[:2].upper() if name else "??"

def highlight(text: str, keyword: str) -> str:
    pat = re.compile(re.escape(keyword), re.IGNORECASE)
    return pat.sub(lambda m: f'<span class="hl">{m.group(0)}</span>', text)

COLORS = ["#1565C0","#6A1B9A","#2E7D32","#AD1457",
          "#00695C","#E65100","#4527A0","#0277BD"]

def avatar_color(name: str) -> str:
    return COLORS[sum(ord(c) for c in name) % len(COLORS)]

# ── Fetch channel profile photo (Bot API) ─────

bot_instance = None  # set in main()

async def refresh_photo_if_needed(chat_id: int, chat_title: str):
    known = {row[0]: row[3] for row in db_get_known_channels()}
    if known.get(chat_id):
        return
    try:
        chat = await bot_instance.get_chat(chat_id)
        if chat.photo:
            file = await bot_instance.get_file(chat.photo.small_file_id)
            data = await file.download_as_bytearray()
            b64 = "data:image/jpeg;base64," + base64.b64encode(bytes(data)).decode()
            db_update_photo(chat_id, b64)
    except Exception as e:
        log.warning(f"Photo fetch failed for {chat_title}: {e}")

# ── Telethon hybrid listener (for channels where bot can't be admin) ─────

async def telethon_refresh_photo(client, chat_id: int, chat_title: str):
    known = {row[0]: row[3] for row in db_get_known_channels()}
    if known.get(chat_id):
        return
    try:
        data = await client.download_profile_photo(chat_id, file=bytes)
        if data:
            b64 = "data:image/jpeg;base64," + base64.b64encode(data).decode()
            db_update_photo(chat_id, b64)
    except Exception as e:
        log.warning(f"Telethon photo fetch failed for {chat_title}: {e}")


def register_telethon_handlers(client):
    """Telethon client pe naye messages ka listener lagata hai — jitne bhi
    channels mein ye personal account member hai, sab cover ho jate hain."""

    @client.on(events.NewMessage)
    async def _on_telethon_message(event):
        try:
            if not event.message or not event.message.text:
                return
            chat = await event.get_chat()
            title = getattr(chat, "title", None)
            if not title:
                return  # DMs, bots, waghera skip — sirf channels/groups chahiye
            username = getattr(chat, "username", None)

            db_save_message(chat.id, title, username or "", event.message.id, event.message.text, event.message.date)
            asyncio.create_task(telethon_refresh_photo(client, chat.id, title))

            text_lower = event.message.text.lower()
            matched = [kw for kw in AUTO_ALERT_KEYWORDS if kw.lower() in text_lower]
            for kw in matched:
                asyncio.create_task(check_plan_full_coverage(kw))
        except Exception as e:
            log.error(f"Telethon message handler error: {e}", exc_info=True)

    log.info("✅ Telethon hybrid listener registered.")

# ── Channel post listener — this is what replaces Telethon ────

async def check_plan_full_coverage(keyword: str):
    """Agar ye keyword/brand kisi Plan ke SAARE channels mein mil chuka hai
    (last AUTO_ALERT_WINDOW_MINUTES mein), us plan ka poora screenshot
    generate karke saare authorized users ko bhej do."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=AUTO_ALERT_WINDOW_MINUTES)
    rows = await asyncio.get_event_loop().run_in_executor(
        None, lambda: db_search_any_channel(keyword, cutoff)
    )
    if not rows:
        return

    matched_titles_lower = {(row[1] or "").lower() for row in rows}
    known = {row[1].lower(): (row[2], row[3]) for row in db_get_known_channels() if row[1]}
    rows_by_title = {(row[1] or "").lower(): row for row in rows}

    for plan_name, plan_channels in PLANS.items():
        plan_names_lower = {ch[0].lower() for ch in plan_channels}
        if not plan_names_lower.issubset(matched_titles_lower):
            continue  # is plan ke saare channels mein abhi tak nahi aaya

        key = (plan_name, keyword.lower())
        if key in alerted_plan_keywords:
            continue  # is plan ke liye is keyword pe pehle hi alert bhej chuke hain
        alerted_plan_keywords.add(key)

        results = []
        for ch_name, ch_link in plan_channels:
            row = rows_by_title.get(ch_name.lower())
            _, photo_b64 = known.get(ch_name.lower(), (None, ""))
            if row:
                chat_id, chat_title, username, message_id, msg_text, date_utc = row
                dt = datetime.fromisoformat(date_utc)
                post_link = f"https://t.me/{username}/{message_id}" if username else f"https://t.me/c/{abs(chat_id)}/{message_id}"
                results.append({
                    "channel": ch_name, "time": to_ist(dt), "text": msg_text,
                    "link": post_link, "photo_b64": photo_b64, "found": True,
                })
            else:
                results.append({"channel": ch_name, "found": False, "photo_b64": photo_b64})

        try:
            png_bytes = await make_screenshot(results, keyword, plan_name)
            caption = (f"🔥 *Plan {plan_name} mein '{keyword}' poore plan mein mila!* "
                       f"Sab {len(plan_channels)} channels mein aaya:\n\n" +
                       "\n".join(r["link"] for r in results if r.get("found")))[:1020]
            img_b64 = base64.b64encode(png_bytes).decode()
            wa_grp = plan_wa_groups.get(plan_name)

            if wa_grp and WA_API_URL:
                # Seedha WhatsApp group mein bhej do — button dabana nahi padega
                wa_caption = caption.strip()[:900]
                res = wa_send_image(wa_grp['id'], img_b64, wa_caption)
                if res.get('success'):
                    del_id = f'wd_{uuid.uuid4().hex[:8]}'
                    sent_wa[del_id] = {'key': res['key'], 'group_id': wa_grp['id']}
                    threading.Timer(600, lambda: sent_wa.pop(del_id, None)).start()
                    tg_caption = f"✅ *Auto-sent to {wa_grp['name']}!*\n\n{caption[:850]}"
                    kb = InlineKeyboardMarkup([[
                        InlineKeyboardButton('🗑️ Delete from WhatsApp', callback_data=del_id)
                    ]])
                else:
                    tg_caption = f"⚠️ WhatsApp send fail hua ({res.get('error', 'unknown')}):\n\n{caption[:850]}"
                    kb = build_send_buttons(keyword, img_b64, caption.strip()[:900], plan=plan_name, plan_wa_grp=wa_grp)
            else:
                tg_caption = caption[:900]
                kb = build_send_buttons(keyword, img_b64, caption.strip()[:900], plan=plan_name, plan_wa_grp=wa_grp)

            for uid in YOUR_USER_ID:
                await bot_instance.send_photo(
                    chat_id=uid, photo=BytesIO(png_bytes),
                    caption=tg_caption[:1020], parse_mode="Markdown", reply_markup=kb,
                )
        except Exception as e:
            log.error(f"Plan auto-alert failed for Plan {plan_name}: {e}", exc_info=True)


async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg or not msg.text:
        return
    chat = msg.chat
    db_save_message(chat.id, chat.title or "", chat.username or "", msg.message_id, msg.text, msg.date)
    asyncio.create_task(refresh_photo_if_needed(chat.id, chat.title or ""))

    text_lower = msg.text.lower()
    matched = [kw for kw in AUTO_ALERT_KEYWORDS if kw.lower() in text_lower]
    for kw in matched:
        asyncio.create_task(check_plan_full_coverage(kw))

# ── HTML builder ──────────────────────────────

def build_html(results: list, keyword: str, plan: str) -> str:
    rows = ""
    found_count    = sum(1 for r in results if r.get("found"))
    notfound_count = len(results) - found_count

    for m in results:
        name  = m["channel"]
        found = m.get("found", False)

        photo = m.get("photo_b64", "")
        if photo:
            avatar_html = f'<img class="avatar-img" src="{photo}" alt="{name}"/>'
        else:
            initials    = get_initials(name)
            color       = avatar_color(name)
            faded_cls   = " faded" if not found else ""
            avatar_html = f'<div class="avatar-txt{faded_cls}" style="background:{color};">{initials}</div>'

        if found:
            clean = m["text"].replace("**","").replace("__","").replace("`","").replace("~~","")
            preview  = highlight(clean[:110].replace("\n", " "), keyword)
            if len(m["text"]) > 110:
                preview += "..."
            link     = m.get("link", "")
            link_tag = f'<a class="msg-link" href="{link}">View post ↗</a>' if link else ""
            rows += f"""
            <div class="row">
              {avatar_html}
              <div class="body">
                <div class="top">
                  <span class="chan">{name}</span>
                  <span class="time">{m['time']}</span>
                </div>
                <div class="preview">{preview}</div>
                {link_tag}
              </div>
            </div>
            <div class="divider"></div>"""
        else:
            rows += f"""
            <div class="row faded-row">
              {avatar_html}
              <div class="body">
                <div class="top">
                  <span class="chan faded-text">{name}</span>
                </div>
                <div class="preview not-found">❌ Not posted</div>
              </div>
            </div>
            <div class="divider"></div>"""

    plan_colors = {"A": "#1976D2", "B": "#7B1FA2", "C": "#2E7D32"}
    badge_color = plan_colors.get(plan, "#333")
    nf_badge = f'&nbsp;&nbsp;<span class="meta-miss">✗ {notfound_count} not posted</span>' if notfound_count > 0 else ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{
    font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif;
    background:#fff; width:420px;
    -webkit-font-smoothing: antialiased;
  }}
  .searchbar {{
    display:flex; align-items:center; gap:10px;
    padding:10px 14px; border-bottom:1px solid #e0e0e0;
  }}
  .plan-badge {{
    background:{badge_color}; color:#fff;
    font-size:11px; font-weight:700;
    padding:2px 8px; border-radius:20px;
    flex-shrink:0; letter-spacing:0.05em;
  }}
  .search-input {{
    flex:1; border:none; outline:none;
    font-size:16px; font-family:inherit; color:#000; font-weight:500;
  }}
  .clear-btn {{ color:#aaa; font-size:16px; }}
  .meta {{
    display:flex; justify-content:space-between; align-items:center;
    padding:6px 14px; font-size:13px; color:#707579;
    background:#f4f4f5; border-bottom:1px solid #e8e8e8;
  }}
  .meta-found {{ color:#2E7D32; font-weight:600; }}
  .meta-miss  {{ color:#c62828; font-weight:600; }}
  .row {{
    display:flex; align-items:center; gap:12px;
    padding:10px 14px; background:#fff;
  }}
  .faded-row {{ background:#fafafa; }}
  img.avatar-img {{
    width:48px; height:48px; border-radius:50%;
    object-fit:cover; flex-shrink:0;
  }}
  .avatar-txt {{
    width:48px; height:48px; border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    font-size:17px; font-weight:700; color:#fff; flex-shrink:0;
  }}
  .avatar-txt.faded {{ opacity:0.35; }}
  .body {{ flex:1; min-width:0; }}
  .top {{
    display:flex; justify-content:space-between;
    align-items:baseline; margin-bottom:2px;
  }}
  .chan {{
    font-size:15px; font-weight:600; color:#000;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    max-width:240px;
  }}
  .faded-text {{ color:#bbb !important; font-weight:500 !important; }}
  .time {{ font-size:12px; color:#707579; flex-shrink:0; margin-left:8px; }}
  .preview {{
    font-size:13.5px; color:#707579;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }}
  .preview.not-found {{ color:#e57373; font-style:italic; font-size:12.5px; }}
  .msg-link {{
    display:inline-block; margin-top:3px;
    font-size:12px; color:#2196F3; text-decoration:none; font-weight:500;
  }}
  .hl {{ color:#2196F3; font-weight:600; }}
  .divider {{ height:1px; background:#f0f0f0; margin-left:74px; }}
</style></head><body>
  {rows}
</body></html>"""

# ── Screenshot using Playwright ─────────────────

async def make_screenshot(results: list, keyword: str, plan: str) -> bytes:
    from playwright.async_api import async_playwright
    html = build_html(results, keyword, plan)
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage", "--disable-gpu"]
        )
        page = await browser.new_page(
            viewport={"width": 420, "height": 800},
            device_scale_factor=2
        )
        await page.set_content(html, wait_until="networkidle")
        h = await page.evaluate("document.body.scrollHeight")
        await page.set_viewport_size({"width": 420, "height": h})
        png = await page.screenshot(full_page=True)
        await browser.close()
    return png

# ── Search (reads from local DB instead of live Telegram history) ──

def _search_sync(keyword: str, plan_channels: list) -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=SEARCH_HOURS)
    known = {row[1].lower(): (row[2], row[3]) for row in db_get_known_channels() if row[1]}

    results = []
    for ch_name, ch_link in plan_channels:
        row = db_search(ch_name, keyword, cutoff)
        _, photo_b64 = known.get(ch_name.lower(), (None, ""))
        if row:
            chat_id, username, message_id, text, date_utc = row
            dt = datetime.fromisoformat(date_utc)
            link = f"https://t.me/{username}/{message_id}" if username else f"https://t.me/c/{abs(chat_id)}/{message_id}"
            results.append({
                "channel":   ch_name,
                "time":      to_ist(dt),
                "text":      text,
                "link":      link,
                "photo_b64": photo_b64,
                "found":     True,
            })
        else:
            results.append({"channel": ch_name, "found": False, "photo_b64": photo_b64})
    return results

# ── /start and /help text ─────────────────────

def start_text() -> str:
    a_names = ", ".join(ch[0] for ch in PLAN_A)
    b_names = ", ".join(ch[0] for ch in PLAN_B)
    c_names = ", ".join(ch[0] for ch in PLAN_C)
    return (
        "👋 *Welcome to Telegram Keyword Scanner Bot*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 /a keyword — Plan A ({len(PLAN_A)} channels)\n"
        f"_{a_names}_\n\n"
        f"📦 /b keyword — Plan B ({len(PLAN_B)} channels)\n"
        f"_{b_names}_\n\n"
        f"📦 /c keyword — Plan C ({len(PLAN_C)} channels)\n"
        f"_{c_names}_\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📋 /plans — Show all plans and channels\n"
        "🔧 /debug — Check which channels bot has seen posts from\n"
        "🏷️ /addkeyword <word> — Auto-alert keyword add karo\n"
        "🗑️ /removekeyword <word> — Auto-alert keyword hatao\n"
        "📋 /keywords — Saare auto-alert keywords dekho\n"
        "❓ /help — Show this message\n\n"
        "*Examples:*\n"
        "`/a iPhone`\n"
        "`/b Samsung`\n"
        "`/c Shoes`\n\n"
        "⚠️ *Important:* Bot ko har channel mein ADMIN banao. Sirf add hone ke "
        "baad ke posts hi search hote hain, purana data nahi milega."
    )

def plans_text() -> str:
    emoji = {"A": "🔵", "B": "🟣", "C": "🟢"}
    lines = ["📋 *All Plans and Channels*\n"]
    for plan, channels in PLANS.items():
        lines.append(f"{emoji.get(plan,'⚪')} *Plan {plan}* — {len(channels)} channels")
        for i, (name, link) in enumerate(channels, 1):
            lines.append(f"  {i}. {name}")
        lines.append("")
    return "\n".join(lines)

# ── Bot handlers ──────────────────────────────

def build_all_group_buttons(img_b64: str, caption: str):
    """Direct-text search ke baad har WhatsApp group ka button dikhata hai —
    jo bhi chahiye tap karke seedha wahan bhej do."""
    if not WA_API_URL:
        return None
    groups = wa_get_groups()
    if not groups:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton('⚠️ Koi WhatsApp group nahi mila (bot connected hai?)', callback_data='no_grp')
        ]])
    rows = []
    for g in groups[:25]:  # Telegram inline keyboard limit ke andar
        cb_id = f'ws_{uuid.uuid4().hex[:8]}'
        pending_send[cb_id] = {
            'img_b64': img_b64, 'caption': caption,
            'group_id': g['id'], 'group_name': g['name'],
        }
        threading.Timer(1800, lambda cid=cb_id: pending_send.pop(cid, None)).start()
        rows.append([InlineKeyboardButton(f'📤 {g["name"]}', callback_data=cb_id)])
    return InlineKeyboardMarkup(rows)


def build_send_buttons(keyword: str, img_b64: str, caption: str, plan: str = None, plan_wa_grp: dict = None):
    """Plan-group button + (agar keyword mein brand-word mile) brand-group button banata hai."""
    rows = []

    if plan_wa_grp and WA_API_URL:
        cb_id = f'ws_{uuid.uuid4().hex[:8]}'
        pending_send[cb_id] = {
            'img_b64': img_b64, 'caption': caption,
            'group_id': plan_wa_grp['id'], 'group_name': plan_wa_grp['name'],
        }
        threading.Timer(1800, lambda: pending_send.pop(cb_id, None)).start()
        rows.append([InlineKeyboardButton(f'📤 Send to Plan {plan} Group ({plan_wa_grp["name"]})', callback_data=cb_id)])
    elif plan and WA_API_URL:
        rows.append([InlineKeyboardButton(f'⚠️ Set Plan {plan} group (/setgroup {plan.lower()})', callback_data=f'no_grp_{plan}')])

    brand, brand_group_name = find_brand_for_keyword(keyword)
    if brand and WA_API_URL:
        brand_grp = wa_find_group_by_name(brand_group_name)
        if brand_grp:
            cb_id2 = f'ws_{uuid.uuid4().hex[:8]}'
            pending_send[cb_id2] = {
                'img_b64': img_b64, 'caption': caption,
                'group_id': brand_grp['id'], 'group_name': brand_grp['name'],
            }
            threading.Timer(1800, lambda: pending_send.pop(cb_id2, None)).start()
            rows.append([InlineKeyboardButton(f'📤 Send to {brand.capitalize()} ({brand_grp["name"]})', callback_data=cb_id2)])
        else:
            rows.append([InlineKeyboardButton(
                f'⚠️ "{brand_group_name}" WA group nahi mila (naam check karo)', callback_data='no_grp')])

    return InlineKeyboardMarkup(rows) if rows else None


async def plan_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, plan: str):
    user_id = update.effective_user.id
    if user_id not in YOUR_USER_ID:
        await update.message.reply_text("⛔ Unauthorised.")
        return

    keyword = " ".join(context.args).strip() if context.args else ""
    if not keyword:
        await update.message.reply_text(
            f"⚠️ Please provide a keyword.\nExample: `/{plan.lower()} iphone`",
            parse_mode="Markdown"
        )
        return

    plan_channels = PLANS.get(plan, [])
    status = await update.message.reply_text(
        f"🔍 Searching *{keyword}* in Plan {plan} ({len(plan_channels)} channels)...",
        parse_mode="Markdown"
    )

    try:
        results = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _search_sync(keyword, plan_channels)
        )

        found_count = sum(1 for r in results if r.get("found"))

        if found_count == 0:
            await status.edit_text(
                f"❌ No results for *{keyword}* in Plan {plan}",
                parse_mode="Markdown"
            )
            return

        await status.edit_text("📸 Generating screenshot...")
        png_bytes = await make_screenshot(results, keyword, plan)

        not_found_count = len(results) - found_count
        links = ""
        for r in results:
            if r.get("found") and r.get("link"):
                links += f"{r['link']}\n"

        if not_found_count > 0:
            links += f"\n❌ Not posted ({not_found_count}): "
            links += ", ".join(r['channel'] for r in results if not r.get("found"))

        caption = links.strip()[:1020]
        wa_grp = plan_wa_groups.get(plan) or user_wa_group.get(user_id)
        img_b64 = base64.b64encode(png_bytes).decode()
        kb = build_send_buttons(keyword, img_b64, caption.strip()[:900], plan=plan, plan_wa_grp=wa_grp)

        await update.message.reply_photo(
            photo=BytesIO(png_bytes),
            caption=caption[:900],
            reply_markup=kb,
        )
        await status.delete()

    except Exception as e:
        log.error(f"Error: {e}", exc_info=True)
        await status.edit_text(f"⚠️ Error: {e}")

# ── /setgroup ─────────────────────────────────────────────

async def cmd_setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in YOUR_USER_ID:
        return await update.message.reply_text('⛔ Unauthorised.')
    if not WA_API_URL:
        return await update.message.reply_text('❌ WA_API_URL set nahi hai.')

    args = context.args
    if not args or args[0].upper() not in ['A', 'B', 'C']:
        current = []
        for p in ['A', 'B', 'C']:
            g = plan_wa_groups.get(p)
            current.append(f'Plan {p}: {g["name"] if g else "❌ Not set"}')
        return await update.message.reply_text(
            f'📋 *Plan Group Settings:*\n\n' +
            '\n'.join(current) +
            '\n\n*Usage:* /setgroup a, /setgroup b, /setgroup c',
            parse_mode='Markdown'
        )

    plan = args[0].upper()
    msg = await update.message.reply_text(f'🔄 Plan {plan} ke liye groups load ho rahe hain...')
    groups = wa_get_groups()
    if not groups:
        return await msg.edit_text('❌ Groups nahi mile. WA API connected hai?')

    kb = [[InlineKeyboardButton(f'💬 {g["name"]}', callback_data=f'sg_{plan}_{i}')]
          for i, g in enumerate(groups[:25])]
    context.user_data['wa_groups'] = groups
    await msg.edit_text(
        f'📋 *Plan {plan}* ke liye group select karo:',
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ── /wagroup ──────────────────────────────────────────────

async def cmd_wagroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in YOUR_USER_ID:
        await update.message.reply_text("⛔ Unauthorised.")
        return
    if not WA_API_URL:
        return await update.message.reply_text('❌ WA_API_URL env var set nahi hai.')
    msg = await update.message.reply_text('🔄 WhatsApp groups load ho rahe hain...')
    groups = wa_get_groups()
    if not groups:
        return await msg.edit_text('❌ Groups nahi mile. WA API connected hai?')
    kb = [[InlineKeyboardButton(f'💬 {g["name"]}', callback_data=f'wg_{i}')]
          for i, g in enumerate(groups[:25])]
    context.user_data['wa_groups'] = groups
    await msg.edit_text(
        f'💬 *WhatsApp Groups ({len(groups)}):*\nEk select karo 👇',
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(kb)
    )

# ── Callback handler ──────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query
    uid  = q.from_user.id
    data = q.data
    await q.answer()

    if data.startswith('wg_'):
        idx    = int(data[3:])
        groups = context.user_data.get('wa_groups', [])
        if idx >= len(groups):
            return await q.edit_message_text('❌ /wagroup dobara try karo.')
        g = groups[idx]
        user_wa_group[uid] = {'id': g['id'], 'name': g['name']}
        return await q.edit_message_text(
            f'✅ *{g["name"]}* select ho gaya!\n\nAb /a /b /c se search karo 🚀',
            parse_mode='Markdown'
        )

    if data == 'no_grp' or data.startswith('no_grp_'):
        plan = data.split('_')[-1] if '_' in data[7:] else ''
        msg = f'Pehle /setgroup {plan.lower()} se group set karo!' if plan else 'Pehle /wagroup se group select karo!'
        return await q.answer(msg, show_alert=True)

    if data.startswith('sg_'):
        parts = data.split('_')
        plan  = parts[1]
        idx   = int(parts[2])
        groups = context.user_data.get('wa_groups', [])
        if idx >= len(groups):
            return await q.edit_message_text('❌ /setgroup dobara try karo.')
        g = groups[idx]
        plan_wa_groups[plan] = {'id': g['id'], 'name': g['name']}
        save_plan_groups(plan_wa_groups)
        return await q.edit_message_text(
            f'✅ *Plan {plan}* → *{g["name"]}*\n\nAb /{plan.lower()} se search karo — button automatically is group mein bhejega! 🚀',
            parse_mode='Markdown'
        )

    if data.startswith('ws_'):
        info = pending_send.get(data)
        if not info:
            return await q.edit_message_caption(caption='⚠️ Session expire ho gaya. Dobara search karo.', reply_markup=None)
        await q.edit_message_caption(caption=f'📤 Sending to {info["group_name"]}...', reply_markup=None)
        try:
            res = wa_send_image(info['group_id'], info['img_b64'], info['caption'])
            if not res.get('success'):
                raise Exception(res.get('error', 'Unknown'))
            del_id = f'wd_{uuid.uuid4().hex[:8]}'
            sent_wa[del_id] = {'key': res['key'], 'group_id': info['group_id']}
            threading.Timer(600, lambda: sent_wa.pop(del_id, None)).start()
            del pending_send[data]
            await q.edit_message_caption(
                caption=f'✅ Sent to *{info["group_name"]}!*',
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton('🗑️ Delete from WhatsApp', callback_data=del_id)
                ]])
            )
        except Exception as e:
            await q.edit_message_caption(
                caption=f'❌ Send fail: {e}',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton('🔄 Retry', callback_data=data)
                ]])
            )
        return

    if data.startswith('wd_'):
        info = sent_wa.get(data)
        if not info:
            return await q.edit_message_caption(caption='⚠️ Delete window expire ho gaya (10 min).', reply_markup=None)
        try:
            success = wa_delete(info['group_id'], info['key'])
            del sent_wa[data]
            if success:
                await q.edit_message_caption(caption='🗑️ *WhatsApp se delete ho gaya!*', parse_mode='Markdown', reply_markup=None)
            else:
                await q.edit_message_caption(caption='❌ Delete nahi hua.', reply_markup=None)
        except Exception as e:
            await q.edit_message_caption(caption=f'❌ Error: {e}', reply_markup=None)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in YOUR_USER_ID:
        await update.message.reply_text("⛔ Unauthorised.")
        return
    await update.message.reply_text(start_text(), parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in YOUR_USER_ID:
        await update.message.reply_text("⛔ Unauthorised.")
        return
    await update.message.reply_text(start_text(), parse_mode="Markdown")

async def cmd_plans(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in YOUR_USER_ID:
        await update.message.reply_text("⛔ Unauthorised.")
        return
    await update.message.reply_text(plans_text(), parse_mode="Markdown")

async def handle_direct_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Purane link-tracker bot wala feature — koi bhi link/keyword seedha
    bhejo (bina /a /b /c ke), saare tracked channels mein dhoondh ke batayega."""
    user_id = update.effective_user.id
    if user_id not in YOUR_USER_ID:
        return  # silently ignore unauthorised private messages

    text = (update.message.text or "").strip()
    if not text or text.startswith("/"):
        return

    cutoff = datetime.now(timezone.utc) - timedelta(hours=SEARCH_HOURS)
    known = {row[1].lower(): (row[2], row[3]) for row in db_get_known_channels() if row[1]}

    rows = await asyncio.get_event_loop().run_in_executor(
        None, lambda: db_search_any_channel(text, cutoff)
    )

    if not rows:
        await update.message.reply_text(
            f"❌ '{text}' kisi tracked channel mein nahi mila (last {SEARCH_HOURS}h).\n"
            "Check karo: bot us channel mein admin hai? Post is se pehle hi to nahi aaya?"
        )
        return

    results = []
    for chat_id, chat_title, username, message_id, msg_text, date_utc in rows:
        dt = datetime.fromisoformat(date_utc)
        link = f"https://t.me/{username}/{message_id}" if username else f"https://t.me/c/{abs(chat_id)}/{message_id}"
        _, photo_b64 = known.get((chat_title or "").lower(), (None, ""))
        results.append({
            "channel":   chat_title or "Unknown",
            "time":      to_ist(dt),
            "text":      msg_text,
            "link":      link,
            "photo_b64": photo_b64,
            "found":     True,
        })

    status = await update.message.reply_text(f"📸 {len(results)} channel(s) mein mila, screenshot bana raha hoon...")
    png_bytes = await make_screenshot(results, text, "*")
    caption = "\n".join(r["link"] for r in results)[:1020]
    img_b64 = base64.b64encode(png_bytes).decode()
    kb = build_all_group_buttons(img_b64, caption.strip()[:900])
    await update.message.reply_photo(photo=BytesIO(png_bytes), caption=caption[:900], reply_markup=kb)
    await status.delete()


async def cmd_a(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await plan_handler(update, context, "A")

async def cmd_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await plan_handler(update, context, "B")

async def cmd_c(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await plan_handler(update, context, "C")

# ── /addkeyword, /removekeyword, /keywords — manage AUTO_ALERT_KEYWORDS ────

async def cmd_addkeyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")
    if not context.args:
        return await update.message.reply_text(
            "⚠️ Usage: `/addkeyword loot fast`\n(ek command mein ek hi keyword/phrase)",
            parse_mode="Markdown"
        )
    kw = " ".join(context.args).strip()
    existing_lower = [k.lower() for k in AUTO_ALERT_KEYWORDS]
    if kw.lower() in existing_lower:
        return await update.message.reply_text(f"ℹ️ '{kw}' pehle se list mein hai.")
    AUTO_ALERT_KEYWORDS.append(kw)
    save_alert_keywords(AUTO_ALERT_KEYWORDS)
    await update.message.reply_text(f"✅ '{kw}' add ho gaya. Total keywords: {len(AUTO_ALERT_KEYWORDS)}")

async def cmd_removekeyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")
    if not context.args:
        return await update.message.reply_text(
            "⚠️ Usage: `/removekeyword loot fast`", parse_mode="Markdown"
        )
    kw = " ".join(context.args).strip().lower()
    match = next((k for k in AUTO_ALERT_KEYWORDS if k.lower() == kw), None)
    if not match:
        return await update.message.reply_text(f"❌ '{kw}' list mein nahi mila.")
    AUTO_ALERT_KEYWORDS.remove(match)
    save_alert_keywords(AUTO_ALERT_KEYWORDS)
    await update.message.reply_text(f"🗑️ '{match}' hata diya. Total keywords: {len(AUTO_ALERT_KEYWORDS)}")

async def cmd_keywords(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")
    if not AUTO_ALERT_KEYWORDS:
        return await update.message.reply_text("Koi keyword set nahi hai.")
    sorted_kw = sorted(AUTO_ALERT_KEYWORDS, key=str.lower)
    header = f"📋 *Auto-Alert Keywords ({len(sorted_kw)}):*\n\n"
    body = ", ".join(sorted_kw)
    # Telegram message limit ~4096 chars — chunks mein bhejo agar lamba ho
    chunk = header
    for item in sorted_kw:
        piece = item + ", "
        if len(chunk) + len(piece) > 3800:
            await update.message.reply_text(chunk.rstrip(", "), parse_mode="Markdown")
            chunk = ""
        chunk += piece
    if chunk.strip():
        await update.message.reply_text(chunk.rstrip(", "), parse_mode="Markdown")

async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in YOUR_USER_ID:
        await update.message.reply_text("⛔ Unauthorised.")
        return

    known = db_get_known_channels()
    all_names = [row[1] for row in known if row[1]]

    if not all_names:
        await update.message.reply_text(
            "📋 Bot ne abhi tak kisi channel se koi post nahi dekhi.\n\n"
            "Bot ko har channel mein *admin* banao, fir wahan koi naya message post hote hi "
            "yahan dikhega.",
            parse_mode="Markdown"
        )
        return

    joined_text = "\n".join(f"• `{n}`" for n in sorted(all_names))
    await update.message.reply_text(
        f"📋 *Channels bot has seen posts from ({len(all_names)}):*\n\n{joined_text}",
        parse_mode="Markdown"
    )

    for plan_name, plan_channels in PLANS.items():
        plan_lower  = {ch[0].lower() for ch in plan_channels}
        all_lower   = {n.lower(): n for n in all_names}
        matched     = [all_lower[n] for n in all_lower if n in plan_lower]
        not_matched = [ch[0] for ch in plan_channels if ch[0].lower() not in all_lower]
        msg = f"*Plan {plan_name} — {len(matched)}/{len(plan_channels)} matched:*\n"
        msg += "\n".join(f"✅ `{n}`" for n in matched)
        if not_matched:
            msg += "\n\n*Not seen yet (add bot as admin here, or fix spelling):*\n"
            msg += "\n".join(f"❌ `{n}`" for n in not_matched)
        await update.message.reply_text(msg, parse_mode="Markdown")

# ── Startup ───────────────────────────────────

async def main():
    global bot_instance
    missing = []
    if not BOT_TOKEN:      missing.append("BOT_TOKEN")
    if not YOUR_USER_ID:   missing.append("AUTHORIZED_USERS")
    if missing:
        print(f"❌ Please fill in: {', '.join(missing)}")
        return

    db_init()
    log.info("✅ Database ready at %s", DB_PATH)

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    bot_instance = app.bot

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("a",     cmd_a))
    app.add_handler(CommandHandler("b",     cmd_b))
    app.add_handler(CommandHandler("c",     cmd_c))
    app.add_handler(CommandHandler("debug",   cmd_debug))
    app.add_handler(CommandHandler("addkeyword",    cmd_addkeyword))
    app.add_handler(CommandHandler("removekeyword", cmd_removekeyword))
    app.add_handler(CommandHandler("keywords",      cmd_keywords))
    app.add_handler(CommandHandler("wagroup",  cmd_wagroup))
    app.add_handler(CommandHandler("setgroup", cmd_setgroup))
    app.add_handler(CallbackQueryHandler(handle_callback))
    # This is the key piece — listens for new posts in any channel the bot is admin of
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST & filters.TEXT, on_channel_post))
    # Merged from the old link-tracker bot — paste any link/keyword directly in private chat
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_direct_search))

    # ── Optional hybrid Telethon listener ──
    telethon_client = None
    if TELETHON_AVAILABLE and TELETHON_API_ID and TELETHON_API_HASH and TELETHON_PHONE:
        try:
            telethon_client = TelegramClient(TELETHON_SESSION_PATH, int(TELETHON_API_ID), TELETHON_API_HASH)
            register_telethon_handlers(telethon_client)
        except Exception as e:
            log.error(f"Telethon setup failed, chal raha hai bina hybrid listener ke: {e}")
            telethon_client = None
    else:
        log.info("ℹ️ Telethon hybrid listener disabled (TELETHON_API_ID/HASH/PHONE set nahi hain).")

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        log.info("✅ Bot running! Send /start to your bot.")

        if telethon_client:
            await telethon_client.start(phone=TELETHON_PHONE)
            log.info("✅ Telethon hybrid listener running.")

        try:
            if telethon_client:
                await telethon_client.run_until_disconnected()
            else:
                await asyncio.Event().wait()  # bas zinda rakho jab tak koi stop na kare
        finally:
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
