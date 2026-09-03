/**
 * WhatsApp Bridge Server — Baileys version (no Chromium/Puppeteer)
 * ==================================================================
 * whatsapp-web.js/Puppeteer approach was breaking every time WhatsApp Web's
 * frontend updated (the "r: r" bug). Baileys talks to WhatsApp's real
 * protocol directly — no browser automation, so it doesn't break the same way,
 * and it's much lighter on memory/CPU (no Chromium process running).
 *
 * Endpoints (same contract as before, Telegram bot code doesn't need to change):
 *   GET  /groups         -> list of WhatsApp groups
 *   POST /send            -> send an image to a group
 *   POST /delete           -> delete a previously sent message
 *   GET  /qr               -> QR code page (fallback, QR is also pushed to Telegram)
 *   GET  /status            -> connection status
 *   GET  /debug-chats-open  -> TEMP: list all chats, no auth (for diagnosing)
 *
 * /groups, /send, /delete need an 'x-api-key' header matching WA_API_KEY.
 */

const express = require("express");
const qrcode = require("qrcode");
const pino = require("pino");
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
} = require("@whiskeysockets/baileys");

const app = express();
app.use(express.json({ limit: "20mb" }));

const API_KEY = process.env.WA_API_KEY || "";
const PORT = process.env.PORT || 3000;
const SESSION_PATH = process.env.SESSION_PATH || "/data/baileys_auth";
const BOT_TOKEN = process.env.BOT_TOKEN || "";
const AUTHORIZED_USERS = (process.env.AUTHORIZED_USERS || "")
  .split(",").map((s) => s.trim()).filter(Boolean);

let latestQr = null;
let isReady = false;
let sock = null;
let lastQrSentAt = 0;  // debounce — Baileys QR har ~20 sec mein rotate hota hai, Telegram pe spam na ho

// In-memory map of sent message keys, so /delete can find them later
const sentMessages = new Map(); // ourKey -> baileys message key

// ── Telegram helpers ─────────────────────────────────

async function sendQrToTelegram(qr) {
  const now = Date.now();
  if (now - lastQrSentAt < 45000) {
    // Baileys ~20 sec mein QR rotate karta hai jab tak scan na ho — isi session
    // ke liye baar-baar naya photo nahi bhejna, sirf pehli baar.
    return;
  }
  lastQrSentAt = now;
  if (!BOT_TOKEN || AUTHORIZED_USERS.length === 0) {
    console.log("⚠️ BOT_TOKEN ya AUTHORIZED_USERS set nahi hai, QR sirf /qr page par milega.");
    return;
  }
  try {
    const qrBuffer = await qrcode.toBuffer(qr, { width: 400 });
    for (const userId of AUTHORIZED_USERS) {
      const form = new FormData();
      form.append("chat_id", userId);
      form.append("caption", "📱 WhatsApp se scan karo:\nSettings → Linked Devices → Link a Device");
      form.append("photo", new Blob([qrBuffer], { type: "image/png" }), "qr.png");
      const resp = await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendPhoto`, {
        method: "POST",
        body: form,
      });
      if (!resp.ok) console.log("⚠️ Telegram ko QR bhejne mein error:", await resp.text());
    }
    console.log("📤 QR code Telegram bot ke through bhej diya.");
  } catch (e) {
    console.log("⚠️ QR Telegram pe bhejne mein fail:", e.message);
  }
}

async function notifyTelegram(text) {
  if (!BOT_TOKEN || AUTHORIZED_USERS.length === 0) return;
  for (const userId of AUTHORIZED_USERS) {
    try {
      await fetch(`https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chat_id: userId, text }),
      });
    } catch (e) {
      console.log("⚠️ Telegram notify fail:", e.message);
    }
  }
}

// ── WhatsApp connection (Baileys) ─────────────────────

const logger = pino({ level: "warn" }); // Baileys is chatty — keep it quiet

async function startSocket() {
  const { state, saveCreds } = await useMultiFileAuthState(SESSION_PATH);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: state,
    logger,
    printQRInTerminal: false,
    browser: ["Chrome (Linux)", "Chrome", "120.0.0"],
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      latestQr = qr;
      isReady = false;
      console.log("📱 Naya QR code aaya! Telegram bot pe bhej raha hoon...");
      sendQrToTelegram(qr);
    }

    if (connection === "open") {
      isReady = true;
      latestQr = null;
      lastQrSentAt = 0;
      console.log("✅ WhatsApp connected aur ready hai!");
      notifyTelegram("✅ WhatsApp connect ho gaya! Ab /wagroup try kar sakte ho.");
    }

    if (connection === "close") {
      isReady = false;
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const loggedOut = statusCode === DisconnectReason.loggedOut;
      console.log(`⚠️ WhatsApp disconnect ho gaya (loggedOut=${loggedOut}, code=${statusCode})`);
      if (loggedOut) {
        lastQrSentAt = 0;
        notifyTelegram("⚠️ WhatsApp session logout ho gaya. Naya QR generate hoga jab dobara start hoga.");
      } else {
        console.log("🔄 Reconnecting...");
        setTimeout(startSocket, 3000);
      }
    }
  });
}

