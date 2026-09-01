/**
 * WhatsApp Bridge Server
 * =======================
 * Ye server tumhare naye WhatsApp number se WhatsApp Web ke through connect hota hai
 * aur Telegram bot (telegram_screenshot.py) ke liye 3 endpoints deta hai:
 *   GET  /groups   -> saare WhatsApp groups ki list
 *   POST /send     -> image kisi group mein bhejo
 *   POST /delete   -> bheja hua message delete karo
 *   GET  /qr       -> login ke liye QR code (browser mein khol ke scan karo)
 *   GET  /status   -> connection status check
 *
 * Sabhi /groups, /send, /delete endpoints ko 'x-api-key' header chahiye
 * jo WA_API_KEY env variable se match hona chahiye.
 */

const express = require("express");
const { Client, LocalAuth, MessageMedia } = require("whatsapp-web.js");
const qrcode = require("qrcode");

const app = express();
app.use(express.json({ limit: "20mb" })); // images base64 mein bade ho sakte hain

const API_KEY = process.env.WA_API_KEY || "";
const PORT = process.env.PORT || 3000;
const SESSION_PATH = process.env.SESSION_PATH || "/data/wwebjs_auth";

let latestQr = null;
let isReady = false;

// ── WhatsApp Client Setup ──────────────────────────────
const client = new Client({
  authStrategy: new LocalAuth({ dataPath: SESSION_PATH }),
  puppeteer: {
    headless: true,
    executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
    args: [
      "--no-sandbox",
      "--disable-setuid-sandbox",
      "--disable-dev-shm-usage",
      "--disable-gpu",
    ],
  },
});

client.on("qr", (qr) => {
  latestQr = qr;
  isReady = false;
  console.log("📱 Naya QR code aaya! /qr endpoint browser mein kholo aur scan karo.");
});

client.on("ready", () => {
  isReady = true;
  latestQr = null;
  console.log("✅ WhatsApp connected aur ready hai!");
});

client.on("disconnected", (reason) => {
  isReady = false;
  console.log("⚠️ WhatsApp disconnect ho gaya:", reason);
});

client.initialize();

// ── Auth Middleware ─────────────────────────────────────
function checkApiKey(req, res, next) {
  const key = req.headers["x-api-key"];
  if (!API_KEY || key !== API_KEY) {
    return res.status(401).json({ success: false, error: "Invalid or missing x-api-key" });
  }
  next();
}

// ── Routes ───────────────────────────────────────────────

// QR code dikhane ke liye — pehli baar login karte waqt browser mein kholo
app.get("/qr", async (req, res) => {
  if (isReady) {
    return res.send("<h2>✅ Already connected! QR ki zaroorat nahi.</h2>");
  }
  if (!latestQr) {
    return res.send("<h2>⏳ QR abhi generate ho raha hai, thodi der mein refresh karo...</h2>");
  }
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

// Saare groups ki list do
app.get("/groups", checkApiKey, async (req, res) => {
  if (!isReady) return res.status(503).json({ success: false, error: "WhatsApp abhi ready nahi hai" });
  try {
    const chats = await client.getChats();
    const groups = chats
      .filter((c) => c.isGroup)
      .map((c) => ({ id: c.id._serialized, name: c.name }));
    res.json({ groups });
  } catch (e) {
    res.status(500).json({ success: false, error: e.message });
  }
});

// Image kisi group mein bhejo
app.post("/send", checkApiKey, async (req, res) => {
  if (!isReady) return res.status(503).json({ success: false, error: "WhatsApp abhi ready nahi hai" });
  try {
    const { type, content, groupId, caption } = req.body;
    if (type !== "image") {
      return res.status(400).json({ success: false, error: "Sirf 'image' type supported hai abhi" });
    }
    const media = new MessageMedia("image/png", content);
    const msg = await client.sendMessage(groupId, media, { caption: caption || "" });
    res.json({ success: true, key: msg.id._serialized });
  } catch (e) {
    res.status(500).json({ success: false, error: e.message });
  }
});

// Bheja hua message delete karo (10 min window ke andar)
app.post("/delete", checkApiKey, async (req, res) => {
  if (!isReady) return res.status(503).json({ success: false, error: "WhatsApp abhi ready nahi hai" });
  try {
    const { groupId, key } = req.body;
    const chat = await client.getChatById(groupId);
    const messages = await chat.fetchMessages({ limit: 50 });
    const msg = messages.find((m) => m.id._serialized === key);
    if (!msg) return res.json({ success: false, error: "Message nahi mila (shayad expire ho gaya)" });
    await msg.delete(true); // true = everyone ke liye delete
    res.json({ success: true });
  } catch (e) {
    res.status(500).json({ success: false, error: e.message });
  }
});

app.listen(PORT, () => {
  console.log(`🚀 WA Bridge server chal raha hai port ${PORT} par`);
});
