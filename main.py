import ccxt
import time
from flask import Flask
import threading
import telebot
import pandas as pd
import ta

# --- CONFIG ---
BOT_TOKEN = "APNA_TELEGRAM_BOT_TOKEN_YAHAN_DALO"  # <--- Yahan token dalna hai
app = Flask(__name__)

# BINANCE DELETE - AB BYBIT USE HOGA (RENDER PE BLOCK NAHI HAI)
exchange = ccxt.bybit({
    'enableRateLimit': True,
})

bot = telebot.TeleBot(BOT_TOKEN)

def get_signal(symbol='BTC/USDT'):
    try:
        # Triple TF Data
        tf_15m = exchange.fetch_ohlcv(symbol, '15m', limit=100)
        tf_1h = exchange.fetch_ohlcv(symbol, '1h', limit=100)
        tf_4h = exchange.fetch_ohlcv(symbol, '4h', limit=100)
        
        df_15 = pd.DataFrame(tf_15m, columns=['time','open','high','low','close','vol'])
        df_1h = pd.DataFrame(tf_1h, columns=['time','open','high','low','close','vol'])
        df_4h = pd.DataFrame(tf_4h, columns=['time','open','high','low','close','vol'])
        
        # EMA Logic
        df_15['ema50'] = ta.trend.ema_indicator(df_15['close'], 50)
        df_1h['ema50'] = ta.trend.ema_indicator(df_1h['close'], 50)
        df_4h['ema50'] = ta.trend.ema_indicator(df_4h['close'], 50)
        
        price = df_15['close'].iloc[-1]
        ema_15 = df_15['ema50'].iloc[-1]
        ema_1h = df_1h['ema50'].iloc[-1]
        ema_4h = df_4h['ema50'].iloc[-1]
        
        if price > ema_15 and price > ema_1h and price > ema_4h:
            signal = f"✅ LONG SIGNAL - BTC\n\nPrice: {price}\n15M EMA: {ema_15:.2f}\n1H EMA: {ema_1h:.2f}\n4H EMA: {ema_4h:.2f}\n\nEntry: {price}\nSL: {price*0.995:.2f}\nTarget: {price*1.01:.2f}"
        elif price < ema_15 and price < ema_1h and price < ema_4h:
            signal = f"🔴 SHORT SIGNAL - BTC\n\nPrice: {price}\n15M EMA: {ema_15:.2f}\n1H EMA: {ema_1h:.2f}\n4H EMA: {ema_4h:.2f}\n\nEntry: {price}\nSL: {price*1.005:.2f}\nTarget: {price*0.99:.2f}"
        else:
            signal = f"⏳ NO TRADE - WAIT\nPrice: {price}\nMixed TF - Sideways market hai"
            
        return signal
    except Exception as e:
        return f"Error: {e}"

@bot.message_handler(commands=['start'])
def start(msg):
    bot.reply_to(msg, "Bot Live Hai! /signal likho")

@bot.message_handler(commands=['signal'])
def signal_cmd(msg):
    bot.reply_to(msg, "⌛ Signal nikal raha hu...")
    sig = get_signal()
    bot.reply_to(msg, sig)

@app.route('/')
def home():
    return "Bot Running - Bybit OK"

def run_bot():
    bot.infinity_polling()

threading.Thread(target=run_bot).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
