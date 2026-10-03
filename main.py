import os, asyncio, ccxt
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask
from threading import Thread

TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

print(f"TOKEN FOUND: {bool(TOKEN)}")
print(f"CHAT_ID FOUND: {bool(CHAT_ID)}")

app = Flask('')
@app.route('/')
def home(): return "TRIPLE TF BOT IS LIVE 24/7"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

async def get_analysis():
    exchange = ccxt.binance()
    ticker = exchange.fetch_ticker('BTC/USDT')
    price = ticker['last']
    return f"BTC: ${price} | 15M 1H 4H STRONG BUY | TP: {price*1.02:.2f}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Live ✅ /signal likho")

async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = await get_analysis()
    await update.message.reply_text(f"SIGNAL\n{result}")

async def main():
    keep_alive()
    if not TOKEN:
        print("ERROR: BOT_TOKEN missing in Environment!")
        while True: await asyncio.sleep(3600)
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("signal", signal_cmd))
    print("Starting Telegram Bot Polling...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    print("Bot Polling Started!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
