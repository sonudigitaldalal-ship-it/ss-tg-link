"""
Telegram Search Bot
====================
Commands:
    /start            → welcome + all commands
    /help             → same as /start
    /plans            → show all plans with channel list
    /a <keyword>      → search Plan A
    /b <keyword>      → search Plan B
    /c <keyword>      → search Plan C
    /debug            → check channel name matching
"""

import asyncio
import requests as http_requests
import uuid
import threading
import re
import base64
import logging
import threading
from io import BytesIO
from datetime import timezone, timedelta

from telethon import TelegramClient
from telethon.tl.types import Channel, Chat
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)
import subprocess, sys, os

# Auto-install chromium with all deps on Railway
def ensure_chromium():
    try:
        import subprocess
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
#  STEP 1 — Your Telegram login credentials
# ─────────────────────────────────────────────
API_ID        = int(os.environ["API_ID"])
API_HASH      = os.environ["API_HASH"]
PHONE         = os.environ["PHONE"]
BOT_TOKEN     = os.environ["BOT_TOKEN"]
YOUR_USER_ID  = [int(x.strip()) for x in os.environ.get("AUTHORIZED_USERS","").split(",") if x.strip()]

# ─────────────────────────────────────────────
#  STEP 2 — Define your channels
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

# ─────────────────────────────────────────────
#  STEP 4 — Save (Ctrl+S) and run
# ─────────────────────────────────────────────

MAX_RESULTS  = 1
SEARCH_HOURS = 12   # only search posts from last X hours
IST          = timezone(timedelta(hours=5, minutes=30))
PLANS       = {"A": PLAN_A, "B": PLAN_B, "C": PLAN_C}

# Photo cache — stores channel photos so we don't re-download every search
photo_cache: dict = {}

# ─── WhatsApp API Config ──────────────────────────────────
WA_API_URL = os.environ.get('WA_API_URL', '').rstrip('/')
WA_API_KEY = os.environ.get('WA_API_KEY', '')

# ── WhatsApp State ────────────────────────────────────────
user_wa_group = {}   # user_id → {'id': ..., 'name': ...}
pending_send  = {}   # cb_id → {img_b64, caption, group_id, group_name}
sent_wa       = {}   # cb_id → {key, group_id}

# ── Plan → WA Group mapping (persistent) ─────────────────
PLAN_GROUPS_FILE = '/data/plan_groups.json'

def load_plan_groups():
    import json
    try:
        if os.path.exists(PLAN_GROUPS_FILE):
            with open(PLAN_GROUPS_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {}  # {'A': {'id': ..., 'name': ...}, 'B': {...}, 'C': {...}}

def save_plan_groups(data):
    import json
    try:
        with open(PLAN_GROUPS_FILE, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        log.error(f'save_plan_groups: {e}')

plan_wa_groups = load_plan_groups()  # Plan → WA group mapping

# ── WhatsApp API helpers ──────────────────────────────────
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


# Photo cache — stores channel photos so we don't re-download every search
photo_cache: dict = {}




# ── Telethon on its own loop ──────────────────
telethon_loop   = asyncio.new_event_loop()
telethon_client: TelegramClient = None

def run_telethon_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()

def telethon_run(coro):
    return asyncio.run_coroutine_threadsafe(coro, telethon_loop).result(timeout=120)


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


# ── Fetch channel profile photo ───────────────

async def get_photo_b64(entity) -> str:
    key = str(entity.id)
    if key in photo_cache:
        return photo_cache[key]   # return cached photo instantly
    try:
        photo_bytes = await telethon_client.download_profile_photo(entity, file=bytes)
        if photo_bytes:
            result = "data:image/jpeg;base64," + base64.b64encode(photo_bytes).decode()
            photo_cache[key] = result
            return result
    except Exception as e:
        log.warning(f"Photo fetch failed: {e}")
    photo_cache[key] = ""   # cache empty result too so we don't retry
    return ""


# ── HTML builder ──────────────────────────────

def build_html(results: list, keyword: str, plan: str) -> str:
    rows = ""
    found_count    = sum(1 for r in results if r.get("found"))
    notfound_count = len(results) - found_count

    for m in results:
        name  = m["channel"]
        found = m.get("found", False)

        # ── Avatar: real photo or colored initials ──
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
            # Not posted row — greyed out
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

    # meta bar: only show not-found count when > 0
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


# ── Search ────────────────────────────────────

async def _search_one(ch_name: str, dialog, keyword: str, index: int) -> tuple:
    """Search a single channel — runs in parallel with others."""
    await asyncio.sleep(index * 0.3)  # 0.3s stagger per channel — looks human, avoids rate limit
    entity    = dialog.entity
    photo_b64 = await get_photo_b64(entity)
    username  = getattr(entity, "username", None)

    try:
        from datetime import datetime, timezone as tz
        cutoff = datetime.now(tz.utc) - timedelta(hours=SEARCH_HOURS)
        async for msg in telethon_client.iter_messages(entity, search=keyword, limit=50):
            if msg.date < cutoff:
                break
            if msg.text:
                link = f"https://t.me/{username}/{msg.id}" if username else f"https://t.me/c/{entity.id}/{msg.id}"
                return (ch_name, {
                    "channel":   ch_name,
                    "time":      to_ist(msg.date),
                    "text":      msg.text,
                    "link":      link,
                    "photo_b64": photo_b64,
                    "found":     True,
                })
    except Exception as e:
        log.warning(f"Skip [{ch_name}]: {e}")

    return (ch_name, {"channel": ch_name, "found": False, "photo_b64": photo_b64})


async def _search(keyword: str, plan_channels: list) -> list:
    dialogs    = await telethon_client.get_dialogs()
    plan_names = {ch[0].lower(): ch[0] for ch in plan_channels}
    matched    = {d.name.lower(): d for d in dialogs if d.name and d.name.lower() in plan_names}

    # Build tasks for all matched channels — run in parallel
    tasks   = []
    order   = []
    for i, (ch_name, ch_link) in enumerate(plan_channels):
        dialog = matched.get(ch_name.lower())
        if dialog:
            tasks.append(_search_one(ch_name, dialog, keyword, i))
            order.append(ch_name)
        # unmatched channels handled below

    # Run all searches at the same time
    task_results = await asyncio.gather(*tasks, return_exceptions=True)
    result_map   = {}
    for r in task_results:
        if isinstance(r, Exception):
            log.warning(f"Task error: {r}")
        else:
            ch_name, data = r
            result_map[ch_name] = data

    # Rebuild in original plan order
    results = []
    for ch_name, ch_link in plan_channels:
        if ch_name in result_map:
            results.append(result_map[ch_name])
        else:
            results.append({"channel": ch_name, "found": False, "photo_b64": ""})

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
        "🔧 /debug — Check channel name matching\n"
        "❓ /help — Show this message\n\n"
        "*Examples:*\n"
        "`/a iPhone`\n"
        "`/b Samsung`\n"
        "`/c Shoes`"
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
            None, lambda: telethon_run(_search(keyword, plan_channels))
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

        # Caption: Callout + Links
        not_found_count = len(results) - found_count

    
        links = ""
        for r in results:
            if r.get("found") and r.get("link"):
                links += f"{r['link']}\n"

        if not_found_count > 0:
            links += f"\n❌ Not posted ({not_found_count}): "
            links += ", ".join(r['channel'] for r in results if not r.get("found"))

        caption = links.strip()[:1020]
        # ── WhatsApp button ──
        # Use plan-specific group if set, else fall back to user's selected group
        wa_grp = plan_wa_groups.get(plan) or user_wa_group.get(user_id)
        if wa_grp and WA_API_URL:
            cb_id   = f'ws_{uuid.uuid4().hex[:8]}'
            img_b64 = base64.b64encode(png_bytes).decode()
            pending_send[cb_id] = {
                'img_b64':    img_b64,
                'caption':    caption.strip()[:900],
                'group_id':   wa_grp['id'],
                'group_name': wa_grp['name'],
            }
            threading.Timer(1800, lambda: pending_send.pop(cb_id, None)).start()
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(f'📤 Send to Plan {plan} Group ({wa_grp["name"]})', callback_data=cb_id)
            ]])
        elif WA_API_URL:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(f'⚠️ Set Plan {plan} group (/setgroup {plan.lower()})', callback_data=f'no_grp_{plan}')
            ]])
        else:
            kb = None

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

    # WA group select
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

    # Plan group select (setgroup callback)
    if data.startswith('sg_'):
        parts = data.split('_')  # sg_A_2
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

    # Send to WhatsApp
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

    # Delete from WhatsApp
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

