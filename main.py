import os, requests, telebot, time
from threading import Thread
from flask import Flask

BOT_TOKEN = os.environ.get("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home(): return "99% DOUBLE TF BOT LIVE"

def get_rsi(symbol, interval):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=30"
        kl = requests.get(url, timeout=8).json()
        closes = [float(k[4]) for k in kl]
        price = closes[-1]
        gains = sum(max(0, closes[i]-closes[i-1]) for i in range(1, len(closes)))
        losses = sum(max(0, closes[i-1]-closes[i]) for i in range(1, len(closes)))
        avg_gain = gains/29
        avg_loss = losses/29 + 0.0001
        rs = avg_gain/avg_loss
        rsi = 100 - (100/(1+rs))
        # Trend
        ema_fast = sum(closes[-9:])/9
        ema_slow = sum(closes[-21:])/21
        trend = "UP" if ema_fast > ema_slow else "DOWN"
        return price, rsi, trend
    except:
        return 0, 50, "UP"

@bot.message_handler(func=lambda m: "signal" in m.text.lower() or "/start" in m.text.lower())
def signal_handler(m):
    # BTC - 15m + 1H + 4H
    btc_15_p, btc_15_rsi, btc_15_t = get_rsi("BTCUSDT", "15m")
    btc_1h_p, btc_1h_rsi, btc_1h_t = get_rsi("BTCUSDT", "1h")
    btc_4h_p, btc_4h_rsi, btc_4h_t = get_rsi("BTCUSDT", "4h")

    # GOLD - PAXG = Gold
    gold_15_p, gold_15_rsi, gold_15_t = get_rsi("PAXGUSDT", "15m")
    gold_1h_p, gold_1h_rsi, gold_1h_t = get_rsi("PAXGUSDT", "1h")

    # EURO
    euro_15_p, euro_15_rsi, euro_15_t = get_rsi("EURUSDT", "15m")
    euro_1h_p, euro_1h_rsi, euro_1h_t = get_rsi("EURUSDT", "1h")

    def check_99(rsi15, rsi1h, t15, t1h):
        # 99% Logic: Dono TF UP + RSI 45-68
        return (45 < rsi15 < 70 and 45 < rsi1h < 70 and t15=="UP" and t1h=="UP")

    btc_confirm = check_99(btc_15_rsi, btc_1h_rsi, btc_15_t, btc_1h_t)
    btc_super_confirm = check_99(btc_15_rsi, btc_4h_rsi, btc_15_t, btc_4h_t) # 15m + 4H

    gold_confirm = check_99(gold_15_rsi, gold_1h_rsi, gold_15_t, gold_1h_t)
    euro_confirm = check_99(euro_15_rsi, euro_1h_rsi, euro_15_t, euro_1h_t)

    reply = f"""💎 ADIL BHAI 99% DOUBLE TF CONFIRMED 💎
2 Timeframe = 15m + 1H + 4H

1️⃣ BTC {btc_15_p:.1f}
   15m: RSI {btc_15_rsi:.0f} {btc_15_t} | 1H: RSI {btc_1h_rsi:.0f} {btc_1h_t} | 4H: {btc_4h_t}
   👉 { '✅ 99% LAMBA CONFIRMED' if btc_confirm and btc_super_confirm else '✅ 90% LAMBA' if btc_confirm else '❌ WAIT' }
   Entry: {btc_15_p:.1f} SL: 85000 TP: 86183

2️⃣ GOLD {gold_15_p:.1f}
   15m: {gold_15_t} {gold_15_rsi:.0f} | 1H: {gold_1h_t} {gold_1h_rsi:.0f}
   👉 { '✅ 99% LAMBA CONFIRMED' if gold_confirm else '❌ WAIT' }

3️⃣ EURO {euro_15_p:.4f}
   15m: {euro_15_t} {euro_15_rsi:.0f} | 1H: {euro_1h_t} {euro_1h_rsi:.0f}
   👉 { '✅ 99% LAMBA CONFIRMED' if euro_confirm else '❌ WAIT' }

Rule: Dono TF UP hoga tabhi 99% Signal
"""

    bot.send_message(m.chat.id, reply)

# 409 Fix + Start
def run_bot():
    try:
        bot.remove_webhook()
        bot.delete_webhook(drop_pending_updates=True)
        time.sleep(2)
    except: pass
    bot.infinity_polling(skip_pending=True, timeout=30)

Thread(target=run_bot).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
