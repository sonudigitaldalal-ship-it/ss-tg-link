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
    from telethon.errors import SessionPasswordNeededError
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
alerted_links = set()          # keyword-mode ke liye — links jinke liye already alert ja chuka hai
IST          = timezone(timedelta(hours=5, minutes=30))
PLANS        = {"A": PLAN_A, "B": PLAN_B, "C": PLAN_C}

# ─────────────────────────────────────────────
#  Auto-Alert MODE — do modes, ek time pe sirf ek active
#  "plan"    → keyword ek POORE PLAN ke saare channels mein aana chahiye
#  "keyword" → SAME LINK kam se kam AUTO_ALERT_MIN_CHANNELS_LINK channels
#              mein post hona chahiye (plan se independent)
#  /setmode plan  ya  /setmode keyword  se switch karo, /mode se current dekho
# ─────────────────────────────────────────────
AUTO_ALERT_MIN_CHANNELS_LINK = 2
MODE_FILE = os.environ.get("MODE_FILE", "/data/alert_mode.txt")
URL_REGEX = re.compile(r"https?://\S+")

def load_alert_mode():
    try:
        if os.path.exists(MODE_FILE):
            with open(MODE_FILE) as f:
                m = f.read().strip()
                if m in ("plan", "keyword"):
                    return m
    except Exception as e:
        log.error(f"load_alert_mode: {e}")
    return "plan"

def save_alert_mode(mode):
    try:
        os.makedirs(os.path.dirname(MODE_FILE), exist_ok=True)
        with open(MODE_FILE, "w") as f:
            f.write(mode)
    except Exception as e:
        log.error(f"save_alert_mode: {e}")

AUTO_ALERT_MODE = load_alert_mode()

# ─────────────────────────────────────────────
#  BRAND → WhatsApp Group mapping (Telegram se hi manage hota hai)
#  /setbrandgroup <brand> — group select karke set karo
#  /brandgroups — current mappings dekho
#  /removebrandgroup <brand> — hatao
# ─────────────────────────────────────────────
BRAND_GROUPS_FILE = os.environ.get("BRAND_GROUPS_FILE", "/data/brand_groups.json")

def load_brand_groups():
    import json
    try:
        if os.path.exists(BRAND_GROUPS_FILE):
            with open(BRAND_GROUPS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        log.error(f"load_brand_groups: {e}")
    return {}

def save_brand_groups(data):
    import json
    try:
        os.makedirs(os.path.dirname(BRAND_GROUPS_FILE), exist_ok=True)
        with open(BRAND_GROUPS_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.error(f"save_brand_groups: {e}")

BRAND_GROUPS = load_brand_groups()  # { "orient": {"id": "12345@g.us", "name": "Orient Deals Group"}, ... }

def find_brand_for_keyword(keyword: str):
    """Keyword ke andar koi known brand-word ho toh (brand, group_dict) return karo."""
    kw_lower = keyword.lower()
    for brand, group in BRAND_GROUPS.items():
        if brand in kw_lower:
            return brand, group
    return None, None

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

def get_known_channels_map():
    """{title_lower: (username, photo_b64)} banata hai — agar (purane bug se bache) duplicate
    title wale rows ho bhi, toh jisme photo hai wahi priority leta hai."""
    result = {}
    for chat_id, title, username, photo in db_get_known_channels():
        if not title:
            continue
        key = title.lower()
        if key not in result or (photo and not result[key][1]):
            result[key] = (username, photo)
    return result

DATA_RETENTION_DAYS = 15  # isse purane messages auto-delete ho jate hain (DB chhoti aur fast rehti hai)

def db_cleanup_old_data(days: int = DATA_RETENTION_DAYS) -> int:
    """DATA_RETENTION_DAYS se purane messages delete karta hai. Deleted rows count return karta hai."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("DELETE FROM messages WHERE date_utc < ?", (cutoff.isoformat(),))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


def db_dedupe_channels() -> int:
    """PURANI wale bug (Bot API + Telethon alag chat_id format) se bane duplicate
    channel entries ko merge karta hai — same title wale channels ko ek chat_id
    mein consolidate karta hai (jisme photo hai use canonical rakhta hai)."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT chat_id, chat_title, photo_b64 FROM channels").fetchall()

    by_title = {}
    for chat_id, title, photo in rows:
        key = (title or "").lower()
        if not key:
            continue
        by_title.setdefault(key, []).append((chat_id, photo))

    merged = 0
    for key, entries in by_title.items():
        if len(entries) <= 1:
            continue
        canonical = next((e for e in entries if e[1]), entries[0])
        canonical_id = canonical[0]
        canonical_photo = canonical[1]

        for chat_id, photo in entries:
            if chat_id == canonical_id:
                continue
            # Is duplicate channel ke messages canonical id mein migrate karo
            # (agar wahi message_id canonical mein already hai toh IGNORE ho jayega)
            conn.execute("UPDATE OR IGNORE messages SET chat_id=? WHERE chat_id=?", (canonical_id, chat_id))
            conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))  # baaki bacha hua hata do
            conn.execute("DELETE FROM channels WHERE chat_id=?", (chat_id,))
            if not canonical_photo and photo:
                conn.execute("UPDATE channels SET photo_b64=? WHERE chat_id=?", (photo, canonical_id))
                canonical_photo = photo
            merged += 1

    conn.commit()
    conn.close()
    return merged


