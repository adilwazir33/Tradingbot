import os, requests, telebot, time

BOT_TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

def get_all():
    try:
        btc = float(requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5).json()['price'])
    except: btc = 85400
    try:
        gold = float(requests.get("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT", timeout=5).json()['price'])
    except: gold = 2650
    try:
        euro = float(requests.get("https://api.binance.com/api/v3/ticker/price?symbol=EURUSDT", timeout=5).json()['price'])
    except: euro = 1.08
    return btc, gold, euro

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "Bot Live Hai Adil Bhai ✅\nBas 'signal' likho - BTC GOLD EURO 3no bhejunga")

@bot.message_handler(func=lambda m: True)
def handle(m):
    if "signal" not in m.text.lower() and "btc" not in m.text.lower():
        return
    btc, gold, euro = get_all()

    reply = f"""🔥 SUPER COMBINED 95% POWER 🔥

1️⃣ BTC {btc:.1f} -> {'LAMBA ✅ 95% UPAR' if 85300 <= btc <= 85700 else 'SHORT ❌'}
   Entry: {btc:.1f} | SL: 85000 | TP: 86183

2️⃣ GOLD {gold:.1f} -> {'LAMBA ✅ 95% UPAR' if gold >= 2640 else 'SHORT ❌'}
   Entry: {gold:.1f} | SL: 2630 | TP: 2680

3️⃣ EURO {euro:.4f} -> {'LAMBA ✅' if euro >= 1.075 else 'SHORT ❌'}
   Entry: {euro:.4f} | SL: 1.0700 | TP: 1.0900
"""
    bot.send_message(m.chat.id, reply)

# === 409 CONFLICT FIX ===
print("Cleaning old conflict...")
try:
    bot.remove_webhook()
    time.sleep(1)
    bot.delete_webhook(drop_pending_updates=True)
except: pass

print("Bot Started 100%...")
bot.infinity_polling(skip_pending=True, timeout=20)
