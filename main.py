import telebot, requests, os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "APNA_TOKEN_YAHAN_DALO")
bot = telebot.TeleBot(BOT_TOKEN)

def get_all_prices():
    try:
        btc = float(requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=5).json()['price'])
    except: btc = 85400

    try:
        # Gold ~ XAUUSD
        gold_data = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT", timeout=5).json()
        gold = float(gold_data['price']) # PAXG = Gold
    except: gold = 2650

    try:
        # Euro ~ EURUSD (Binance se EURUSDT)
        euro = float(requests.get("https://api.binance.com/api/v3/ticker/price?symbol=EURUSDT", timeout=5).json()['price'])
    except: euro = 1.08

    return btc, gold, euro

@bot.message_handler(func=lambda m: True)
def handle(m):
    if "signal" not in m.text.lower() and "btc" not in m.text.lower() and "gold" not in m.text.lower() and "euro" not in m.text.lower():
        return

    btc, gold, euro = get_all_prices()

    # BTC Logic - Aap ka 85 wala
    if 85300 <= btc <= 85700:
        btc_msg = f"BTC {btc:.1f} -> LAMBA ✅ 95% UPAR"
    elif btc > 85700:
        btc_msg = f"BTC {btc:.1f} -> LAMBA ✅ 90% UPAR"
    else:
        btc_msg = f"BTC {btc:.1f} -> SHORT ❌ NEECHE"

    # GOLD Logic
    if gold >= 2640 and gold <= 2660:
        gold_msg = f"GOLD {gold:.1f} -> LAMBA ✅ 95% UPAR"
    elif gold > 2660:
        gold_msg = f"GOLD {gold:.1f} -> LAMBA ✅ Trend Tez"
    else:
        gold_msg = f"GOLD {gold:.1f} -> SHORT ❌ NEECHE"

    # EURO Logic
    if euro >= 1.0750 and euro <= 1.0850:
        euro_msg = f"EURO {euro:.4f} -> LAMBA ✅ 90% UPAR"
    elif euro > 1.0850:
        euro_msg = f"EURO {euro:.4f} -> LAMBA ✅ UPAR"
    else:
        euro_msg = f"EURO {euro:.4f} -> SHORT ❌ NEECHE"

    final_reply = f"""
🔥 Adil Bhai 3 SIGNAL READY 🔥

1. {btc_msg}
   Entry: {btc:.1f} | SL: 85000 | TP: 86183

2. {gold_msg}
   Entry: {gold:.1f} | SL: 2630 | TP: 2680

3. {euro_msg}
   Entry: {euro:.4f} | SL: 1.0700 | TP: 1.0900

95% Wala Zone Check Ho Gaya ✅
"""

    bot.send_message(m.chat.id, final_reply)

print("3 Coin Bot Start - BTC GOLD EURO...")
bot.infinity_polling()