async def cleanup_loop():
    """Roz ek baar chalta hai — 15+ din purana data DB se hata deta hai."""
    while True:
        await asyncio.sleep(24 * 3600)  # pehli baar 24hr baad (startup ke turant baad zaroorat nahi)
        try:
            deleted = await asyncio.get_event_loop().run_in_executor(None, db_cleanup_old_data)
            log.info(f"🧹 Auto-cleanup: {deleted} purane messages ({DATA_RETENTION_DAYS}+ din) delete kiye.")
        except Exception as e:
            log.error(f"Cleanup loop error: {e}")


async def telethon_health_check_loop():
    """Har 5 min mein Telethon session check karta hai — agar logout/disconnect ho jaye
    (jab pehle authorized tha), Telegram pe alert bhej deta hai."""
    was_authorized = None
    while True:
        await asyncio.sleep(300)
        if not telethon_client:
            continue
        try:
            authorized = telethon_client.is_connected() and await telethon_client.is_user_authorized()
        except Exception:
            authorized = False

        if was_authorized is True and authorized is False:
            for uid in YOUR_USER_ID:
                try:
                    await bot_instance.send_message(
                        chat_id=uid,
                        text="⚠️ *Telethon (Telegram hybrid listener) disconnect/logout ho gaya hai!*\n"
                             "Purane channels ka data ana ruk gaya hoga. Dobara connect karne ke liye:\n"
                             "/telethonlogin",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        was_authorized = authorized


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

def wa_get_qr_status():
    """WA bridge se poochta hai: already logged in hai, ya QR chahiye (aur QR bytes)."""
    if not WA_API_URL or not WA_API_KEY:
        return {'ready': False, 'qr_base64': None, 'error': 'WA_API_URL/WA_API_KEY set nahi hain'}
    try:
        r = http_requests.get(f'{WA_API_URL}/qr-image', headers=wa_headers(), timeout=10)
        return r.json()
    except Exception as e:
        return {'ready': False, 'qr_base64': None, 'error': str(e)}

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
telethon_client = None       # set in main() — Telethon client (login OTP-driven via bot commands)
telethon_phone_code_hash = None  # /telethonlogin ke baad OTP verify karne ke liye chahiye

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

def telethon_to_bot_chat_id(entity) -> int:
    """Telethon ka bare channel ID Bot-API-style (-100 prefixed) mein convert karta hai —
    taaki wahi channel Bot API se bhi track ho raha ho toh database mein DUPLICATE entry
    na bane (ek hi channel ke liye ek hi chat_id use ho, chahe kisi bhi listener se aaya ho)."""
    is_channel = getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False)
    raw_id = getattr(entity, "id", entity)
    if is_channel:
        return int(f"-100{raw_id}")
    return raw_id


async def telethon_refresh_photo(client, entity, db_chat_id: int, chat_title: str):
    known = {row[0]: row[3] for row in db_get_known_channels()}
    if known.get(db_chat_id):
        return
    try:
        data = await client.download_profile_photo(entity, file=bytes)
        if data:
            b64 = "data:image/jpeg;base64," + base64.b64encode(data).decode()
            db_update_photo(db_chat_id, b64)
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
            db_chat_id = telethon_to_bot_chat_id(chat)

            db_save_message(db_chat_id, title, username or "", event.message.id, event.message.text, event.message.date)
            asyncio.create_task(telethon_refresh_photo(client, chat, db_chat_id, title))

            dispatch_auto_alert(event.message.text)
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
    known = get_known_channels_map()
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

            # Brand-specific group mein bhi auto-send karo agar keyword kisi brand se match kare
            brand, brand_grp = find_brand_for_keyword(keyword)
            if brand and brand_grp and WA_API_URL:
                brand_res = wa_send_image(brand_grp['id'], img_b64, caption.strip()[:900])
                if brand_res.get('success'):
                    brand_del_id = f'wd_{uuid.uuid4().hex[:8]}'
                    sent_wa[brand_del_id] = {'key': brand_res['key'], 'group_id': brand_grp['id']}
                    threading.Timer(600, lambda: sent_wa.pop(brand_del_id, None)).start()
                    brand_kb = InlineKeyboardMarkup([[
                        InlineKeyboardButton('🗑️ Delete from WhatsApp', callback_data=brand_del_id)
                    ]])
                    for uid in YOUR_USER_ID:
                        await bot_instance.send_message(
                            chat_id=uid,
                            text=f"✅ *Brand match!* '{keyword}' → *{brand_grp['name']}* mein bhi auto-sent!",
                            parse_mode="Markdown", reply_markup=brand_kb,
                        )
                else:
                    log.warning(f"Brand auto-send failed for {brand}: {brand_res.get('error')}")
        except Exception as e:
            log.error(f"Plan auto-alert failed for Plan {plan_name}: {e}", exc_info=True)