startSocket().catch((e) => {
  console.log("⚠️ startSocket fail hua, 15 sec baad retry:", e.message);
  setTimeout(startSocket, 15000);
});

process.on("uncaughtException", (err) => {
  console.log("⚠️ Uncaught exception (WA bridge process crash nahi hone dega):", err.message);
});
process.on("unhandledRejection", (err) => {
  console.log("⚠️ Unhandled rejection (WA bridge process crash nahi hone dega):", err);
});

// ── Auth middleware ────────────────────────────────────

function checkApiKey(req, res, next) {
  const key = req.headers["x-api-key"];
  if (!API_KEY || key !== API_KEY) {
    return res.status(401).json({ success: false, error: "Invalid or missing x-api-key" });
  }
  next();
}

// ── Routes ─────────────────────────────────────────────

app.get("/qr", async (req, res) => {
  if (isReady) return res.send("<h2>✅ Already connected! QR ki zaroorat nahi.</h2>");
  if (!latestQr) return res.send("<h2>⏳ QR abhi generate ho raha hai, thodi der mein refresh karo...</h2>");
  const qrImage = await qrcode.toDataURL(latestQr);
  res.send(`
    <html><body style="text-align:center; font-family:sans-serif; margin-top:40px;">
      <h2>WhatsApp se scan karo</h2>
      <p>Naye number ke WhatsApp app mein: Settings → Linked Devices → Link a Device</p>
      <img src="${qrImage}" style="width:300px;height:300px;" />
      <p><a href="/qr">Refresh</a></p>
    </body></html>
  `);
});

app.get("/status", (req, res) => {
  res.json({ ready: isReady, waiting_for_qr: !isReady && !!latestQr });
});

// Telegram bot ka /qr command isko call karta hai — protected (API key chahiye)
app.get("/qr-image", checkApiKey, async (req, res) => {
  if (isReady) return res.json({ ready: true });
  if (!latestQr) return res.json({ ready: false, qr_base64: null });
  const qrBuffer = await qrcode.toBuffer(latestQr, { width: 400 });
  res.json({ ready: false, qr_base64: qrBuffer.toString("base64") });
});

app.get("/groups", checkApiKey, async (req, res) => {
  if (!isReady) return res.status(503).json({ success: false, error: "WhatsApp abhi ready nahi hai" });
  try {
    const all = await sock.groupFetchAllParticipating();
    const groups = Object.values(all).map((g) => ({ id: g.id, name: g.subject }));
    res.json({ groups });
  } catch (e) {
    res.status(500).json({ success: false, error: e.message });
  }
});

// TEMPORARY — bina API key ke, diagnosing ke liye. Baad mein hata dena.
app.get("/debug-chats-open", async (req, res) => {
  if (!isReady) return res.status(503).json({ success: false, error: "WhatsApp abhi ready nahi hai" });
  try {
    const all = await sock.groupFetchAllParticipating();
    const groups = Object.values(all).map((g) => ({ id: g.id, name: g.subject, isGroup: true }));
    res.json({ total: groups.length, chats: groups });
  } catch (e) {
    res.status(500).json({ success: false, error: e.message });
  }
});

app.post("/send", checkApiKey, async (req, res) => {
  if (!isReady) return res.status(503).json({ success: false, error: "WhatsApp abhi ready nahi hai" });
  try {
    const { type, content, groupId, caption } = req.body;
    if (type !== "image") {
      return res.status(400).json({ success: false, error: "Sirf 'image' type supported hai abhi" });
    }
    const buffer = Buffer.from(content, "base64");
    const sent = await sock.sendMessage(groupId, { image: buffer, caption: caption || "" });
    const ourKey = `${sent.key.remoteJid}_${sent.key.id}`;
    sentMessages.set(ourKey, sent.key);
    res.json({ success: true, key: ourKey });
  } catch (e) {
    res.status(500).json({ success: false, error: e.message });
  }
});

app.post("/delete", checkApiKey, async (req, res) => {
  if (!isReady) return res.status(503).json({ success: false, error: "WhatsApp abhi ready nahi hai" });
  try {
    const { key } = req.body;
    const msgKey = sentMessages.get(key);
    if (!msgKey) return res.json({ success: false, error: "Message nahi mila (shayad expire ho gaya)" });
    await sock.sendMessage(msgKey.remoteJid, { delete: msgKey });
    sentMessages.delete(key);
    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ success: false, error: e.message });
  }
});

app.listen(PORT, () => {
  console.log(`🚀 WA Bridge server (Baileys) chal raha hai port ${PORT} par`);
});
