import os, threading, time
from datetime import datetime, timedelta
from flask import Flask
import telebot
import yfinance as yf

BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

@app.route('/')
def home():
    return "ADIL ULTIMATE BOT LIVE - MT5 + Quotex + WAIT + CONFIRMED"

# --- PAIRS ---
PAIRS = {
    "GOLD": "GC=F",
    "EURUSD.r": "EURUSD=X",
    "BTCUSD.r": "BTC-USD"
}
REAL_NAME = {
    "GOLD": "XAUUSD.r (GOLD)",
    "EURUSD.r": "EURUSD.r",
    "BTCUSD.r": "BTCUSD.r"
}

def fmt(name, price):
    if price == 0: return "---"
    if "GOLD" in name: return f"{price:.2f}"
    if "EUR" in name: return f"{price:.5f}"
    return f"{price:.2f}"

def get_signal(ticker, tf):
    try:
        hist = yf.Ticker(ticker).history(period="5d" if tf=="15m" else "1mo", interval=tf)
        if len(hist) < 22:
            return "WAIT", 0, 0, 0, 0, 0, "Data Kam Hai"

        last = float(hist['Close'].iloc[-1])
        sma = float(hist['Close'].rolling(20).mean().iloc[-1])

        # WAIT LOGIC
        diff = abs(last - sma) / sma * 100
        if diff < 0.08: # Market sideways
            return "WAIT", last, 0, 0, 0, 0, f"Sideways {diff:.3f}%"

        sig = "BUY" if last > sma else "SELL"

        # SL/TP
        if "GC" in ticker:
            sl,tp1,tp2,tp3 = (0.004,0.006,0.012,0.020) if tf=="15m" else (0.006,0.008,0.015,0.025)
        elif "BTC" in ticker:
            sl,tp1,tp2,tp3 = (0.008,0.01,0.02,0.035) if tf=="15m" else (0.012,0.015,0.03,0.05)
        else: # EUR
            sl,tp1,tp2,tp3 = (0.001,0.0015,0.003,0.005) if tf=="15m" else (0.002,0.003,0.006,0.01)

        if sig == "BUY":
            return sig, last, last*(1-sl), last*(1+tp1), last*(1+tp2), last*(1+tp3), "Trend Strong"
        else:
            return sig, last, last*(1+sl), last*(1-tp1), last*(1-tp2), last*(1-tp3), "Trend Strong"

    except Exception as e:
        print(e)
        return "WAIT", 0, 0, 0, 0, 0, "Market Band Hai"

@bot.message_handler(func=lambda m: m.text and "signal" in m.text.lower())
def handle(m):
    dubai = (datetime.utcnow() + timedelta(hours=4)).strftime("%d-%m-%Y %I:%M %p")
    msg = f"💰 ADIL ULTIMATE PRO\n🕐 {dubai} Dubai\n✅ MT5 + Quotex + WAIT System\n\n"

    for tf_title, tf_code in [("1 HOUR", "1h"), ("15 MIN", "15m")]:
        msg += f"========== {tf_title} - CONFIRMED ==========\n"
        for short, ticker in PAIRS.items():
            sig, entry, sl, tp1, tp2, tp3, reason = get_signal(ticker, tf_code)

            if sig == "WAIT":
                msg += f"⏳ {REAL_NAME[short]} - WAIT\n{reason} - Trade Mat Lo, Thora Ruko!\n---\n"
            else:
                icon = "🚀" if sig == "BUY" else "🔻"
                qtx_time = "1H" if tf_code=="1h" else "15M"
                msg += f"{icon} {REAL_NAME[short]} - {sig} CONFIRMED\nEntry: {fmt(short,entry)} | SL: {fmt(short,sl)}\nTP1: {fmt(short,tp1)} | TP2: {fmt(short,tp2)} | TP3: {fmt(short,tp3)}\nQTX: {sig} {qtx_time} Trade\n---\n"
        msg += "\n"

    msg += "📌 MT5 = Entry/SL/TP lagao\n📌 Quotex = Sirf BUY/SELL dekho\n📌 WAIT = Market kharab hai, ruk jao"
    bot.send_message(m.chat.id, msg)

def run_bot():
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