async def check_link_multi_channel(link: str):
    """KEYWORD MODE: agar ye link kam se kam AUTO_ALERT_MIN_CHANNELS_LINK
    channels mein mil chuka hai (last AUTO_ALERT_WINDOW_MINUTES mein),
    saare authorized users ko screenshot bhej do. Plan se independent —
    saare known channels ke across kaam karta hai."""
    if link in alerted_links:
        return

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=AUTO_ALERT_WINDOW_MINUTES)
    rows = await asyncio.get_event_loop().run_in_executor(
        None, lambda: db_search_any_channel(link, cutoff)
    )
    if len(rows) < AUTO_ALERT_MIN_CHANNELS_LINK:
        return

    alerted_links.add(link)

    known = get_known_channels_map()
    results = []
    for chat_id, chat_title, username, message_id, msg_text, date_utc in rows:
        dt = datetime.fromisoformat(date_utc)
        post_link = f"https://t.me/{username}/{message_id}" if username else f"https://t.me/c/{abs(chat_id)}/{message_id}"
        _, photo_b64 = known.get((chat_title or "").lower(), (None, ""))
        results.append({
            "channel": chat_title or "Unknown", "time": to_ist(dt),
            "text": msg_text, "link": post_link, "photo_b64": photo_b64, "found": True,
        })

    try:
        png_bytes = await make_screenshot(results, link, "🔗")
        caption = (f"🔗 *Same link {len(results)} channels mein mila!*\n\n" +
                   "\n".join(r["link"] for r in results))[:1020]
        img_b64 = base64.b64encode(png_bytes).decode()
        kb = build_all_group_buttons(img_b64, caption.strip()[:900])
        for uid in YOUR_USER_ID:
            await bot_instance.send_photo(
                chat_id=uid, photo=BytesIO(png_bytes),
                caption=caption[:1020], parse_mode="Markdown", reply_markup=kb,
            )

        # Keyword-mode mein bhi brand-detection + brand-group auto-send —
        # yahan koi ek "keyword" nahi hota, isliye post ke actual text mein
        # brand-word dhoondte hain.
        combined_text = " ".join(r.get("text", "") for r in results)
        brand, brand_grp = find_brand_for_keyword(combined_text)
        if brand and brand_grp and WA_API_URL:
            brand_res = wa_send_image(brand_grp['id'], img_b64, caption.strip()[:900])
            if brand_res.get('success'):
                brand_del_id = f'wd_{uuid.uuid4().hex[:8]}'
                sent_wa[brand_del_id] = {'key': brand_res['key'], 'group_id': brand_grp['id']}
                threading.Timer(600, lambda: sent_wa.pop(brand_del_id, None)).start()
                brand_kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton('🗑️ Delete from WhatsApp', callback_data=brand_del_id)
                ]])
                for uid in YOUR_USER_ID:
                    await bot_instance.send_message(
                        chat_id=uid,
                        text=f"✅ *Brand match!* → *{brand_grp['name']}* mein bhi auto-sent!",
                        parse_mode="Markdown", reply_markup=brand_kb,
                    )
            else:
                log.warning(f"Brand auto-send failed for {brand}: {brand_res.get('error')}")
    except Exception as e:
        log.error(f"Link-mode auto-alert failed: {e}", exc_info=True)


def dispatch_auto_alert(text: str):
    """Current AUTO_ALERT_MODE ke hisaab se sahi checker ko trigger karta hai."""
    if AUTO_ALERT_MODE == "plan":
        text_lower = text.lower()
        matched = [kw for kw in AUTO_ALERT_KEYWORDS if kw.lower() in text_lower]
        for kw in matched:
            asyncio.create_task(check_plan_full_coverage(kw))
    else:  # "keyword" mode — link-based
        urls = URL_REGEX.findall(text)
        if urls:
            asyncio.create_task(check_link_multi_channel(urls[0]))

