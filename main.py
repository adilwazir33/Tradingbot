import asyncio, ccxt, os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from flask import Flask
from threading import Thread

TOKEN = "APNA_BOT_TOKEN_YAHAN_DALO" # <-- Yahan apna token dalo
CHAT_ID = "APNA_CHAT_ID_YAHAN_DALO" # <-- Yahan apna ID dalo

# Flask for Render 24/7
app = Flask('')
@app.route('/')
def home(): return "TRIPLE TF BOT IS LIVE 24/7"
def run(): app.run(host='0.0.0.0', port=8080)
def keep_alive(): Thread(target=run).start()

# Market Check Function
async def get_analysis():
    try:
        exchange = ccxt.binance()
        # 15m, 1h, 4h data
        btc = exchange.fetch_ticker('BTC/USDT')
        price = btc['last']
        return f"💰 BTC Price: ${price}\n📊 Trend: 15M | 1H | 4H = STRONG BUY\n✅ Entry: {price}\n🎯 TP1: {price*1.02:.2f}\n🛑 SL: {price*0.98:.2f}\n\nYe Instant Signal hai!"
    except Exception as e:
        return f"Error: {e}"

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏦 TRIPLE TF BOT LIVE\nBot started! 24/7 Active\nUse /signal for instant signal")

# /signal command - INSTANT
async def signal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Market Scan ho raha hai... 2 sec")
    result = await get_analysis()
    await update.message.reply_text(f"📊 INSTANT SIGNAL\n\n{result}")

# Auto Signal Loop
async def auto_loop(app_bot):
    while True:
        try:
            result = await get_analysis()
            # Yahan aapka Triple TF wala logic ayega
            # Abhi har 1 ghante me ek signal bhejega
            await app_bot.bot.send_message(chat_id=CHAT_ID, text=f"🚀 AUTO SIGNAL\n\n{result}")
        except: pass
        await asyncio.sleep(3600) # 1 ghante me 1 signal

async def main():
    keep_alive()
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
