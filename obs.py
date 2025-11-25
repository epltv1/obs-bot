#!/usr/bin/env python3
import asyncio
import os
import signal
import json
import time
import psutil
import uuid
import random
import string
from datetime import datetime, timedelta
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
BOT_TOKEN = "7454188408:AAE-CRiDf-Kv1BdPm-78kR55ZcJuBTvdb2Y"
OWNER_ID  = 1882002437
DATA_DIR  = Path("data")
DATA_DIR.mkdir(exist_ok=True)
STREAM_DB = DATA_DIR / "streams.json"
LOG_FILE  = DATA_DIR / "bot.log"

(INPUT_URL, INPUT_RTMP, INPUT_TITLE, CONFIRM_START) = range(4)

# ----------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")

def load_db():
    if STREAM_DB.exists():
        with open(STREAM_DB, "r") as f:
            return json.load(f)
    return {}

def save_db(db):
    with open(STREAM_DB, "w") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

# ----------------------------------------------------------------------
# STREAM CLASS — M3U8 → ANY RTMP/RTMPS
# ----------------------------------------------------------------------
class Stream:
    def __init__(self, sid, data):
        self.sid = sid
        self.data = data
        self.proc = None
        self.start_time = time.time()
        self.thumb_path = DATA_DIR / f"thumb_{sid}.jpg"

    async def start(self, app):
        cmd = self._build_ffmpeg()
        log(f"STARTING: {' '.join(cmd)}")
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        asyncio.create_task(self._monitor(app))

    def _build_ffmpeg(self):
        src = self.data["url"]
        rtmp = self.data["rtmp_url"]

        base = [
            "ffmpeg", "-y",
            "-analyzeduration", "1000000",
            "-probesize", "1000000",
            "-fflags", "+genpts",
            "-re", "-i", src,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-b:v", "1200k",
            "-maxrate", "1400k",
            "-bufsize", "2000k",
            "-c:a", "aac",
            "-b:a", "128k",
            "-f", "flv"
        ]

        # RTMPS (SSL) → Add tls flags
        if rtmp.startswith("rtmps://"):
            base.extend([
                "-rtmp_live", "live",
                "-rtmp_app", rtmp.split("/", 3)[3].split("?")[0] if "/" in rtmp.split("://", 1)[1] else "",
                "-rtmp_playpath", "",
                "-rtmp_swfurl", "",
                "-rtmp_tcurl", rtmp,
                rtmp
            ])
            return base

        # Standard RTMP
        base.append(rtmp)
        return base

    async def _monitor(self, app):
        while True:
            await asyncio.sleep(2)
            if self.proc and self.proc.returncode is not None:
                break
        await self._on_exit(app)

    async def _on_exit(self, app):
        uptime = str(timedelta(seconds=int(time.time() - self.start_time)))
        title = self.data.get("title", "Unknown")
        await app.bot.send_message(
            OWNER_ID,
            f"Stream *{title}* stopped after {uptime}\n"
            f"RTMP: {self.data['rtmp_url']}",
            parse_mode="Markdown"
        )
        STREAMS.pop(self.sid, None)
        db = load_db()
        db.pop(self.sid, None)
        save_db(db)
        if self.thumb_path.exists():
            self.thumb_path.unlink(missing_ok=True)

    async def stop(self):
        if self.proc and self.proc.returncode is not None:
            return
        self.proc.send_signal(signal.SIGTERM)
        await asyncio.sleep(1)
        if self.proc.returncode is None:
            self.proc.kill()
        if self.thumb_path.exists():
            self.thumb_path.unlink(missing_ok=True)

    async def take_thumbnail(self):
        src = self.data["url"]
        out = str(self.thumb_path)
        cmd = ["ffmpeg", "-y", "-i", src, "-vframes", "1", "-ss", "5", "-q:v", "2", out]
        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.wait()
        return self.thumb_path.exists()

    def uptime_str(self):
        return str(timedelta(seconds=int(time.time() - self.start_time)))

# ----------------------------------------------------------------------
# GLOBAL
# ----------------------------------------------------------------------
STREAMS: dict = {}

async def load_running_streams(app):
    db = load_db()
    for sid, data in db.items():
        stream = Stream(sid, data)
        STREAMS[sid] = stream
        asyncio.create_task(stream.start(app))