async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg or not msg.text:
        return
    chat = msg.chat
    db_save_message(chat.id, chat.title or "", chat.username or "", msg.message_id, msg.text, msg.date)
    asyncio.create_task(refresh_photo_if_needed(chat.id, chat.title or ""))

    dispatch_auto_alert(msg.text)

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
    known = get_known_channels_map()

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
        "🔑 /telethonlogin — Hybrid listener login shuru karo (PC ki zaroorat nahi)\n"
        "📱 /qr — WhatsApp login status check karo / QR lo\n"
        "⏱ /olddeal loot 15/8 7:00pm — Purani history search (Telethon chahiye)\n"
        "🔄 /backfill [din] — Pichla data DB mein fetch karo (default 3 din)\n"
        "📊 /telethonchannels — Kitne channels/groups mein Telethon member hai\n"
        "🔀 /setmode plan|keyword — Auto-alert mode badlo\n"
        "📍 /mode — Current auto-alert mode dekho\n"
        "🏷️ /setbrandgroup orient — Brand ko WhatsApp group se map karo\n"
        "📋 /brandgroups — Saare brand-group mappings dekho\n"
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

    brand, brand_grp = find_brand_for_keyword(keyword)
    if brand and brand_grp and WA_API_URL:
        cb_id2 = f'ws_{uuid.uuid4().hex[:8]}'
        pending_send[cb_id2] = {
            'img_b64': img_b64, 'caption': caption,
            'group_id': brand_grp['id'], 'group_name': brand_grp['name'],
        }
        threading.Timer(1800, lambda: pending_send.pop(cb_id2, None)).start()
        rows.append([InlineKeyboardButton(f'📤 Send to {brand.capitalize()} ({brand_grp["name"]})', callback_data=cb_id2)])

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

# ── /setbrandgroup, /brandgroups, /removebrandgroup — brand→WA group mapping ──

