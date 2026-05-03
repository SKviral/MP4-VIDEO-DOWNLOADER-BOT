"""
╔══════════════════════════════════════════════════════════════════╗
║          🤖 TERABOX VIDEO DOWNLOADER BOT — PREMIUM v2.0          ║
║         Bug Fixed | New Features | Channel Auto-Post             ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import re
import json
import time
import math
import uuid
import shutil
import zipfile
import asyncio
import hashlib
import traceback
import subprocess
from datetime import datetime, timezone

import aiohttp
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from keep_alive import keep_alive

print("⏳ Bot starting...", flush=True)

# ══════════════════════════════════════════════════════════════════════
# ENV VARS
# ══════════════════════════════════════════════════════════════════════
API_ID_STR          = os.environ.get("API_ID", "").strip()
API_HASH            = os.environ.get("API_HASH", "").strip()
BOT_TOKEN           = os.environ.get("BOT_TOKEN", "").strip()
DEFAULT_TERABOX_KEY = os.environ.get("TERABOX_API_KEY", "").strip()
ADMIN_USER_IDS_STR  = os.environ.get("ADMIN_IDS", "").strip()   # comma-separated

if not API_ID_STR or not API_HASH or not BOT_TOKEN:
    print("❌ ERROR: API_ID, API_HASH বা BOT_TOKEN সেট করা নেই!", flush=True)
    sys.exit(1)

try:
    API_ID = int(API_ID_STR)
except ValueError:
    print("❌ ERROR: API_ID শুধুমাত্র সংখ্যা হতে হবে!", flush=True)
    sys.exit(1)

ADMIN_IDS: set[int] = set()
for _aid in ADMIN_USER_IDS_STR.split(","):
    _aid = _aid.strip()
    if _aid.isdigit():
        ADMIN_IDS.add(int(_aid))

# ══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════
CHUNK_SIZE       = 2 * 1024 * 1024          # 2 MB chunks
MAX_FILE_SIZE    = 2 * 1024 * 1024 * 1024   # 2 GB
MIN_VIDEO_SIZE   = 10 * 1024                # 10 KB
MAX_RETRIES      = 3
VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v", ".ts", ".3gp")
USER_API_FILE    = "user_apis.json"
CHANNEL_FILE     = "user_channels.json"
STATS_FILE       = "bot_stats.json"
TERABOX_API_URL  = "https://xapiverse.com/api/terabox"
BOT_START_TIME   = time.time()

TERABOX_DOMAINS = (
    "terabox.com", "1024terabox.com", "teraboxapp.com",
    "freeterabox.com", "4funbox.co", "mirrobox.com",
    "momerybox.com", "tibibox.com", "nephobox.com", "terabox.app",
    "terabox.fun", "teraboxlink.com", "terabox.live",
)

# Pyrogram client
app = Client(
    "video_downloader_v2",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

# State tracking: { user_id: {"step": "..."} }
waiting_state: dict = {}

# ══════════════════════════════════════════════════════════════════════
# FFMPEG CHECK — ভিডিও রিপেয়ারের জন্য
# ══════════════════════════════════════════════════════════════════════
def has_ffmpeg() -> bool:
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False

FFMPEG_AVAILABLE = has_ffmpeg()

# ══════════════════════════════════════════════════════════════════════
# STATS TRACKING
# ══════════════════════════════════════════════════════════════════════
def load_stats() -> dict:
    if os.path.exists(STATS_FILE):
        try:
            with open(STATS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_downloads": 0, "total_bytes": 0, "total_users": 0, "daily": {}}

def save_stats(stats: dict):
    try:
        with open(STATS_FILE, "w") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def increment_stat(key: str, value: int = 1):
    stats = load_stats()
    stats[key] = stats.get(key, 0) + value
    today = datetime.now().strftime("%Y-%m-%d")
    if "daily" not in stats:
        stats["daily"] = {}
    if today not in stats["daily"]:
        stats["daily"][today] = {"downloads": 0, "bytes": 0}
    if key == "total_downloads":
        stats["daily"][today]["downloads"] = stats["daily"][today].get("downloads", 0) + value
    elif key == "total_bytes":
        stats["daily"][today]["bytes"] = stats["daily"][today].get("bytes", 0) + value
    save_stats(stats)

# ══════════════════════════════════════════════════════════════════════
# USER API STORAGE
# ══════════════════════════════════════════════════════════════════════
def load_data() -> dict:
    if os.path.exists(USER_API_FILE):
        try:
            with open(USER_API_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_data(data: dict):
    with open(USER_API_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_data(user_id: int) -> dict:
    data = load_data()
    raw = data.get(str(user_id), {"active": None, "keys": {}})
    if isinstance(raw, str):
        migrated = {"active": "default", "keys": {"default": raw}}
        data[str(user_id)] = migrated
        save_data(data)
        return migrated
    return raw

def save_user_data(user_id: int, udata: dict):
    data = load_data()
    data[str(user_id)] = udata
    save_data(data)

def get_active_key(user_id: int) -> str | None:
    udata = get_user_data(user_id)
    active = udata.get("active")
    if active and active in udata.get("keys", {}):
        return udata["keys"][active]
    return None

def add_user_key(user_id: int, label: str, api_key: str):
    udata = get_user_data(user_id)
    if "keys" not in udata:
        udata["keys"] = {}
    udata["keys"][label] = api_key
    if not udata.get("active"):
        udata["active"] = label
    save_user_data(user_id, udata)

def set_active_key(user_id: int, label: str):
    udata = get_user_data(user_id)
    if label in udata.get("keys", {}):
        udata["active"] = label
        save_user_data(user_id, udata)

def delete_user_key(user_id: int, label: str):
    udata = get_user_data(user_id)
    keys = udata.get("keys", {})
    keys.pop(label, None)
    udata["keys"] = keys
    if udata.get("active") == label:
        udata["active"] = next(iter(keys), None)
    save_user_data(user_id, udata)

def mask_key(key: str) -> str:
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]

# ══════════════════════════════════════════════════════════════════════
# CHANNEL STORAGE
# ══════════════════════════════════════════════════════════════════════
def load_channels() -> dict:
    if os.path.exists(CHANNEL_FILE):
        try:
            with open(CHANNEL_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_channels(data: dict):
    with open(CHANNEL_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_channels(user_id: int) -> list:
    data = load_channels()
    return data.get(str(user_id), [])

def add_user_channel(user_id: int, channel_id, title: str) -> bool:
    data = load_channels()
    uid = str(user_id)
    if uid not in data:
        data[uid] = []
    for ch in data[uid]:
        if str(ch["id"]) == str(channel_id):
            return False
    data[uid].append({"id": channel_id, "title": title})
    save_channels(data)
    return True

def delete_user_channel(user_id: int, index: int):
    data = load_channels()
    uid = str(user_id)
    if uid in data and 0 <= index < len(data[uid]):
        data[uid].pop(index)
        save_channels(data)

# ══════════════════════════════════════════════════════════════════════
# BACKUP SYSTEM — ডেটা ব্যাকআপ/ডাউনলোড
# ══════════════════════════════════════════════════════════════════════
def create_backup_zip() -> str:
    """সব ডেটা ফাইল একটি ZIP-এ প্যাক করো।"""
    backup_name = f"bot_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    backup_path = f"/tmp/{backup_name}"
    files_to_backup = [USER_API_FILE, CHANNEL_FILE, STATS_FILE]
    with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in files_to_backup:
            if os.path.exists(fp):
                zf.write(fp, os.path.basename(fp))
    return backup_path

def restore_from_backup(zip_path: str) -> tuple[bool, str]:
    """ZIP ব্যাকআপ থেকে ডেটা রিস্টোর করো।"""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            allowed = {USER_API_FILE, CHANNEL_FILE, STATS_FILE}
            for name in names:
                if name in allowed:
                    zf.extract(name, ".")
        return True, f"✅ রিস্টোর সম্পন্ন! ফাইলগুলো: {', '.join(names)}"
    except Exception as e:
        return False, f"❌ রিস্টোর ব্যর্থ: {str(e)}"

# ══════════════════════════════════════════════════════════════════════
# KEYBOARDS — API
# ══════════════════════════════════════════════════════════════════════
def api_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    udata = get_user_data(user_id)
    keys = udata.get("keys", {})
    buttons = [
        [InlineKeyboardButton("➕ নতুন API Key যোগ করুন", callback_data="api_add")],
    ]
    if keys:
        buttons.append([InlineKeyboardButton("🔄 Active Key পরিবর্তন করুন", callback_data="api_switch")])
        buttons.append([InlineKeyboardButton("🗑️ কোনো Key মুছুন", callback_data="api_delete_list")])
    buttons.append([InlineKeyboardButton("📋 সব Key দেখুন", callback_data="api_list")])
    buttons.append([InlineKeyboardButton("❓ API Key কোথায় পাবো?", callback_data="api_help")])
    return InlineKeyboardMarkup(buttons)

def keys_select_keyboard(user_id: int, action: str) -> InlineKeyboardMarkup:
    udata = get_user_data(user_id)
    keys = udata.get("keys", {})
    active = udata.get("active")
    buttons = []
    for label in keys:
        mark = "✅ " if label == active else ""
        buttons.append([InlineKeyboardButton(
            f"{mark}{label}", callback_data=f"{action}:{label}"
        )])
    buttons.append([InlineKeyboardButton("🔙 পিছনে যান", callback_data="api_menu")])
    return InlineKeyboardMarkup(buttons)

def api_menu_text(user_id: int) -> str:
    udata = get_user_data(user_id)
    keys = udata.get("keys", {})
    active = udata.get("active")
    if not keys:
        status = "❌ কোনো API Key সেট নেই।\nএখন **ডিফল্ট API** ব্যবহার হচ্ছে।"
    else:
        active_key = keys.get(active, "")
        status = (
            f"✅ **{len(keys)}টি** API Key সেভ আছে।\n"
            f"🟢 Active: **{active}** (`{mask_key(active_key)}`)"
        )
    return f"⚙️ **Terabox API Key ম্যানেজমেন্ট**\n\n{status}"

# ══════════════════════════════════════════════════════════════════════
# KEYBOARDS — CHANNEL
# ══════════════════════════════════════════════════════════════════════
def channel_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    channels = get_user_channels(user_id)
    buttons = [
        [InlineKeyboardButton("➕ চ্যানেল যোগ করুন", callback_data="ch_add")],
    ]
    if channels:
        buttons.append([InlineKeyboardButton("📋 সেভ করা চ্যানেল দেখুন", callback_data="ch_list")])
        buttons.append([InlineKeyboardButton("🗑️ চ্যানেল মুছুন", callback_data="ch_delete_list")])
    return InlineKeyboardMarkup(buttons)

def channel_delete_keyboard(user_id: int) -> InlineKeyboardMarkup:
    channels = get_user_channels(user_id)
    buttons = []
    for i, ch in enumerate(channels):
        buttons.append([InlineKeyboardButton(
            f"🗑️ {ch['title']}", callback_data=f"ch_del:{i}"
        )])
    buttons.append([InlineKeyboardButton("🔙 পিছনে যান", callback_data="ch_menu")])
    return InlineKeyboardMarkup(buttons)

def back_ch_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে যান", callback_data="ch_menu")]])

def back_api_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে যান", callback_data="api_menu")]])

def channel_menu_text(user_id: int) -> str:
    channels = get_user_channels(user_id)
    if not channels:
        status = "❌ কোনো চ্যানেল সেভ নেই।"
    else:
        lines = [f"✅ **{len(channels)}টি** চ্যানেল সেভ আছে:"]
        for ch in channels:
            lines.append(f"• {ch['title']} (`{ch['id']}`)")
        status = "\n".join(lines)
    return f"📢 **চ্যানেল ম্যানেজমেন্ট**\n\n{status}"

# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════
def is_terabox_url(url: str) -> bool:
    url_lower = url.lower()
    return any(domain in url_lower for domain in TERABOX_DOMAINS)

def extract_terabox_url(text: str) -> str | None:
    if not text:
        return None
    for word in re.split(r'\s+', text):
        word = word.strip(".,;:!?\"'()[]")
        if word.startswith(("http://", "https://")) and is_terabox_url(word):
            return word
    return None

def format_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds//60}m {seconds%60}s"
    else:
        return f"{seconds//3600}h {(seconds%3600)//60}m"

def uptime_str() -> str:
    return format_duration(time.time() - BOT_START_TIME)

def get_progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return "▓" * length
    filled = int(length * current / total)
    bar = "▓" * filled + "░" * (length - filled)
    return bar

# ══════════════════════════════════════════════════════════════════════
# FFMPEG VIDEO REPAIR — ভিডিও প্লে না হওয়ার বাগ ফিক্স
# ══════════════════════════════════════════════════════════════════════
async def repair_video_ffmpeg(input_path: str, output_path: str) -> bool:
    """
    ffmpeg দিয়ে ভিডিও রিমাক্স করো — moov atom ঠিক করে streaming এনাবল করে।
    এটি ভিডিও প্লে না হওয়ার প্রধান কারণ ঠিক করে।
    """
    if not FFMPEG_AVAILABLE:
        return False
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-c", "copy",              # রি-এনকোড ছাড়া কপি
            "-movflags", "+faststart", # moov atom সামনে নিয়ে আসো (streaming fix)
            "-avoid_negative_ts", "make_zero",
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
        if proc.returncode == 0 and os.path.exists(output_path):
            if os.path.getsize(output_path) > MIN_VIDEO_SIZE:
                return True
        print(f"FFmpeg error: {stderr.decode()[:500]}", flush=True)
        return False
    except asyncio.TimeoutError:
        print("FFmpeg timeout!", flush=True)
        return False
    except Exception as e:
        print(f"FFmpeg exception: {e}", flush=True)
        return False

async def ensure_playable_video(path: str) -> str:
    """
    ভিডিও ফাইলটি প্লেযোগ্য কিনা চেক করো।
    প্রয়োজনে ffmpeg দিয়ে ঠিক করো।
    """
    if not path.lower().endswith(".mp4"):
        new_path = path.rsplit(".", 1)[0] + ".mp4"
        if os.path.exists(path):
            os.rename(path, new_path)
        path = new_path

    # moov atom চেক ও faststart ঠিক করা
    if FFMPEG_AVAILABLE:
        fixed_path = path + ".fixed.mp4"
        success = await repair_video_ffmpeg(path, fixed_path)
        if success:
            os.replace(fixed_path, path)
            print(f"✅ Video repaired with ffmpeg: {path}", flush=True)
        elif os.path.exists(fixed_path):
            os.remove(fixed_path)
    return path

# ══════════════════════════════════════════════════════════════════════
# TERABOX API
# ══════════════════════════════════════════════════════════════════════
async def get_terabox_info(url: str, api_key: str):
    if not api_key:
        return False, "Terabox API Key সেট করা নেই।"

    payload = {"url": url}
    headers = {"Content-Type": "application/json", "xAPIverse-Key": api_key}

    try:
        timeout = aiohttp.ClientTimeout(connect=15, total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(TERABOX_API_URL, json=payload, headers=headers) as resp:
                data = await resp.json()

        print(f"Terabox API response: {data}", flush=True)

        if not data or not isinstance(data, dict):
            return False, f"অপ্রত্যাশিত API রেসপন্স: {str(data)[:200]}"

        if data.get("status") in ("error", "fail") or data.get("error"):
            msg = data.get("message") or data.get("error") or "API এরর।"
            if "subscribe" in str(msg).lower():
                msg = (
                    "আপনার API Key এ Terabox API সাবস্ক্রাইব করা নেই।\n\n"
                    "সমাধান:\n"
                    "১. xapiverse.com এ লগিন করুন\n"
                    "২. Terabox API খুঁজে Subscribe করুন\n"
                    "৩. তারপর আবার চেষ্টা করুন"
                )
            return False, str(msg)

        file_list = data.get("list") or data.get("data") or []
        if isinstance(file_list, list) and len(file_list) > 0:
            results = []
            for item in file_list:
                dl_url = (
                    item.get("normal_dlink") or item.get("dlink")
                    or item.get("download_url") or item.get("url") or item.get("link")
                )
                zip_url = item.get("zip_dlink") or item.get("zip_url")
                fname = (
                    item.get("name") or item.get("file_name")
                    or item.get("filename") or "terabox_video.mp4"
                )
                if not fname.lower().endswith(VIDEO_EXTENSIONS):
                    fname = fname.rsplit(".", 1)[0] + ".mp4"
                if dl_url:
                    results.append({
                        "download_url": dl_url,
                        "zip_url": zip_url,
                        "file_name": fname,
                    })
            if results:
                return True, results

        dl_url = (
            data.get("normal_dlink") or data.get("dlink")
            or data.get("download_url") or data.get("url") or data.get("link")
        )
        if dl_url:
            fname = data.get("name") or data.get("file_name") or "terabox_video.mp4"
            if not fname.lower().endswith(VIDEO_EXTENSIONS):
                fname = fname.rsplit(".", 1)[0] + ".mp4"
            zip_url = data.get("zip_dlink") or data.get("zip_url")
            return True, [{"download_url": dl_url, "zip_url": zip_url, "file_name": fname}]

        return False, f"API রেসপন্সে ডাউনলোড লিংক পাওয়া যায়নি।\nRaw: {str(data)[:300]}"

    except aiohttp.ClientError as e:
        return False, f"API কানেকশন সমস্যা: {str(e)}"
    except Exception as e:
        return False, f"Terabox API এরর: {str(e)}"

# ══════════════════════════════════════════════════════════════════════
# ZIP HELPERS
# ══════════════════════════════════════════════════════════════════════
def find_videos_in_zip(extract_dir: str):
    videos = []
    for root, dirs, files in os.walk(extract_dir):
        for fname in files:
            if fname.lower().endswith(VIDEO_EXTENSIONS):
                full_path = os.path.join(root, fname)
                videos.append((full_path, fname))
    videos.sort(key=lambda x: os.path.getsize(x[0]), reverse=True)
    return videos

# ══════════════════════════════════════════════════════════════════════
# DOWNLOAD ENGINE
# ══════════════════════════════════════════════════════════════════════
async def download_file(url: str, save_path: str, status_msg, speed_tracking: bool = True):
    timeout = aiohttp.ClientTimeout(connect=30, sock_read=180, total=None)
    req_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    err = "অজানা সমস্যা।"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=req_headers) as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status != 200:
                        return False, f"সার্ভার {response.status} রেসপন্স দিয়েছে।"
                    content_type = response.headers.get("Content-Type", "")
                    if "text/html" in content_type:
                        return False, "এটি ডাইরেক্ট ডাউনলোড লিংক নয়, HTML পেজ।"
                    total_size = int(response.headers.get("Content-Length", 0))
                    if total_size > MAX_FILE_SIZE:
                        return False, f"ফাইলটি অনেক বড় ({format_size(total_size)})। সর্বোচ্চ ২ GB।"

                    downloaded = 0
                    last_update = time.time()
                    start_time = time.time()
                    speed_samples = []

                    with open(save_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                            f.write(chunk)
                            downloaded += len(chunk)
                            now = time.time()
                            elapsed = now - last_update
                            if elapsed >= 4:
                                # স্পিড ক্যালকুলেশন
                                total_elapsed = now - start_time
                                speed = downloaded / total_elapsed if total_elapsed > 0 else 0
                                speed_samples.append(speed)

                                dl_size = format_size(downloaded)
                                spd_str = format_size(int(speed)) + "/s"

                                if total_size > 0:
                                    pct = (downloaded / total_size) * 100
                                    tot_size = format_size(total_size)
                                    bar = get_progress_bar(downloaded, total_size)
                                    eta = (total_size - downloaded) / speed if speed > 0 else 0
                                    txt = (
                                        f"⬇️ **ডাউনলোড হচ্ছে...**\n"
                                        f"{bar} {pct:.0f}%\n"
                                        f"📦 {dl_size} / {tot_size}\n"
                                        f"⚡ {spd_str} | ⏱ ETA: {format_duration(eta)}"
                                    )
                                else:
                                    txt = (
                                        f"⬇️ **ডাউনলোড হচ্ছে...**\n"
                                        f"📦 {dl_size}\n"
                                        f"⚡ {spd_str}"
                                    )
                                try:
                                    await status_msg.edit_text(txt)
                                except Exception:
                                    pass
                                last_update = now

                    actual_size = os.path.getsize(save_path)
                    if actual_size == 0:
                        return False, "ডাউনলোড করা ফাইলটি খালি।"

                    # HTML error page চেক
                    with open(save_path, "rb") as f:
                        head = f.read(256).lower()
                    if head.startswith(b"<!") or b"<html" in head[:100]:
                        return False, "সার্ভার ভিডিওর বদলে HTML পেজ পাঠিয়েছে।"

                    if actual_size < MIN_VIDEO_SIZE:
                        return False, f"ডাউনলোড হওয়া ফাইল অনেক ছোট ({format_size(actual_size)})।"

                    if total_size > 0 and actual_size < total_size * 0.99:
                        return False, f"ফাইল অসম্পূর্ণ ({format_size(actual_size)}/{format_size(total_size)})।"

                    # Stats আপডেট
                    increment_stat("total_downloads")
                    increment_stat("total_bytes", actual_size)

                    return True, content_type

        except aiohttp.ClientConnectorError:
            err = "সার্ভারের সাথে কানেক্ট করা যাচ্ছে না।"
        except asyncio.TimeoutError:
            err = "কানেকশন টাইমআউট হয়েছে।"
        except Exception as e:
            err = str(e)

        if attempt < MAX_RETRIES:
            try:
                await status_msg.edit_text(
                    f"⚠️ চেষ্টা {attempt}/{MAX_RETRIES} ব্যর্থ: {err}\n🔄 আবার চেষ্টা করছি..."
                )
            except Exception:
                pass
            await asyncio.sleep(3 * attempt)
            if os.path.exists(save_path):
                os.remove(save_path)

    return False, f"{MAX_RETRIES} বার চেষ্টার পরও ব্যর্থ: {err}"

async def download_terabox_with_fallback(
    primary_url: str, fallback_url: str | None, save_path: str, status_msg
):
    ok, result = await download_file(primary_url, save_path, status_msg)
    if ok:
        return True, result
    if fallback_url and fallback_url != primary_url:
        print(f"Primary URL failed ({result}), trying fallback...", flush=True)
        try:
            await status_msg.edit_text("⚠️ মূল লিংক ব্যর্থ, বিকল্প লিংক দিয়ে চেষ্টা হচ্ছে...")
        except Exception:
            pass
        if os.path.exists(save_path):
            os.remove(save_path)
        ok2, result2 = await download_file(fallback_url, save_path, status_msg)
        if ok2:
            return True, result2
        return False, f"উভয় লিংক ব্যর্থ।\nমূল: {result}\nবিকল্প: {result2}"
    return False, result

# ══════════════════════════════════════════════════════════════════════
# VIDEO SENDER — with auto-repair
# ══════════════════════════════════════════════════════════════════════
async def send_video_file(
    client, message: Message, status_msg,
    file_path: str, caption: str,
    thumb_path: str | None = None,
):
    """
    ভিডিও পাঠানোর আগে:
    1. ffmpeg দিয়ে রিপেয়ার করো (প্লে না হওয়ার বাগ ফিক্স)
    2. আপলোড করো
    """
    try:
        await status_msg.edit_text("🔧 ভিডিও প্রসেস করা হচ্ছে...")
    except Exception:
        pass

    # ভিডিও রিপেয়ার/ফাস্টস্টার্ট
    file_path = await ensure_playable_video(file_path)
    size_mb = os.path.getsize(file_path) / (1024 * 1024)

    try:
        await status_msg.edit_text(
            f"✅ প্রসেস সম্পন্ন ({size_mb:.2f} MB)।\n⬆️ আপলোড হচ্ছে... 🚀"
        )
    except Exception:
        pass

    # থাম্বনেইল জেনারেট করার চেষ্টা (ffmpeg থেকে)
    auto_thumb = None
    if FFMPEG_AVAILABLE and not thumb_path:
        auto_thumb = file_path + "_thumb.jpg"
        try:
            cmd = [
                "ffmpeg", "-y", "-i", file_path,
                "-ss", "00:00:01", "-vframes", "1",
                "-vf", "scale=320:-1",
                auto_thumb
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)
            if not (os.path.exists(auto_thumb) and os.path.getsize(auto_thumb) > 100):
                auto_thumb = None
        except Exception:
            auto_thumb = None

    final_thumb = thumb_path or auto_thumb

    try:
        await client.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=caption,
            reply_to_message_id=message.id,
            supports_streaming=True,
            thumb=final_thumb,
        )
    finally:
        if auto_thumb and os.path.exists(auto_thumb):
            os.remove(auto_thumb)

    await status_msg.delete()

# ══════════════════════════════════════════════════════════════════════
# CHANNEL POST — ভিডিও আগে, ইমেজ পরে
# ══════════════════════════════════════════════════════════════════════
async def post_to_channels(
    client, user_id: int, channels: list, status_msg,
    photo_file_id=None,
    video_file_id=None,
    original_caption: str = "",
    downloaded_video_path: str | None = None,
    downloaded_video_name: str = "",
):
    """
    চ্যানেলে পোস্টের অর্ডার:
    ১. ডাউনলোড করা Terabox ভিডিও (VIDEO FIRST)
    ২. অরিজিনাল মিডিয়া (photo/video) — IMAGE LAST
    """
    success_count = 0
    fail_msgs = []

    for ch in channels:
        ch_id = ch["id"]
        ch_title = ch["title"]
        try:
            # ─── ১. প্রথমে ডাউনলোড করা ভিডিও পাঠাও ───────────────────────
            if downloaded_video_path and os.path.exists(downloaded_video_path):
                vid_path = await ensure_playable_video(downloaded_video_path)
                size_mb = os.path.getsize(vid_path) / (1024 * 1024)

                # চ্যানেল ভিডিওর জন্য থাম্বনেইল
                ch_thumb = None
                if FFMPEG_AVAILABLE:
                    ch_thumb = vid_path + f"_ch_thumb_{ch_id}.jpg"
                    try:
                        cmd = [
                            "ffmpeg", "-y", "-i", vid_path,
                            "-ss", "00:00:01", "-vframes", "1",
                            "-vf", "scale=320:-1", ch_thumb
                        ]
                        proc = await asyncio.create_subprocess_exec(
                            *cmd,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        await asyncio.wait_for(proc.communicate(), timeout=30)
                        if not (os.path.exists(ch_thumb) and os.path.getsize(ch_thumb) > 100):
                            ch_thumb = None
                    except Exception:
                        ch_thumb = None

                try:
                    await client.send_video(
                        chat_id=ch_id,
                        video=vid_path,
                        caption=f"🎬 {downloaded_video_name}\n📦 {size_mb:.2f} MB",
                        supports_streaming=True,
                        thumb=ch_thumb,
                    )
                finally:
                    if ch_thumb and os.path.exists(ch_thumb):
                        os.remove(ch_thumb)

                await asyncio.sleep(1)  # flood control

            # ─── ২. তারপর অরিজিনাল ইমেজ/ভিডিও পাঠাও ──────────────────────
            if photo_file_id:
                await client.send_photo(
                    chat_id=ch_id,
                    photo=photo_file_id,
                    caption=original_caption,
                )
            elif video_file_id:
                await client.send_video(
                    chat_id=ch_id,
                    video=video_file_id,
                    caption=original_caption,
                    supports_streaming=True,
                )

            success_count += 1

        except Exception as e:
            fail_msgs.append(f"❌ {ch_title}: {str(e)}")
            print(f"Channel post error ({ch_title}): {e}", flush=True)

    return success_count, fail_msgs

# ══════════════════════════════════════════════════════════════════════
# COMMANDS
# ══════════════════════════════════════════════════════════════════════

@app.on_message(filters.command("start"))
async def start_cmd(client, message: Message):
    user_id = message.from_user.id
    name = message.from_user.first_name or "বন্ধু"

    # ইউজার কাউন্ট আপডেট
    stats = load_stats()
    all_data = load_data()
    if str(user_id) not in all_data:
        increment_stat("total_users")

    await message.reply_text(
        f"🎉 স্বাগতম, **{name}**!\n\n"
        "আমি একটি প্রিমিয়াম ভিডিও ডাউনলোডার বট। "
        "নিচের যেকোনো ধরনের লিংক পাঠান:\n\n"
        "🎬 ডাইরেক্ট MP4/ভিডিও লিংক\n"
        "📦 ZIP ফাইল লিংক (ভেতরে MP4 থাকলে)\n"
        "☁️ Terabox লিংক\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 **কমান্ড তালিকা:**\n"
        "/api — Terabox API Key ম্যানেজ\n"
        "/channel — চ্যানেল ম্যানেজ\n"
        "/backup — ডেটা ব্যাকআপ ডাউনলোড\n"
        "/stats — বটের পরিসংখ্যান\n"
        "/help — বিস্তারিত সাহায্য\n"
        "/cancel — চলমান অপারেশন বাতিল\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "আমি ডাউনলোড করে ভিডিও হিসেবে পাঠিয়ে দেবো। 🚀"
    )

@app.on_message(filters.command("help"))
async def help_cmd(client, message: Message):
    await message.reply_text(
        "📖 **বিস্তারিত সাহায্য**\n\n"
        "**🎬 ভিডিও ডাউনলোড:**\n"
        "যেকোনো ডাইরেক্ট MP4 বা Terabox লিংক পাঠান। "
        "বট স্বয়ংক্রিয়ভাবে ডাউনলোড করে আপনার কাছে পাঠাবে।\n\n"
        "**☁️ Terabox:**\n"
        "Terabox লিংকের জন্য API Key দরকার। "
        "xapiverse.com থেকে ফ্রিতে পাবেন। /api দিয়ে সেট করুন।\n\n"
        "**📢 চ্যানেলে অটো পোস্ট:**\n"
        "১. /channel দিয়ে চ্যানেল যোগ করুন\n"
        "২. বটকে চ্যানেলের Admin করুন\n"
        "৩. Terabox লিংকসহ ছবি/ভিডিও ফরওয়ার্ড করুন\n"
        "বট ভিডিও ডাউনলোড করে চ্যানেলে পোস্ট করবে!\n\n"
        "**💾 ব্যাকআপ:**\n"
        "/backup — আপনার সব ডেটা ZIP করে পাঠাবে\n"
        "ব্যাকআপ রিস্টোর করতে ZIP ফাইল পাঠান।\n\n"
        "**⚡ ফিচার:**\n"
        "• ভিডিও প্লে বাগ অটো-ফিক্স (ffmpeg)\n"
        "• স্বয়ংক্রিয় থাম্বনেইল\n"
        "• ডাউনলোড স্পিড ও ETA দেখানো\n"
        "• একাধিক API Key সাপোর্ট\n"
        "• ZIP ফাইল থেকে ভিডিও বের করা"
    )

@app.on_message(filters.command("api"))
async def api_cmd(client, message: Message):
    user_id = message.from_user.id
    await message.reply_text(
        api_menu_text(user_id),
        reply_markup=api_main_keyboard(user_id),
    )

@app.on_message(filters.command("channel"))
async def channel_cmd(client, message: Message):
    user_id = message.from_user.id
    await message.reply_text(
        channel_menu_text(user_id),
        reply_markup=channel_main_keyboard(user_id),
    )

@app.on_message(filters.command("cancel"))
async def cancel_cmd(client, message: Message):
    user_id = message.from_user.id
    if user_id in waiting_state:
        waiting_state.pop(user_id, None)
        await message.reply_text("❌ বাতিল করা হয়েছে।")
    else:
        await message.reply_text("⚠️ কোনো সক্রিয় অপারেশন নেই।")

@app.on_message(filters.command("stats"))
async def stats_cmd(client, message: Message):
    stats = load_stats()
    all_data = load_data()
    channel_data = load_channels()

    total_users = len(all_data)
    total_channels = sum(len(v) for v in channel_data.values())
    total_dl = stats.get("total_downloads", 0)
    total_bytes = stats.get("total_bytes", 0)

    # আজকের স্ট্যাট
    today = datetime.now().strftime("%Y-%m-%d")
    today_stats = stats.get("daily", {}).get(today, {})
    today_dl = today_stats.get("downloads", 0)
    today_bytes = today_stats.get("bytes", 0)

    await message.reply_text(
        "📊 **বট পরিসংখ্যান**\n\n"
        f"⏱ আপটাইম: `{uptime_str()}`\n"
        f"👥 মোট ইউজার: `{total_users}`\n"
        f"📢 মোট চ্যানেল: `{total_channels}`\n\n"
        "**🔄 সর্বকালীন:**\n"
        f"⬇️ ডাউনলোড: `{total_dl}`\n"
        f"📦 ডেটা: `{format_size(total_bytes)}`\n\n"
        "**📅 আজকে:**\n"
        f"⬇️ ডাউনলোড: `{today_dl}`\n"
        f"📦 ডেটা: `{format_size(today_bytes)}`\n\n"
        f"🔧 FFmpeg: `{'✅ সক্রিয়' if FFMPEG_AVAILABLE else '❌ নেই'}`"
    )

@app.on_message(filters.command("backup"))
async def backup_cmd(client, message: Message):
    user_id = message.from_user.id
    status = await message.reply_text("📦 ব্যাকআপ তৈরি করা হচ্ছে...")
    try:
        backup_path = create_backup_zip()
        size = os.path.getsize(backup_path)
        await status.edit_text(f"✅ ব্যাকআপ তৈরি ({format_size(size)})। পাঠানো হচ্ছে...")
        await client.send_document(
            chat_id=message.chat.id,
            document=backup_path,
            caption=(
                "💾 **বট ডেটা ব্যাকআপ**\n\n"
                f"🕐 সময়: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"📦 আকার: {format_size(size)}\n\n"
                "এই ফাইলটি নিরাপদে রাখুন। "
                "রিস্টোর করতে এই ZIP ফাইলটি আবার বটে পাঠান।"
            ),
            reply_to_message_id=message.id,
        )
        await status.delete()
    except Exception as e:
        await status.edit_text(f"❌ ব্যাকআপ ব্যর্থ: {str(e)}")
    finally:
        if "backup_path" in locals() and os.path.exists(backup_path):
            os.remove(backup_path)

# Admin-only broadcast
@app.on_message(filters.command("broadcast"))
async def broadcast_cmd(client, message: Message):
    user_id = message.from_user.id
    if user_id not in ADMIN_IDS:
        await message.reply_text("❌ শুধুমাত্র Admin ব্যবহার করতে পারবেন।")
        return
    if not message.reply_to_message:
        await message.reply_text("⚠️ যে মেসেজটি ব্রডকাস্ট করবেন সেটিতে Reply করে /broadcast দিন।")
        return

    all_data = load_data()
    user_ids = list(all_data.keys())
    status = await message.reply_text(f"📢 {len(user_ids)} জন ইউজারকে পাঠানো হচ্ছে...")

    sent = 0
    failed = 0
    for uid_str in user_ids:
        try:
            await message.reply_to_message.forward(int(uid_str))
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    await status.edit_text(
        f"✅ ব্রডকাস্ট সম্পন্ন!\n"
        f"📤 পাঠানো: {sent}\n"
        f"❌ ব্যর্থ: {failed}"
    )

# ══════════════════════════════════════════════════════════════════════
# CALLBACK QUERIES
# ══════════════════════════════════════════════════════════════════════
@app.on_callback_query()
async def callback_handler(client, callback: CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data

    # ── API Callbacks ──────────────────────────────────────────────
    if data == "api_menu":
        await callback.message.edit_text(
            api_menu_text(user_id), reply_markup=api_main_keyboard(user_id)
        )

    elif data == "api_add":
        waiting_state[user_id] = {"step": "label"}
        await callback.message.edit_text(
            "✏️ **নতুন API Key এর নাম দিন**\n\n"
            "প্রথমে একটি নাম পাঠান (যেমন: `personal`, `work`, `mykey1`)\n"
            "বাতিল করতে /cancel লিখুন।",
            reply_markup=None,
        )

    elif data == "api_list":
        udata = get_user_data(user_id)
        keys = udata.get("keys", {})
        active = udata.get("active")
        if not keys:
            text = "📋 কোনো API Key সেভ নেই।"
        else:
            lines = ["📋 **আপনার সব API Key:**\n"]
            for label, key_val in keys.items():
                mark = "🟢 " if label == active else "⚪️ "
                lines.append(f"{mark}**{label}**: `{mask_key(key_val)}`")
            text = "\n".join(lines)
        await callback.message.edit_text(text, reply_markup=back_api_keyboard())

    elif data == "api_switch":
        udata = get_user_data(user_id)
        if not udata.get("keys"):
            await callback.message.edit_text("❌ কোনো Key নেই।", reply_markup=back_api_keyboard())
        else:
            await callback.message.edit_text(
                "🔄 **কোন Key Active করবেন?**\n✅ চিহ্নিতটি এখন Active।",
                reply_markup=keys_select_keyboard(user_id, "switch"),
            )

    elif data.startswith("switch:"):
        label = data.split(":", 1)[1]
        set_active_key(user_id, label)
        await callback.message.edit_text(
            f"✅ **{label}** এখন Active Key।",
            reply_markup=back_api_keyboard(),
        )

    elif data == "api_delete_list":
        udata = get_user_data(user_id)
        if not udata.get("keys"):
            await callback.message.edit_text("❌ কোনো Key নেই।", reply_markup=back_api_keyboard())
        else:
            await callback.message.edit_text(
                "🗑️ **কোন Key মুছতে চান?**",
                reply_markup=keys_select_keyboard(user_id, "del"),
            )

    elif data.startswith("del:"):
        label = data.split(":", 1)[1]
        delete_user_key(user_id, label)
        udata = get_user_data(user_id)
        await callback.message.edit_text(
            f"🗑️ **{label}** মুছে ফেলা হয়েছে।",
            reply_markup=(
                keys_select_keyboard(user_id, "del")
                if udata.get("keys") else back_api_keyboard()
            ),
        )

    elif data == "api_help":
        await callback.message.edit_text(
            "❓ **Terabox API Key কোথায় পাবেন?**\n\n"
            "১. [xapiverse.com](https://xapiverse.com) এ যান\n"
            "২. রেজিস্ট্রেশন করুন\n"
            "৩. Dashboard থেকে API Key কপি করুন\n"
            "৪. বটে /api দিয়ে **➕ নতুন API Key যোগ করুন** চাপুন",
            reply_markup=back_api_keyboard(),
        )

    # ── Channel Callbacks ──────────────────────────────────────────
    elif data == "ch_menu":
        await callback.message.edit_text(
            channel_menu_text(user_id), reply_markup=channel_main_keyboard(user_id)
        )

    elif data == "ch_add":
        waiting_state[user_id] = {"step": "add_channel"}
        await callback.message.edit_text(
            "📢 **চ্যানেল যোগ করুন**\n\n"
            "দুটি উপায়ে চ্যানেল যোগ করতে পারবেন:\n\n"
            "১. চ্যানেল থেকে যেকোনো পোস্ট **ফরওয়ার্ড** করুন\n"
            "২. চ্যানেলের **ID** পাঠান (যেমন: `-1001234567890`)\n\n"
            "⚠️ বটকে অবশ্যই চ্যানেলের Admin করতে হবে।\n"
            "বাতিল করতে /cancel লিখুন।",
            reply_markup=None,
        )

    elif data == "ch_list":
        channels = get_user_channels(user_id)
        if not channels:
            text = "📋 কোনো চ্যানেল সেভ নেই।"
        else:
            lines = ["📋 **সেভ করা চ্যানেলগুলো:**\n"]
            for ch in channels:
                lines.append(f"• **{ch['title']}**\nID: `{ch['id']}`")
            text = "\n\n".join(lines)
        await callback.message.edit_text(text, reply_markup=back_ch_keyboard())

    elif data == "ch_delete_list":
        channels = get_user_channels(user_id)
        if not channels:
            await callback.message.edit_text("❌ কোনো চ্যানেল নেই।", reply_markup=back_ch_keyboard())
        else:
            await callback.message.edit_text(
                "🗑️ **কোন চ্যানেল মুছতে চান?**",
                reply_markup=channel_delete_keyboard(user_id),
            )

    elif data.startswith("ch_del:"):
        idx = int(data.split(":", 1)[1])
        delete_user_channel(user_id, idx)
        channels = get_user_channels(user_id)
        await callback.message.edit_text(
            "🗑️ চ্যানেল মুছে ফেলা হয়েছে।",
            reply_markup=(
                channel_delete_keyboard(user_id) if channels else back_ch_keyboard()
            ),
        )

    await callback.answer()

# ══════════════════════════════════════════════════════════════════════
# DOCUMENT HANDLER — ZIP ব্যাকআপ রিস্টোর
# ══════════════════════════════════════════════════════════════════════
@app.on_message(filters.document)
async def handle_document(client, message: Message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    doc = message.document

    # ZIP ফাইল → ব্যাকআপ রিস্টোর
    if doc.file_name and doc.file_name.lower().endswith(".zip"):
        status = await message.reply_text(
            "📦 ZIP ফাইল পাওয়া গেছে।\n"
            "এটি কি ব্যাকআপ রিস্টোর করবেন?\n\n"
            "রিস্টোর করতে নিচের বাটন চাপুন:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ হ্যাঁ, রিস্টোর করুন", callback_data=f"restore:{message.id}")],
                [InlineKeyboardButton("❌ না, বাতিল", callback_data="restore_cancel")],
            ]),
        )
        # ZIP ডাউনলোড করে রাখো
        zip_tmp = f"/tmp/restore_{user_id}_{message.id}.zip"
        await message.download(zip_tmp)
        return

    await message.reply_text(
        "❌ শুধুমাত্র ZIP ফাইল সাপোর্ট করা হয় (ব্যাকআপ রিস্টোরের জন্য)।\n"
        "ভিডিও লিংক পাঠান ডাউনলোড করতে।"
    )

@app.on_callback_query(filters.regex(r"^restore:"))
async def restore_callback(client, callback: CallbackQuery):
    user_id = callback.from_user.id
    msg_id = callback.data.split(":")[1]
    zip_tmp = f"/tmp/restore_{user_id}_{msg_id}.zip"

    if not os.path.exists(zip_tmp):
        await callback.message.edit_text("❌ ফাইলটি আর নেই। আবার পাঠান।")
        return

    success, msg = restore_from_backup(zip_tmp)
    await callback.message.edit_text(msg)
    os.remove(zip_tmp)
    await callback.answer()

@app.on_callback_query(filters.regex(r"^restore_cancel$"))
async def restore_cancel(client, callback: CallbackQuery):
    user_id = callback.from_user.id
    # temp ফাইল মুছো
    for f in os.listdir("/tmp"):
        if f.startswith(f"restore_{user_id}_"):
            os.remove(f"/tmp/{f}")
    await callback.message.edit_text("❌ রিস্টোর বাতিল করা হয়েছে।")
    await callback.answer()

# ══════════════════════════════════════════════════════════════════════
# FORWARDED MEDIA HANDLER
# ══════════════════════════════════════════════════════════════════════
@app.on_message(filters.forwarded & (filters.photo | filters.video))
async def handle_forwarded_media(client, message: Message):
    if not message.from_user:
        return
    user_id = message.from_user.id

    # চ্যানেল যোগের মোডে আছে?
    if user_id in waiting_state and waiting_state[user_id].get("step") == "add_channel":
        waiting_state.pop(user_id, None)
        fwd_chat = message.forward_from_chat
        if not fwd_chat:
            await message.reply_text(
                "❌ এই পোস্ট থেকে চ্যানেল ID পাওয়া যায়নি।\n"
                "চ্যানেলের Privacy setting বন্ধ থাকতে পারে।\n"
                "চ্যানেল ID সরাসরি পাঠান।",
                reply_markup=channel_main_keyboard(user_id),
            )
            return
        added = add_user_channel(user_id, fwd_chat.id, fwd_chat.title or str(fwd_chat.id))
        if added:
            await message.reply_text(
                f"✅ **{fwd_chat.title}** চ্যানেল সেভ হয়েছে!\n"
                f"ID: `{fwd_chat.id}`\n\n"
                "এখন Terabox+মিডিয়া পোস্ট ফরওয়ার্ড করলে এই চ্যানেলে পোস্ট হবে।",
                reply_markup=channel_main_keyboard(user_id),
            )
        else:
            await message.reply_text(
                f"⚠️ **{fwd_chat.title}** চ্যানেল আগেই সেভ আছে।",
                reply_markup=channel_main_keyboard(user_id),
            )
        return

    # Terabox লিংক আছে?
    caption = message.caption or ""
    terabox_url = extract_terabox_url(caption)
    if not terabox_url:
        return  # Terabox লিংক নেই

    channels = get_user_channels(user_id)
    if not channels:
        await message.reply_text(
            "❌ কোনো চ্যানেল সেভ নেই।\n"
            "/channel দিয়ে চ্যানেল যোগ করুন।"
        )
        return

    status_msg = await message.reply_text(
        f"📢 Terabox পোস্ট শনাক্ত হয়েছে!\n"
        f"🔄 {len(channels)}টি চ্যানেলে পোস্ট করা হবে..."
    )

    uid = f"{user_id}_{int(time.time())}"
    active_key = get_active_key(user_id) or DEFAULT_TERABOX_KEY

    photo_file_id = None
    video_file_id = None
    if message.photo:
        photo_file_id = message.photo.file_id
    elif message.video:
        video_file_id = message.video.file_id

    await status_msg.edit_text("☁️ Terabox ভিডিও ডাউনলোড হচ্ছে...")
    ok, info = await get_terabox_info(terabox_url, active_key)
    if not ok:
        await status_msg.edit_text(
            f"❌ Terabox ডাউনলোড ব্যর্থ!\n{info}\n\n"
            "💡 নিজের API Key যোগ করতে /api দিন।"
        )
        return

    total_files = len(info)
    posted_channels = 0

    for i, file_info in enumerate(info, 1):
        dl_url    = file_info["download_url"]
        zip_url   = file_info.get("zip_url")
        file_name = file_info["file_name"]
        dl_path   = f"ch_{uid}_{i}.mp4"

        try:
            await status_msg.edit_text(
                f"⬇️ ডাউনলোড হচ্ছে ({i}/{total_files}): {file_name}"
            )
            success, result = await download_terabox_with_fallback(
                dl_url, zip_url, dl_path, status_msg
            )
            if not success:
                await status_msg.edit_text(f"❌ ডাউনলোড ব্যর্থ: {result}")
                continue

            await status_msg.edit_text(
                f"⬆️ {len(channels)}টি চ্যানেলে পোস্ট হচ্ছে..."
            )

            send_original = (i == 1)
            ok_count, fail_list = await post_to_channels(
                client, user_id, channels, status_msg,
                photo_file_id=photo_file_id if send_original else None,
                video_file_id=video_file_id if send_original else None,
                original_caption=caption if send_original else "",
                downloaded_video_path=dl_path,
                downloaded_video_name=file_name,
            )
            posted_channels += ok_count

            if fail_list:
                for fm in fail_list:
                    print(fm, flush=True)

        finally:
            if os.path.exists(dl_path):
                os.remove(dl_path)

    ch_names = ", ".join(ch["title"] for ch in channels)
    await status_msg.edit_text(
        f"✅ **সম্পন্ন!**\n\n"
        f"📢 চ্যানেল: {ch_names}\n"
        f"🎬 পোস্ট করা হয়েছে: {total_files}টি ভিডিও"
    )

# ══════════════════════════════════════════════════════════════════════
# TEXT HANDLER (URL + State machine)
# ══════════════════════════════════════════════════════════════════════
@app.on_message(filters.text & ~filters.regex(r"^/"))
async def handle_text(client, message: Message):
    if not message.from_user:
        return
    user_id = message.from_user.id
    text = message.text.strip()

    # ── Waiting state ─────────────────────────────────────────────
    if user_id in waiting_state:
        state = waiting_state[user_id]

        # API Key: ধাপ ১ — নাম
        if state["step"] == "label":
            label = text.strip()
            if len(label) < 1 or len(label) > 30:
                await message.reply_text(
                    "❌ নামটি ১–৩০ অক্ষরের মধ্যে হতে হবে। আবার লিখুন।\n"
                    "বাতিল করতে /cancel।"
                )
                return
            waiting_state[user_id] = {"step": "key", "label": label}
            await message.reply_text(
                f"✅ নাম: **{label}**\n\n"
                "এখন xapiverse.com এর API Key পাঠান:\n"
                "বাতিল করতে /cancel।"
            )
            return

        # API Key: ধাপ ২ — key
        elif state["step"] == "key":
            api_key = text.strip()
            label = state.get("label")
            waiting_state.pop(user_id, None)
            if len(api_key) < 10:
                await message.reply_text(
                    "❌ API Key টি সঠিক মনে হচ্ছে না।\nআবার /api দিয়ে চেষ্টা করুন।"
                )
                return
            if not label:
                udata = get_user_data(user_id)
                label = f"API {len(udata.get('keys', {})) + 1}"
            add_user_key(user_id, label, api_key)
            await message.reply_text(
                f"✅ **API Key সফলভাবে সেভ হয়েছে!**\n\n"
                f"🏷️ নাম: **{label}**\n"
                f"🔑 Key: `{mask_key(api_key)}`\n\n"
                "এখন এই Key টি Active আছে।",
                reply_markup=api_main_keyboard(user_id),
            )
            return

        # চ্যানেল যোগ
        elif state["step"] == "add_channel":
            if message.forward_from_chat:
                waiting_state.pop(user_id, None)
                fwd_chat = message.forward_from_chat
                added = add_user_channel(user_id, fwd_chat.id, fwd_chat.title or str(fwd_chat.id))
                if added:
                    await message.reply_text(
                        f"✅ **{fwd_chat.title}** চ্যানেল সেভ হয়েছে!\n"
                        f"ID: `{fwd_chat.id}`",
                        reply_markup=channel_main_keyboard(user_id),
                    )
                else:
                    await message.reply_text(
                        "⚠️ এই চ্যানেল আগেই সেভ আছে।",
                        reply_markup=channel_main_keyboard(user_id),
                    )
                return

            channel_input = text.strip()
            waiting_state.pop(user_id, None)
            try:
                channel_id = int(channel_input)
                title = f"Channel {channel_id}"
            except ValueError:
                channel_id = channel_input
                title = channel_input

            added = add_user_channel(user_id, channel_id, title)
            if added:
                await message.reply_text(
                    f"✅ চ্যানেল সেভ হয়েছে!\n"
                    f"ID: `{channel_id}`\n\n"
                    "⚠️ নিশ্চিত করুন বটকে চ্যানেলের Admin করা হয়েছে।",
                    reply_markup=channel_main_keyboard(user_id),
                )
            else:
                await message.reply_text(
                    "⚠️ এই চ্যানেল আগেই সেভ আছে।",
                    reply_markup=channel_main_keyboard(user_id),
                )
            return

    # ── URL হ্যান্ডেলিং ──────────────────────────────────────────
    if not (text.startswith("http://") or text.startswith("https://")):
        await message.reply_text(
            "❌ সঠিক URL দিন (http:// বা https:// দিয়ে শুরু)।\n"
            "অথবা /help দিয়ে সাহায্য দেখুন।"
        )
        return

    url = text
    status_msg = await message.reply_text("⏳ লিংকটি চেক করা হচ্ছে...")

    uid      = f"{user_id}_{int(time.time())}"
    temp_dir = f"temp_{uid}"
    zip_path = f"{temp_dir}.zip"
    mp4_path = f"video_{uid}.mp4"
    temp_dl  = f"dl_{uid}.tmp"

    try:
        # ── Terabox ──────────────────────────────────────────────
        if is_terabox_url(url):
            active_key = get_active_key(user_id) or DEFAULT_TERABOX_KEY
            udata = get_user_data(user_id)
            active_label = udata.get("active")
            key_label = f"🔑 {active_label}" if get_active_key(user_id) else "🌐 ডিফল্ট API"

            await status_msg.edit_text(
                f"☁️ Terabox লিংক শনাক্ত হয়েছে!\n"
                f"ব্যবহার হচ্ছে: {key_label}\n"
                "🔍 তথ্য সংগ্রহ করা হচ্ছে..."
            )

            ok, info = await get_terabox_info(url, active_key)
            if not ok:
                await status_msg.edit_text(
                    f"❌ Terabox লিংক প্রসেস করতে ব্যর্থ!\n{info}\n\n"
                    "💡 নিজের API Key যোগ করতে /api দিন।"
                )
                return

            total = len(info)
            for i, file_info in enumerate(info, 1):
                dl_url    = file_info["download_url"]
                zip_url   = file_info.get("zip_url")
                file_name = file_info["file_name"]
                dl_path   = f"terabox_{uid}_{i}.mp4"

                await status_msg.edit_text(
                    f"📄 ফাইল ({i}/{total}): {file_name}\n⬇️ ডাউনলোড শুরু হচ্ছে..."
                )
                success, result = await download_terabox_with_fallback(
                    dl_url, zip_url, dl_path, status_msg
                )
                if not success:
                    await status_msg.edit_text(f"❌ ডাউনলোড ব্যর্থ ({file_name})!\n{result}")
                    continue

                try:
                    size_mb = os.path.getsize(dl_path) / (1024 * 1024)
                    await send_video_file(
                        client, message, status_msg, dl_path,
                        f"☁️ **Terabox:** {file_name}\n📦 {size_mb:.2f} MB"
                        + (f" ({i}/{total})" if total > 1 else "")
                    )
                finally:
                    if os.path.exists(dl_path):
                        os.remove(dl_path)
            return

        # ── সাধারণ লিংক ──────────────────────────────────────────
        await status_msg.edit_text("⬇️ ডাউনলোড শুরু হচ্ছে...")
        success, result = await download_file(url, temp_dl, status_msg)

        if not success:
            await status_msg.edit_text(f"❌ ডাউনলোড ব্যর্থ!\n{result}")
            return

        content_type = result
        url_lower = url.lower().split("?")[0]
        is_zip = (
            url_lower.endswith(".zip")
            or "application/zip" in content_type
            or "application/x-zip" in content_type
        )
        if not is_zip:
            with open(temp_dl, "rb") as f:
                magic = f.read(4)
            if magic[:2] == b"PK":
                is_zip = True

        if is_zip:
            os.rename(temp_dl, zip_path)
            await status_msg.edit_text("📦 ZIP ফাইল পাওয়া গেছে। আনজিপ করা হচ্ছে...")
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    names = zf.namelist()
                    video_names = [n for n in names if n.lower().endswith(VIDEO_EXTENSIONS)]
                    if not video_names:
                        await status_msg.edit_text(
                            "❌ ZIP এর ভেতরে কোনো ভিডিও নেই।\n"
                            f"ফাইলগুলো: {', '.join(names[:10])}"
                        )
                        return
                    os.makedirs(temp_dir, exist_ok=True)
                    zf.extractall(temp_dir)
            except zipfile.BadZipFile:
                await status_msg.edit_text("❌ ফাইলটি সঠিক ZIP ফরম্যাটে নেই।")
                return

            videos = find_videos_in_zip(temp_dir)
            if not videos:
                await status_msg.edit_text("❌ ZIP আনজিপ করার পরেও কোনো ভিডিও পাওয়া যায়নি।")
                return

            total_videos = len(videos)
            await status_msg.edit_text(
                f"✅ {total_videos}টি ভিডিও পাওয়া গেছে।\n⬆️ আপলোড শুরু হচ্ছে..."
            )
            for i, (video_path, video_fname) in enumerate(videos, 1):
                size_mb = os.path.getsize(video_path) / (1024 * 1024)
                try:
                    await status_msg.edit_text(
                        f"🔧 প্রসেস হচ্ছে ({i}/{total_videos}): {video_fname}"
                    )
                except Exception:
                    pass
                # ভিডিও রিপেয়ার
                video_path = await ensure_playable_video(video_path)

                # থাম্বনেইল
                auto_thumb = None
                if FFMPEG_AVAILABLE:
                    auto_thumb = video_path + "_thumb.jpg"
                    try:
                        cmd = [
                            "ffmpeg", "-y", "-i", video_path,
                            "-ss", "00:00:01", "-vframes", "1",
                            "-vf", "scale=320:-1", auto_thumb
                        ]
                        proc = await asyncio.create_subprocess_exec(
                            *cmd,
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                        )
                        await asyncio.wait_for(proc.communicate(), timeout=30)
                        if not (os.path.exists(auto_thumb) and os.path.getsize(auto_thumb) > 100):
                            auto_thumb = None
                    except Exception:
                        auto_thumb = None

                try:
                    await client.send_video(
                        chat_id=message.chat.id,
                        video=video_path,
                        caption=f"🎬 {video_fname}\n📦 {size_mb:.2f} MB ({i}/{total_videos})",
                        reply_to_message_id=message.id,
                        supports_streaming=True,
                        thumb=auto_thumb,
                    )
                finally:
                    if auto_thumb and os.path.exists(auto_thumb):
                        os.remove(auto_thumb)

            await status_msg.delete()

        else:
            os.rename(temp_dl, mp4_path)
            size_mb = os.path.getsize(mp4_path) / (1024 * 1024)
            await send_video_file(
                client, message, status_msg, mp4_path,
                f"✅ ডাউনলোড সম্পন্ন!\n📦 {size_mb:.2f} MB"
            )

    except Exception as e:
        print(f"Error: {e}", flush=True)
        traceback.print_exc()
        try:
            await status_msg.edit_text(f"⚠️ একটি সমস্যা হয়েছে:\n{str(e)}")
        except Exception:
            pass
    finally:
        for path in [temp_dl, zip_path, mp4_path]:
            if os.path.exists(path):
                os.remove(path)
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("✅ Bot v2.0 starting...", flush=True)
    print(f"🔧 FFmpeg: {'✅ Available' if FFMPEG_AVAILABLE else '❌ Not found'}", flush=True)

    keep_alive()

    app.start()
    print("🤖 Bot started and listening for messages...", flush=True)

    try:
        idle()
    except KeyboardInterrupt:
        print("🛑 Bot stopped manually")

    app.stop()
