#!/usr/bin/env python3

# ================= AUTO INSTALLER =================
import subprocess
import sys

def install(package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

for pkg in ["python-telegram-bot", "qrcode[pil]", "pillow"]:
    try:
        __import__(pkg.split("[")[0])
    except:
        install(pkg)

# ================= IMPORTS =================
import os
import uuid
import sqlite3
import qrcode
from io import BytesIO
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

TOKEN_FILE = "bot_token.txt"
DB_FILE = "ultimate_qr_wifi.db"

# ================= TOKEN =================
def get_token():
    if os.path.exists(TOKEN_FILE):
        return open(TOKEN_FILE).read().strip()
    token = input("Enter Bot Token: ")
    open(TOKEN_FILE, "w").write(token)
    return token

def save_token(token):
    open(TOKEN_FILE, "w").write(token)

BOT_TOKEN = get_token()

# ================= DATABASE =================
conn = sqlite3.connect(DB_FILE)
c = conn.cursor()

# Normal QR Table
c.execute("""
CREATE TABLE IF NOT EXISTS qrdata (
    id TEXT PRIMARY KEY,
    user_id INTEGER,
    data TEXT,
    password TEXT,
    expiry TEXT,
    downloads_left INTEGER,
    type TEXT
)
""")

# WiFi Table
c.execute("""
CREATE TABLE IF NOT EXISTS wifi (
    id TEXT PRIMARY KEY,
    ssid TEXT,
    wifi_password TEXT,
    security TEXT,
    access_password TEXT,
    expiry TEXT,
    views_left INTEGER
)
""")

conn.commit()

# ================= QR GENERATOR =================
def create_qr(data):
    qr = qrcode.QRCode(box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white")

# ================= MENU =================
def main_menu():
    keyboard = [
        [InlineKeyboardButton("📄 Text QR", callback_data="text")],
        [InlineKeyboardButton("📁 File QR", callback_data="file")],
        [InlineKeyboardButton("📶 Direct WiFi QR", callback_data="wifi_direct")],
        [InlineKeyboardButton("🔐 Secure Guest WiFi QR", callback_data="wifi_secure")],
        [InlineKeyboardButton("📜 My QR History", callback_data="history")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if context.args:
        await process_secure(update, context)
        return

    await update.message.reply_text(
        "👋 Ultimate QR + WiFi Bot 🔥\n\n"
        "Select option below:",
        reply_markup=main_menu()
    )

# ================= TOKEN CHANGE =================
async def token_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["change_token"] = True
    await update.message.reply_text("Enter new bot token:")

# ================= MENU HANDLER =================
async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    choice = query.data

    if choice == "history":
        await show_history(query)
        return

    context.user_data["mode"] = choice
    context.user_data["step"] = "data"

    if "wifi" in choice:
        await query.message.reply_text("Enter WiFi Name (SSID):")
    else:
        await query.message.reply_text("Send your data (text or file).")

# ================= HISTORY =================
async def show_history(query):
    user_id = query.from_user.id
    c.execute("SELECT id,expiry,downloads_left,type FROM qrdata WHERE user_id=?", (user_id,))
    rows = c.fetchall()

    if not rows:
        await query.message.reply_text("No QR history.")
        return

    msg = "Your QR History:\n\n"
    for row in rows:
        msg += f"ID: {row[0]}\nExpiry: {row[1]}\nLeft: {row[2]}\nType: {row[3]}\n\n"

    await query.message.reply_text(msg)

# ================= PROCESS SECURE LINK =================
async def process_secure(update, context):

    secure_id = context.args[0]

    # Check normal QR
    c.execute("SELECT data,password,expiry,downloads_left,type FROM qrdata WHERE id=?", (secure_id,))
    row = c.fetchone()

    if row:
        await process_normal_secure(update, context, secure_id, row)
        return

    # Check WiFi
    c.execute("SELECT ssid,wifi_password,security,access_password,expiry,views_left FROM wifi WHERE id=?", (secure_id,))
    row = c.fetchone()

    if row:
        await process_wifi_secure(update, context, secure_id, row)
        return

    await update.message.reply_text("Invalid or expired link.")

# ================= NORMAL QR PROCESS =================
async def process_normal_secure(update, context, secure_id, row):

    data, password, expiry, downloads_left, dtype = row

    if datetime.now() > datetime.fromisoformat(expiry):
        c.execute("DELETE FROM qrdata WHERE id=?", (secure_id,))
        conn.commit()
        await update.message.reply_text("Expired.")
        return

    if downloads_left <= 0:
        await update.message.reply_text("Limit reached.")
        return

    if password:
        context.user_data["pending_id"] = secure_id
        return await update.message.reply_text("Enter password:")

    await deliver_normal(update, secure_id, data, dtype, downloads_left)

# ================= WIFI PROCESS =================
async def process_wifi_secure(update, context, secure_id, row):

    ssid, wifi_pass, security, access_pass, expiry, views_left = row

    if datetime.now() > datetime.fromisoformat(expiry):
        c.execute("DELETE FROM wifi WHERE id=?", (secure_id,))
        conn.commit()
        await update.message.reply_text("Expired.")
        return

    if views_left <= 0:
        await update.message.reply_text("Limit reached.")
        return

    context.user_data["pending_wifi"] = secure_id
    await update.message.reply_text("Enter guest access password:")

# ================= PASSWORD HANDLER =================
async def handle_password(update, context):

    entered = update.message.text

    if context.user_data.get("pending_id"):
        secure_id = context.user_data["pending_id"]
        c.execute("SELECT data,password,downloads_left,type FROM qrdata WHERE id=?", (secure_id,))
        row = c.fetchone()
        if row and entered == row[1]:
            await deliver_normal(update, secure_id, row[0], row[3], row[2])
        else:
            await update.message.reply_text("Wrong password.")
        context.user_data.pop("pending_id", None)
        return

    if context.user_data.get("pending_wifi"):
        secure_id = context.user_data["pending_wifi"]
        c.execute("SELECT ssid,wifi_password,security,access_password,views_left FROM wifi WHERE id=?", (secure_id,))
        row = c.fetchone()
        if row and entered == row[3]:
            await deliver_wifi(update, secure_id, row)
        else:
            await update.message.reply_text("Wrong password.")
        context.user_data.pop("pending_wifi", None)
        return

# ================= DELIVER NORMAL =================
async def deliver_normal(update, secure_id, data, dtype, downloads_left):

    if dtype == "text":
        await update.message.reply_text(data)
    else:
        await update.message.reply_document(data)

    downloads_left -= 1

    if downloads_left <= 0:
        c.execute("DELETE FROM qrdata WHERE id=?", (secure_id,))
    else:
        c.execute("UPDATE qrdata SET downloads_left=? WHERE id=?", (downloads_left, secure_id))

    conn.commit()

# ================= DELIVER WIFI =================
async def deliver_wifi(update, secure_id, row):

    ssid, wifi_pass, security, access_pass, views_left = row

    wifi_format = f"WIFI:T:{security};S:{ssid};P:{wifi_pass};;"

    img = create_qr(wifi_format)

    bio = BytesIO()
    bio.name = "wifi.png"
    img.save(bio, "PNG")
    bio.seek(0)

    views_left -= 1

    if views_left <= 0:
        c.execute("DELETE FROM wifi WHERE id=?", (secure_id,))
    else:
        c.execute("UPDATE wifi SET views_left=? WHERE id=?", (views_left, secure_id))

    conn.commit()

    await update.message.reply_photo(bio, caption="Guest WiFi QR")

# ================= HANDLE INPUT =================
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if context.user_data.get("change_token"):
        save_token(update.message.text.strip())
        await update.message.reply_text("Token updated. Restarting...")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    if context.user_data.get("pending_id") or context.user_data.get("pending_wifi"):
        return await handle_password(update, context)

    step = context.user_data.get("step")
    mode = context.user_data.get("mode")

    if not step:
        return

    # ===== WiFi Direct =====
    if mode == "wifi_direct":

        if step == "data":
            context.user_data["ssid"] = update.message.text
            context.user_data["step"] = "wifi_pass"
            return await update.message.reply_text("Enter WiFi Password:")

        if step == "wifi_pass":
            wifi_format = f"WIFI:T:WPA;S:{context.user_data['ssid']};P:{update.message.text};;"
            img = create_qr(wifi_format)
            bio = BytesIO()
            bio.name = "wifi.png"
            img.save(bio, "PNG")
            bio.seek(0)
            await update.message.reply_photo(bio, caption="Direct WiFi QR")
            context.user_data.clear()
            return

    # ===== WiFi Secure =====
    if mode == "wifi_secure":

        if step == "data":
            context.user_data["ssid"] = update.message.text
            context.user_data["step"] = "wifi_pass"
            return await update.message.reply_text("Enter WiFi Password:")

        if step == "wifi_pass":
            context.user_data["wifi_pass"] = update.message.text
            context.user_data["step"] = "expiry"
            return await update.message.reply_text("Enter expiry (minutes):")

        if step == "expiry":
            context.user_data["expiry"] = int(update.message.text)
            context.user_data["step"] = "limit"
            return await update.message.reply_text("Enter view limit:")

        if step == "limit":
            context.user_data["limit"] = int(update.message.text)
            context.user_data["step"] = "access_pass"
            return await update.message.reply_text("Set guest access password:")

        if step == "access_pass":

            secure_id = str(uuid.uuid4())[:8]
            expiry_time = datetime.now() + timedelta(minutes=context.user_data["expiry"])

            c.execute(
                "INSERT INTO wifi VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    secure_id,
                    context.user_data["ssid"],
                    context.user_data["wifi_pass"],
                    "WPA",
                    update.message.text,
                    expiry_time.isoformat(),
                    context.user_data["limit"],
                ),
            )
            conn.commit()

            bot_username = (await context.bot.get_me()).username
            link = f"https://t.me/{bot_username}?start={secure_id}"

            img = create_qr(link)
            bio = BytesIO()
            bio.name = "secure_wifi.png"
            img.save(bio, "PNG")
            bio.seek(0)

            await update.message.reply_photo(bio, caption="Secure Guest WiFi QR")
            context.user_data.clear()
            return

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("token_change", token_change))
    app.add_handler(CallbackQueryHandler(menu_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_input))

    print("🔥 Ultimate QR + WiFi Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
