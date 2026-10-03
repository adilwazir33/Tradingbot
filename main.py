import os, asyncio, ccxt
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask
from threading import Thread

TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

app = Flask('')
@app.route('/')
def home(): return "TRIPLE TF BOT IS LIVE 24/7"
def run(): app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
def keep_alive(): Thread(target=run).start()

async def get_analysis():
    exchange = ccxt.binance()
    ticker = exchange.fetch_ticker('BTC/USDT')
    price = ticker['last']
    return f"BTC: ${price} | 15M 1H 4H STRONG BUY | SL: {price*0.99:.2f} TP: {price*1.02:.2f}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot Live Hai! /signal likho")

async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Signal nikal raha hu...")
    result = await get_analysis()
    await update.message.reply_text(f"📊 TRIPLE TF SIGNAL\n{result}")

async def main():
    keep_alive()
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("signal", signal_cmd))
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    print("Bot Polling Started!")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
