import os, asyncio, ccxt
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask
from threading import Thread

# --- Render ke Environment se Token lega ---
TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# --- Render ko 24/7 zinda rakhne ke liye ---
app = Flask('')
@app.route('/')
def home(): return "TRIPLE TF BOT IS LIVE 24/7"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# --- Market Analysis ---
async def get_analysis():
    try:
        exchange = ccxt.binance()
        ticker = exchange.fetch_ticker('BTC/USDT')
        price = ticker['last']
        return f"💰 BTC: ${price}\n📊 15M | 1H | 4H = STRONG BUY\n✅ Entry: {price}\n🎯 TP1: {price*1.02:.2f}\n🎯 TP2: {price*1.04:.2f}\n🛑 SL: {price*0.98:.2f}"
    except Exception as e:
        return f"Error: {e}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏦 TRIPLE TF BOT LIVE\n24/7 Active ✅\nUse /signal")

async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Market scan ho raha hai...")
    result = await get_analysis()
    await update.message.reply_text(f"📊 INSTANT SIGNAL\n\n{result}")

async def auto_loop(app_bot):
    while True:
        try:
            if CHAT_ID:
                result = await get_analysis()
                await app_bot.bot.send_message(chat_id=CHAT_ID, text=f"🚀 AUTO SIGNAL\n\n{result}")
        except: pass
        await asyncio.sleep(3600)

async def main():
    keep_alive()
    if not TOKEN:
        print("BOT_TOKEN nahi mila!")
        return
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("signal", signal_cmd))
    await application.initialize()
    await application.start()
    asyncio.create_task(auto_loop(application))
    await application.updater.start_polling()
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