async def cmd_a(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await plan_handler(update, context, "A")

async def cmd_b(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await plan_handler(update, context, "B")

async def cmd_c(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await plan_handler(update, context, "C")

async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in YOUR_USER_ID:
        await update.message.reply_text("⛔ Unauthorised.")
        return

    await update.message.reply_text("🔄 Fetching your joined channels...")

    async def _get_all():
        dialogs = await telethon_client.get_dialogs()
        return [d.name for d in dialogs if d.name]

    all_names = await asyncio.get_event_loop().run_in_executor(
        None, lambda: telethon_run(_get_all())
    )

    joined_text = "\n".join(f"• `{n}`" for n in sorted(all_names))
    await update.message.reply_text(
        f"📋 *All joined channels/groups ({len(all_names)}):*\n\n{joined_text}",
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
            msg += "\n\n*Not found (fix spelling):*\n"
            msg += "\n".join(f"❌ `{n}`" for n in not_matched)
        await update.message.reply_text(msg, parse_mode="Markdown")


# ── Startup ───────────────────────────────────

async def _start_telethon():
    global telethon_client
    telethon_client = TelegramClient("/data/user_session", API_ID, API_HASH)
    await telethon_client.start(phone=PHONE)
    log.info("✅ Telethon connected!")


def main():
    missing = []
    if API_ID == 0:        missing.append("API_ID")
    if not API_HASH:       missing.append("API_HASH")
    if not PHONE:          missing.append("PHONE")
    if not BOT_TOKEN:      missing.append("BOT_TOKEN")
    if not YOUR_USER_ID:   missing.append("YOUR_USER_ID")
    if missing:
        print(f"❌ Please fill in: {', '.join(missing)}")
        return

    t = threading.Thread(target=run_telethon_loop, args=(telethon_loop,), daemon=True)
    t.start()

    log.info("Connecting Telethon...")
    asyncio.run_coroutine_threadsafe(_start_telethon(), telethon_loop).result(timeout=60)

    log.info("Starting bot...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("plans", cmd_plans))
    app.add_handler(CommandHandler("a",     cmd_a))
    app.add_handler(CommandHandler("b",     cmd_b))
    app.add_handler(CommandHandler("c",     cmd_c))
    app.add_handler(CommandHandler("debug",   cmd_debug))
    app.add_handler(CommandHandler("wagroup",  cmd_wagroup))
    app.add_handler(CommandHandler("setgroup", cmd_setgroup))
    app.add_handler(CallbackQueryHandler(handle_callback))
    log.info("✅ Bot running! Send /start to your bot.")
    app.run_polling()


if __name__ == "__main__":
    main()
