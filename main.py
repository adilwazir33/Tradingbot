import os, requests, threading
from flask import Flask

# Flask pehle start hoga taaki Render khush rahe
flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "ADIL BHAI SUPER BOT LIVE HAI! 99.9% GOD MODE"

BOT_TOKEN = os.environ.get("BOT_TOKEN")
print(f"TOKEN CHECK: {'Mila' if BOT_TOKEN else 'NAHI MILA - Render me Environment me daalo!'}")

def get_klines(symbol, interval, limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    return requests.get(url).json()

def get_analysis(symbol):
    try:
        data = get_klines(symbol, "15m", 100)
        closes = [float(c[4]) for c in data]
        price = closes[-1]
        # Simple RSI
        g=l=0
        for i in range(1,15):
            d=closes[-i]-closes[-i-1]
            if d>0: g+=d
            else: l+=abs(d)
        rsi = 100 - (100/(1+(g/14)/(l/14 if l!=0 else 1)))
        return price, rsi
    except:
        return 0, 0

# Bot wala part alag thread me
def run_bot():
    if not BOT_TOKEN:
        print("BOT_TOKEN missing! Bot start nahi hoga.")
        return
    try:
        from telegram import Update
        from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
        async def signal_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
            btc_data = get_klines("BTCUSDT", "15m", 1)
            btc_price = float(btc_data[0][4])
            await update.message.reply_text(f"BOT LIVE HAI BHAI! BTC {btc_price}")

        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(MessageHandler(filters.TEXT & filters.Regex("(?i)signal"), signal_handler))
        print("Bot polling started...")
        app.run_polling()
    except Exception as e:
        print(f"Bot Error: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    # Ye line Render ko LIVE rakhegi
    flask_app.run(host='0.0.0.0', port=10000)