# ----------------------------------------------------------------------
# COMMANDS
# ----------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("*M3U8 → RTMP/RTMPS Bot*\nUse /help", parse_mode="Markdown")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "*Commands*\n"
        "/stream – start M3U8 → RTMP/RTMPS\n"
        "/streamlist – view & stop\n"
        "/ping – stats",
        parse_mode="Markdown"
    )

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    cpu = psutil.cpu_percent(1)
    await update.message.reply_text(
        f"*VPS*\nCPU: {cpu}%\nRAM: {ram.percent}%\nDisk: {disk.percent}%",
        parse_mode="Markdown"
    )

# ----------------------------------------------------------------------
# /stream
# ----------------------------------------------------------------------
async def stream_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("Owner only.")
        return ConversationHandler.END
    await update.message.reply_text("Send M3U8 URL:")
    return INPUT_URL

async def input_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["url"] = update.message.text.strip()
    await update.message.reply_text("Send RTMP URL (rtmp:// or rtmps://):")
    return INPUT_RTMP

async def input_rtmp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rtmp = update.message.text.strip()
    if not rtmp.startswith(("rtmp://", "rtmps://")):
        await update.message.reply_text("Invalid! Must start with `rtmp://` or `rtmps://`")
        return INPUT_RTMP
    context.user_data["rtmp_url"] = rtmp
    await update.message.reply_text("Send stream title:")
    return INPUT_TITLE

async def input_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["title"] = update.message.text.strip()
    kb = [[InlineKeyboardButton("Start Stream", callback_data="start_stream")]]
    await update.message.reply_text(
        f"Start: *{context.user_data['title']}*\n"
        f"M3U8: {context.user_data['url']}\n"
        f"RTMP: `{context.user_data['rtmp_url']}`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )
    return CONFIRM_START

async def confirm_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Starting...")

    sid = str(uuid.uuid4())
    data = context.user_data.copy()
    stream = Stream(sid, data)
    STREAMS[sid] = stream
    asyncio.create_task(stream.start(context.application))

    db = load_db()
    db[sid] = data
    save_db(db)

    await q.edit_message_text("Stream started! Supports RTMP & RTMPS.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

# ----------------------------------------------------------------------
# /streamlist
# ----------------------------------------------------------------------
async def streamlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not STREAMS:
        await update.message.reply_text("No streams.")
        return

    for sid, stream in list(STREAMS.items()):
        if stream.proc and stream.proc.returncode is not None:
            await stream.stop()
            STREAMS.pop(sid, None)
            db = load_db()
            db.pop(sid, None)
            save_db(db)
            continue

        await stream.take_thumbnail()
        title = stream.data['title']
        up = stream.uptime_str()
        kb = [[InlineKeyboardButton("Stop", callback_data=f"stop_{sid}")]]

        if stream.thumb_path.exists():
            await update.message.reply_photo(
                photo=open(stream.thumb_path, "rb"),
                caption=f"*M3U8 Stream*\nTitle: {title}\nUptime: {up}\nRTMP: `{stream.data['rtmp_url']}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            await update.message.reply_text(
                f"*M3U8 Stream*\nTitle: {title}\nUptime: {up}\nRTMP: `{stream.data['rtmp_url']}`",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(kb)
            )

async def stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    sid = q.data.split("_")[1]
    stream = STREAMS.get(sid)
    if stream:
        await stream.stop()
        STREAMS.pop(sid)
        db = load_db()
        db.pop(sid, None)
        save_db(db)
    await q.edit_message_text("Stopped.")

# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------
async def post_init(app: Application):
    app.bot_data["start_ts"] = time.time()
    await load_running_streams(app)

def main():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("stream", stream_start)],
        states={
            INPUT_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_url)],
            INPUT_RTMP: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_rtmp)],
            INPUT_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_title)],
            CONFIRM_START: [CallbackQueryHandler(confirm_start, "^start_stream$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(conv)
    app.add_handler(CommandHandler("streamlist", streamlist))
    app.add_handler(CallbackQueryHandler(stop_callback, "^stop_"))

    app.run_polling()

if __name__ == "__main__":
    main()
