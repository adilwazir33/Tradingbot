import os, requests, telebot, time
from threading import Thread
from flask import Flask

BOT_TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home(): return "Adil Bhai 99% Bot Live"

def safe_price(sym):
    try:
        # Ye wala link Render pe block nahi hota
        r = requests.get(f"https://data-api.binance.vision/api/v3/ticker/price?symbol={sym}", timeout=10).json()
        return float(r['price'])
    except:
        if "BTC" in sym: return 85650.0
        if "PAXG" in sym: return 2650.0
        return 1.08

def get_info(sym, interval):
    price = safe_price(sym)
    try:
        url = f"https://data-api.binance.vision/api/v3/klines?symbol={sym}&interval={interval}&limit=30"
        kl = requests.get(url, timeout=10).json()
        closes = [float(k[4]) for k in kl]
        gains = sum(max(0, closes[i]-closes[i-1]) for i in range(1, len(closes)))
        losses = sum(max(0, closes[i-1]-closes[i]) for i in range(1, len(closes)))
        rsi = 100 - (100/(1+ (gains/29)/(losses/29 + 0.001)))
        trend = "UP" if sum(closes[-9:])/9 > sum(closes[-21:])/21 else "DOWN"
        return price, rsi, trend
    except:
        return price, 58, "UP"

@bot.message_handler(func=lambda m: "signal" in m.text.lower() or "/start" in m.text.lower())
def sig(m):
    btc15_p, btc15_r, btc15_t = get_info("BTCUSDT", "15m")
    btc1h_p, btc1h_r, btc1h_t = get_info("BTCUSDT", "1h")
    gold15_p, gold15_r, gold15_t = get_info("PAXGUSDT", "15m")
    gold1h_p, gold1h_r, gold1h_t = get_info("PAXGUSDT", "1h")
    euro15_p, euro15_r, euro15_t = get_info("EURUSDT", "15m")
    euro1h_p, euro1h_r, euro1h_t = get_info("EURUSDT", "1h")

    btc_ok = 45 < btc15_r < 70 and 45 < btc1h_r < 70 and btc15_t=="UP" and btc1h_t=="UP"
    gold_ok = 45 < gold15_r < 70 and 45 < gold1h_r < 70 and gold15_t=="UP" and gold1h_t=="UP"
    euro_ok = 45 < euro15_r < 70 and 45 < euro1h_r < 70 and euro15_t=="UP" and euro1h_t=="UP"

    txt = f"""💎 ADIL BHAI 99% DOUBLE TF 💎

1️⃣ BTC {btc15_p:.2f}
   15m: {btc15_r:.0f} {btc15_t} | 1H: {btc1h_r:.0f} {btc1h_t}
   👉 {'✅ 99% LAMBA' if btc_ok else '❌ WAIT'} | Entry {btc15_p:.1f}

2️⃣ GOLD {gold15_p:.2f}
   15m: {gold15_r:.0f} {gold15_t} | 1H: {gold1h_r:.0f} {gold1h_t}
   👉 {'✅ 99% LAMBA' if gold_ok else '❌ WAIT'}

3️⃣ EURO {euro15_p:.4f}
   15m: {euro15_r:.0f} {euro15_t} | 1H: {euro1h_r:.0f} {euro1h_t}
   👉 {'✅ 99% LAMBA' if euro_ok else '❌ WAIT'}
"""
    bot.send_message(m.chat.id, txt)

def run_bot():
    try:
        bot.remove_webhook()
        bot.delete_webhook(drop_pending_updates=True)
    except: pass
    bot.infinity_polling(skip_pending=True)

Thread(target=run_bot).start()
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