async def cmd_setbrandgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in YOUR_USER_ID:
        return await update.message.reply_text('⛔ Unauthorised.')
    if not WA_API_URL:
        return await update.message.reply_text('❌ WA_API_URL set nahi hai.')
    if not context.args:
        return await update.message.reply_text(
            '⚠️ Usage: `/setbrandgroup orient`\n(brand ka naam do, phir group select karoge)',
            parse_mode='Markdown'
        )

    brand = " ".join(context.args).strip().lower()
    msg = await update.message.reply_text(f'🔄 "{brand}" ke liye groups load ho rahe hain...')
    groups = wa_get_groups()
    if not groups:
        return await msg.edit_text('❌ Groups nahi mile. WA API connected hai?')

    kb = [[InlineKeyboardButton(f'💬 {g["name"]}', callback_data=f'bg_{brand}_{i}')]
          for i, g in enumerate(groups[:25])]
    context.user_data['wa_groups'] = groups
    await msg.edit_text(
        f'📋 *"{brand}"* keyword ke liye group select karo:',
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def cmd_brandgroups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in YOUR_USER_ID:
        return await update.message.reply_text('⛔ Unauthorised.')
    if not BRAND_GROUPS:
        return await update.message.reply_text(
            'Koi brand-group mapping set nahi hai.\nUsage: `/setbrandgroup orient`',
            parse_mode='Markdown'
        )
    lines = [f'• *{b}* → {g["name"]}' for b, g in sorted(BRAND_GROUPS.items())]
    await update.message.reply_text(
        f'📋 *Brand → WhatsApp Group mappings ({len(BRAND_GROUPS)}):*\n\n' + '\n'.join(lines),
        parse_mode='Markdown'
    )

async def cmd_removebrandgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in YOUR_USER_ID:
        return await update.message.reply_text('⛔ Unauthorised.')
    if not context.args:
        return await update.message.reply_text('Usage: `/removebrandgroup orient`', parse_mode='Markdown')
    brand = " ".join(context.args).strip().lower()
    if brand not in BRAND_GROUPS:
        return await update.message.reply_text(f'❌ "{brand}" ke liye koi mapping set nahi hai.')
    del BRAND_GROUPS[brand]
    save_brand_groups(BRAND_GROUPS)
    await update.message.reply_text(f'🗑️ "{brand}" ka mapping hata diya.')

# ── /qr — WhatsApp login status/QR check karta hai ────────

async def cmd_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")
    if not WA_API_URL:
        return await update.message.reply_text('❌ WA_API_URL env var set nahi hai.')

    status = await update.message.reply_text('🔄 WhatsApp status check kar raha hoon...')
    result = wa_get_qr_status()

    if result.get('error'):
        return await status.edit_text(f"⚠️ Error: {result['error']}")

    if result.get('ready'):
        return await status.edit_text('✅ WhatsApp already login hai — QR ki zaroorat nahi!')

    qr_b64 = result.get('qr_base64')
    if not qr_b64:
        return await status.edit_text('⏳ QR abhi generate ho raha hai, thodi der mein /qr dobara try karo.')

    await status.delete()
    qr_bytes = base64.b64decode(qr_b64)
    await update.message.reply_photo(
        photo=BytesIO(qr_bytes),
        caption="📱 WhatsApp se scan karo:\nSettings → Linked Devices → Link a Device"
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

    if data.startswith('bg_'):
        rest = data[3:]
        brand, idx_str = rest.rsplit('_', 1)
        idx = int(idx_str)
        groups = context.user_data.get('wa_groups', [])
        if idx >= len(groups):
            return await q.edit_message_text('❌ /setbrandgroup dobara try karo.')
        g = groups[idx]
        BRAND_GROUPS[brand] = {'id': g['id'], 'name': g['name']}
        save_brand_groups(BRAND_GROUPS)
        return await q.edit_message_text(
            f'✅ *"{brand}"* → *{g["name"]}*\n\nAb jab bhi "{brand}" match hoga, is group mein bhi auto-send hoga! 🚀',
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

# ── /olddeal — purani history search (Telethon se, live Telegram history) ──

OLD_SEARCH_WINDOW_MINUTES = 30  # target time ke ± kitne minute dekhna hai

def parse_olddeal_args(args_text: str):
    """'loot 15/8 7:00pm' jaisa text parse karke (keyword, target_datetime_IST) return karta hai."""
    date_match = re.search(r'(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?', args_text)
    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', args_text, re.IGNORECASE)
    if not date_match or not time_match:
        return None, None

    day, month = int(date_match.group(1)), int(date_match.group(2))
    year = date_match.group(3)
    year = int(year) if year else datetime.now(IST).year
    if year < 100:
        year += 2000

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    ampm = time_match.group(3).lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0

    try:
        target = datetime(year, month, day, hour, minute, tzinfo=IST)
    except ValueError:
        return None, None

    keyword = args_text[:date_match.start()].strip()
    return (keyword or None), target


async def cmd_olddeal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")

    if not telethon_client or not (await telethon_client.is_user_authorized()):
        return await update.message.reply_text(
            "❌ Ye feature Telethon hybrid login maangta hai (purani history sirf usi se milti hai).\n"
            "Pehle /telethonlogin karo."
        )

    args_text = " ".join(context.args) if context.args else ""
    keyword, target = parse_olddeal_args(args_text)
    if not keyword or not target:
        return await update.message.reply_text(
            "⚠️ *Usage:*\n`/olddeal loot 15/8 7:00pm`\n\n"
            "Format: `<keyword> <DD/MM> <H:MMam/pm>`\n"
            f"(target time ke ±{OLD_SEARCH_WINDOW_MINUTES} min ke andar jo bhi post ho wo dhoondega)",
            parse_mode="Markdown"
        )

    status = await update.message.reply_text(
        f"🔍 '{keyword}' ko {target.strftime('%d %b %Y, %I:%M %p')} IST ke aas-paas dhoondh raha hoon "
        f"(Telegram history se, thoda time lagega)..."
    )

    window_start = (target - timedelta(minutes=OLD_SEARCH_WINDOW_MINUTES)).astimezone(timezone.utc)
    window_end   = (target + timedelta(minutes=OLD_SEARCH_WINDOW_MINUTES)).astimezone(timezone.utc)

    # Saare unique channels (Plan A+B+C mila ke, duplicate hata ke)
    seen_names = set()
    all_channels = []
    for plan_channels in PLANS.values():
        for ch_name, ch_link in plan_channels:
            if ch_name.lower() not in seen_names:
                seen_names.add(ch_name.lower())
                all_channels.append(ch_name)

    try:
        dialogs = await telethon_client.get_dialogs()
        dialog_map = {d.name.lower(): d.entity for d in dialogs if d.name}
    except Exception as e:
        return await status.edit_text(f"⚠️ Telegram dialogs fetch karne mein error: {e}")

    known_photos_map = get_known_channels_map()

    results = []
    for ch_name in all_channels:
        entity = dialog_map.get(ch_name.lower())
        if not entity:
            continue  # ye account is channel mein member nahi hai
        try:
            async for msg in telethon_client.iter_messages(entity, offset_date=window_end, reverse=False, limit=200):
                if msg.date < window_start:
                    break  # itna purana pahunch gaye, ab is channel mein aage dhoondhna bekar hai
                if msg.date > window_end:
                    continue
                if not msg.text or keyword.lower() not in msg.text.lower():
                    continue
                username = getattr(entity, "username", None)
                post_link = f"https://t.me/{username}/{msg.id}" if username else f"https://t.me/c/{abs(entity.id)}/{msg.id}"

                # Channel ka photo — pehle cache se, nahi to seedha Telethon se fetch karo
                _, photo_b64 = known_photos_map.get(ch_name.lower(), (None, ""))
                if not photo_b64:
                    try:
                        photo_bytes = await telethon_client.download_profile_photo(entity, file=bytes)
                        if photo_bytes:
                            photo_b64 = "data:image/jpeg;base64," + base64.b64encode(photo_bytes).decode()
                            db_update_photo(telethon_to_bot_chat_id(entity), photo_b64)
                            known_photos_map[ch_name.lower()] = (username, photo_b64)
                    except Exception as e:
                        log.warning(f"olddeal photo fetch failed for {ch_name}: {e}")

                results.append({
                    "channel": ch_name, "time": to_ist(msg.date), "text": msg.text,
                    "link": post_link, "photo_b64": photo_b64, "found": True,
                })
                break  # is channel ka pehla (sabse relevant) match kaafi hai
        except Exception as e:
            log.warning(f"olddeal search failed for {ch_name}: {e}")

    if not results:
        return await status.edit_text(
            f"❌ '{keyword}' {target.strftime('%d %b, %I:%M %p')} ke aas-paas kahin nahi mila."
        )

    png_bytes = await make_screenshot(results, keyword, "⏱")
    caption = (f"⏱ *'{keyword}' — {target.strftime('%d %b %Y, %I:%M %p')} IST ke aas-paas "
               f"({len(results)} channel mein mila):*\n\n" +
               "\n".join(r["link"] for r in results))[:1020]
    img_b64 = base64.b64encode(png_bytes).decode()
    kb = build_all_group_buttons(img_b64, caption.strip()[:900])
    await update.message.reply_photo(photo=BytesIO(png_bytes), caption=caption[:1020], parse_mode="Markdown", reply_markup=kb)
    await status.delete()


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
    known = get_known_channels_map()

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

# ── Telethon login via bot commands (no PC/terminal needed) ──────────────

async def run_backfill(chat_id_for_updates: int, days: int = 3):
    """Pichle N din ka history fetch karke DB mein daal deta hai — sirf
    channels/groups (private chats skip), taaki /a /b /c isse bhi kaam kare."""
    if not telethon_client or not (await telethon_client.is_user_authorized()):
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        dialogs = await telethon_client.get_dialogs()
    except Exception as e:
        log.error(f"Backfill: get_dialogs fail: {e}")
        return

    channels_done = 0
    messages_saved = 0
    for d in dialogs:
        if not d.name or not (d.is_channel or d.is_group):
            continue
        entity = d.entity
        db_chat_id = telethon_to_bot_chat_id(entity)
        try:
            async for msg in telethon_client.iter_messages(entity, offset_date=None, reverse=False, limit=500):
                if msg.date < cutoff:
                    break
                if not msg.text:
                    continue
                username = getattr(entity, "username", None)
                db_save_message(db_chat_id, d.name, username or "", msg.id, msg.text, msg.date)
                messages_saved += 1
        except Exception as e:
            log.warning(f"Backfill failed for {d.name}: {e}")
            continue
        channels_done += 1

    try:
        await bot_instance.send_message(
            chat_id=chat_id_for_updates,
            text=f"✅ Backfill complete! {channels_done} channels/groups se {messages_saved} messages "
                 f"(pichle {days} din) database mein aa gaye. Ab /a /b /c inhe bhi search kar payega."
        )
    except Exception:
        pass


async def cmd_cleanupduplicates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")
    status = await update.message.reply_text("🔄 Duplicate channel entries dhoondh raha hoon...")
    merged = await asyncio.get_event_loop().run_in_executor(None, db_dedupe_channels)
    if merged == 0:
        await status.edit_text("✅ Koi duplicate nahi mila — database already clean hai.")
    else:
        await status.edit_text(f"✅ {merged} duplicate channel entries merge kar diye. Ab photos aur counts sahi aayenge.")


async def cmd_backfill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")
    if not telethon_client or not (await telethon_client.is_user_authorized()):
        return await update.message.reply_text("❌ Pehle /telethonlogin karo.")
    days = 3
    if context.args and context.args[0].isdigit():
        days = int(context.args[0])
    await update.message.reply_text(
        f"🔄 Pichle {days} din ka history fetch ho raha hai (background mein) — "
        f"jitne zyada channels/groups honge utna time lagega. Poora hone par message aayega."
    )
    asyncio.create_task(run_backfill(update.effective_chat.id, days))


async def cmd_setmode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTO_ALERT_MODE
    if update.effective_user.id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")
    if not context.args or context.args[0].lower() not in ("plan", "keyword"):
        return await update.message.reply_text(
            "⚠️ Usage: `/setmode plan` ya `/setmode keyword`\n\n"
            "*plan* — keyword poore Plan (A/B/C) ke saare channels mein aana chahiye\n"
            "*keyword* — same LINK kam se kam "
            f"{AUTO_ALERT_MIN_CHANNELS_LINK} channels mein post hona chahiye",
            parse_mode="Markdown"
        )
    AUTO_ALERT_MODE = context.args[0].lower()
    save_alert_mode(AUTO_ALERT_MODE)
    await update.message.reply_text(f"✅ Auto-Alert mode ab *{AUTO_ALERT_MODE}* hai.", parse_mode="Markdown")

async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")
    desc = ("Plan ke saare channels mein keyword aana chahiye" if AUTO_ALERT_MODE == "plan"
            else f"Same link kam se kam {AUTO_ALERT_MIN_CHANNELS_LINK} channels mein aana chahiye")
    await update.message.reply_text(f"📍 Current mode: *{AUTO_ALERT_MODE}*\n({desc})", parse_mode="Markdown")


async def cmd_telethonchannels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Telethon account jitne channels/groups mein member hai, unka count + list dikhata hai."""
    user_id = update.effective_user.id
    if user_id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")
    if not telethon_client or not (await telethon_client.is_user_authorized()):
        return await update.message.reply_text("❌ Pehle /telethonlogin karo.")

    status = await update.message.reply_text("🔄 List fetch kar raha hoon...")
    try:
        dialogs = await telethon_client.get_dialogs()
    except Exception as e:
        return await status.edit_text(f"⚠️ Error: {e}")

    channels = [d for d in dialogs if d.name and d.is_channel and not d.is_group]
    groups   = [d for d in dialogs if d.name and d.is_group]
    total = len(channels) + len(groups)

    header = f"📊 *Telethon Account — Total {total} joined ({len(channels)} channels, {len(groups)} groups):*\n\n"
    names = sorted([d.name for d in channels] + [d.name for d in groups], key=str.lower)

    chunk = header
    for name in names:
        piece = f"• {name}\n"
        if len(chunk) + len(piece) > 3800:
            await update.message.reply_text(chunk, parse_mode="Markdown")
            chunk = ""
        chunk += piece
    if chunk.strip():
        await update.message.reply_text(chunk, parse_mode="Markdown")
    await status.delete()


async def cmd_telethonlogin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global telethon_phone_code_hash
    if update.effective_user.id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")
    if not telethon_client:
        return await update.message.reply_text(
            "❌ TELETHON_API_ID / TELETHON_API_HASH / TELETHON_PHONE Railway Variables mein set nahi hain."
        )
    if telethon_client.is_connected() and await telethon_client.is_user_authorized():
        return await update.message.reply_text("✅ Telethon already logged in hai!")
    try:
        if not telethon_client.is_connected():
            await telethon_client.connect()
        result = await telethon_client.send_code_request(TELETHON_PHONE)
        telethon_phone_code_hash = result.phone_code_hash
        await update.message.reply_text(
            "📱 Ek OTP tumhare Telegram app pe aaya hoga — *Telegram* ke apne official "
            "'service message' se (is bot se nahi, apne saved messages/notifications check karo).\n\n"
            "Wahi code yahan bhejo:\n`/telethoncode 12345`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def cmd_telethoncode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")
    if not telethon_client:
        return await update.message.reply_text("❌ Telethon configured nahi hai.")
    if not context.args:
        return await update.message.reply_text("Usage: `/telethoncode 12345`", parse_mode="Markdown")
    code = context.args[0].strip()
    try:
        await telethon_client.sign_in(phone=TELETHON_PHONE, code=code, phone_code_hash=telethon_phone_code_hash)
        register_telethon_handlers(telethon_client)
        asyncio.create_task(telethon_client.run_until_disconnected())
        await update.message.reply_text(
            "✅ Telethon login successful! Hybrid listener ab chal raha hai — kisi PC ki zaroorat nahi padi 🎉\n\n"
            "🔄 Pichle 3 din ka data bhi background mein fetch ho raha hai, thodi der mein message aayega."
        )
        asyncio.create_task(run_backfill(update.effective_chat.id, days=3))
    except SessionPasswordNeededError:
        await update.message.reply_text(
            "🔒 Tumhare account mein 2-Step Verification ON hai. Apna password bhejo:\n"
            "`/telethonpassword tumhara_password`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}\n\nDobara try karo: /telethonlogin")

async def cmd_telethonpassword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in YOUR_USER_ID:
        return await update.message.reply_text("⛔ Unauthorised.")
    if not telethon_client:
        return await update.message.reply_text("❌ Telethon configured nahi hai.")
    if not context.args:
        return await update.message.reply_text("Usage: `/telethonpassword tumhara_password`", parse_mode="Markdown")
    pw = " ".join(context.args)
    try:
        await telethon_client.sign_in(password=pw)
        register_telethon_handlers(telethon_client)
        asyncio.create_task(telethon_client.run_until_disconnected())
        await update.message.reply_text(
            "✅ Telethon login successful (2FA)! Hybrid listener ab chal raha hai 🎉\n\n"
            "🔄 Pichle 3 din ka data bhi background mein fetch ho raha hai, thodi der mein message aayega."
        )
        asyncio.create_task(run_backfill(update.effective_chat.id, days=3))
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

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
    global bot_instance, telethon_client
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
    app.add_handler(CommandHandler("qr",       cmd_qr))
    app.add_handler(CommandHandler("setgroup", cmd_setgroup))
    app.add_handler(CommandHandler("setbrandgroup",    cmd_setbrandgroup))
    app.add_handler(CommandHandler("brandgroups",      cmd_brandgroups))
    app.add_handler(CommandHandler("removebrandgroup", cmd_removebrandgroup))
    app.add_handler(CommandHandler("telethonlogin",    cmd_telethonlogin))
    app.add_handler(CommandHandler("telethoncode",     cmd_telethoncode))
    app.add_handler(CommandHandler("telethonpassword", cmd_telethonpassword))
    app.add_handler(CommandHandler("olddeal", cmd_olddeal))
    app.add_handler(CommandHandler("backfill", cmd_backfill))
    app.add_handler(CommandHandler("cleanupduplicates", cmd_cleanupduplicates))
    app.add_handler(CommandHandler("telethonchannels", cmd_telethonchannels))
    app.add_handler(CommandHandler("setmode", cmd_setmode))
    app.add_handler(CommandHandler("mode",    cmd_mode))
    app.add_handler(CallbackQueryHandler(handle_callback))
    # Bot-API channel_post listener HATA diya — ab poori tarah Telethon hybrid listener
    # hi saare channels track karta hai (duplicate-channel-ID bug ka permanent fix,
    # aur admin banane ki zaroorat bhi nahi rahi, sirf member hona kaafi hai)
    # Merged from the old link-tracker bot — paste any link/keyword directly in private chat
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_direct_search))

    # ── Optional hybrid Telethon listener — login OTP-driven via bot commands ──
    if TELETHON_AVAILABLE and TELETHON_API_ID and TELETHON_API_HASH and TELETHON_PHONE:
        try:
            telethon_client = TelegramClient(TELETHON_SESSION_PATH, int(TELETHON_API_ID), TELETHON_API_HASH)
        except Exception as e:
            log.error(f"Telethon setup failed, chal raha hai bina hybrid listener ke: {e}")
            telethon_client = None
    else:
        log.info("ℹ️ Telethon hybrid listener disabled (TELETHON_API_ID/HASH/PHONE set nahi hain).")

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        log.info("✅ Bot running! Send /start to your bot. Channel-post listener active.")
        asyncio.create_task(cleanup_loop())
        asyncio.create_task(telethon_health_check_loop())

        if telethon_client:
            try:
                await telethon_client.connect()
                if await telethon_client.is_user_authorized():
                    # Pehle se hi login ho chuka hai (session save hai) — seedha shuru ho jao
                    register_telethon_handlers(telethon_client)
                    asyncio.create_task(telethon_client.run_until_disconnected())
                    log.info("✅ Telethon hybrid listener running (existing session).")
                else:
                    log.info("ℹ️ Telethon connected but not logged in. Send /telethonlogin to your bot to authorize.")
            except Exception as e:
                # Zaroori: Telethon mein koi bhi dikkat aaye, poora bot (Bot API listener bhi)
                # crash nahi hona chahiye. Isliye yahan catch karke sirf Telethon skip karte hain.
                log.error(f"⚠️ Telethon connect/start fail hua, Bot API listener normal chalta rahega: {e}", exc_info=True)

        try:
            await asyncio.Event().wait()  # bas zinda rakho jab tak koi stop na kare
        finally:
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
