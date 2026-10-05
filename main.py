import os, requests, threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes, CommandHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN")
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "SUPER BOT LIVE"

def get_klines(sym, inter, lim=100):
    url=f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={inter}&limit={lim}"
    r=requests.get(url).json()
    return [float(x[4]) for x in r]

def get_rsi(c):
    g=l=0
    for i in range(1,15):
        d=c[-i]-c[-i-1]
        if d>0: g+=d
        else: l+=abs(d)
    if l==0: return 100
    return 100-(100/(1+(g/14)/(l/14)))

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        btc = get_klines("BTCUSDT","15m",50)
        price = btc[-1]
        rsi = get_rsi(btc)
        msg = f"👑 SUPER BOT REPLY AA GAYA! 👑\n\nBTC: {price:.2f}\nRSI: {rsi:.0f}\n\nAapka bot ab LIVE hai Adil bhai! Signal = {price}"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

def run_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", handle))
    app.add_handler(CommandHandler("signal", handle))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("(?i)signal"), handle))
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    flask_app.run(host='0.0.0.0', port=10000)
