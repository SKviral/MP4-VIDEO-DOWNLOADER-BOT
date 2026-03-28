import os
import sys
import re
import json
import time
import aiohttp
import asyncio
import zipfile
import shutil
import traceback
from pyrogram import Client, filters
from pyrogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from keep_alive import keep_alive

print("⏳ Bot starting...", flush=True)

try:
    API_ID_STR = os.environ.get("API_ID", "").strip()
    API_HASH   = os.environ.get("API_HASH", "").strip()
    BOT_TOKEN  = os.environ.get("BOT_TOKEN", "").strip()
    DEFAULT_TERABOX_KEY = os.environ.get("TERABOX_API_KEY", "").strip()

    if not API_ID_STR or not API_HASH or not BOT_TOKEN:
        print("❌ ERROR: API_ID, API_HASH বা BOT_TOKEN সেট করা নেই!", flush=True)
        sys.exit(1)

    try:
        API_ID = int(API_ID_STR)
    except ValueError:
        print("❌ ERROR: API_ID শুধুমাত্র সংখ্যা হতে হবে!", flush=True)
        sys.exit(1)

    app = Client("video_downloader", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

    # ── Constants ─────────────────────────────────────────────────────────
    CHUNK_SIZE       = 2 * 1024 * 1024
    MAX_FILE_SIZE    = 2 * 1024 * 1024 * 1024
    MIN_VIDEO_SIZE   = 10 * 1024   # ১০ KB — এর চেয়ে ছোট হলে ভিডিও নয়
    MAX_RETRIES      = 3
    VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v")
    USER_API_FILE    = "user_apis.json"
    CHANNEL_FILE     = "user_channels.json"
    TERABOX_API_URL  = "https://xapiverse.com/api/terabox"

    TERABOX_DOMAINS = (
        "terabox.com", "1024terabox.com", "teraboxapp.com",
        "freeterabox.com", "4funbox.co", "mirrobox.com",
        "momerybox.com", "tibibox.com", "nephobox.com", "terabox.app",
    )

    # ── State tracking ────────────────────────────────────────────────────
    # { user_id: {"step": "key"|"add_channel"} }
    waiting_state: dict = {}

    # ════════════════════════════════════════════════════════════════════════
    # USER API STORAGE
    # ════════════════════════════════════════════════════════════════════════

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

    # ════════════════════════════════════════════════════════════════════════
    # CHANNEL STORAGE
    # ════════════════════════════════════════════════════════════════════════
    # ফরম্যাট: {"user_id":[{"id": -1001234, "title": "Channel Name"}]}

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
        return data.get(str(user_id),[])

    def add_user_channel(user_id: int, channel_id, title: str) -> bool:
        data = load_channels()
        uid = str(user_id)
        if uid not in data:
            data[uid] =[]
        # duplicate চেক — int ও string উভয় ফরম্যাটে তুলনা
        for ch in data[uid]:
            if str(ch["id"]) == str(channel_id):
                return False  # ইতিমধ্যেই আছে
        data[uid].append({"id": channel_id, "title": title})
        save_channels(data)
        return True

    def delete_user_channel(user_id: int, index: int):
        data = load_channels()
        uid = str(user_id)
        if uid in data and 0 <= index < len(data[uid]):
            data[uid].pop(index)
            save_channels(data)

    # ════════════════════════════════════════════════════════════════════════
    # KEYBOARDS — API
    # ════════════════════════════════════════════════════════════════════════

    def api_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
        udata = get_user_data(user_id)
        keys = udata.get("keys", {})
        buttons = [[InlineKeyboardButton("➕ নতুন API Key যোগ করুন", callback_data="api_add")],
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
        buttons =[]
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

    # ════════════════════════════════════════════════════════════════════════
    # KEYBOARDS — CHANNEL
    # ════════════════════════════════════════════════════════════════════════

    def channel_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
        channels = get_user_channels(user_id)
        buttons = [[InlineKeyboardButton("➕ চ্যানেল যোগ করুন", callback_data="ch_add")],
        ]
        if channels:
            buttons.append([InlineKeyboardButton("📋 সেভ করা চ্যানেল দেখুন", callback_data="ch_list")])
            buttons.append([InlineKeyboardButton("🗑️ চ্যানেল মুছুন", callback_data="ch_delete_list")])
        return InlineKeyboardMarkup(buttons)

    def channel_delete_keyboard(user_id: int) -> InlineKeyboardMarkup:
        channels = get_user_channels(user_id)
        buttons =[]
        for i, ch in enumerate(channels):
            buttons.append([InlineKeyboardButton(
                f"🗑️ {ch['title']}", callback_data=f"ch_del:{i}"
            )])
        buttons.append([InlineKeyboardButton("🔙 পিছনে যান", callback_data="ch_menu")])
        return InlineKeyboardMarkup(buttons)

    def back_ch_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 পিছনে যান", callback_data="ch_menu")]
        ])

    def back_api_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 পিছনে যান", callback_data="api_menu")]
        ])

    def channel_menu_text(user_id: int) -> str:
        channels = get_user_channels(user_id)
        if not channels:
            status = "❌ কোনো চ্যানেল সেভ নেই।"
        else:
            lines =[f"✅ **{len(channels)}টি** চ্যানেল সেভ আছে:"]
            for ch in channels:
                lines.append(f"• {ch['title']} (`{ch['id']}`)")
            status = "\n".join(lines)
        return f"📢 **চ্যানেল ম্যানেজমেন্ট**\n\n{status}"

    # ════════════════════════════════════════════════════════════════════════
    # HELPERS
    # ════════════════════════════════════════════════════════════════════════

    def is_terabox_url(url: str) -> bool:
        url_lower = url.lower()
        return any(domain in url_lower for domain in TERABOX_DOMAINS)

    def extract_terabox_url(text: str) -> str | None:
        """টেক্সট থেকে Terabox URL বের করো।"""
        if not text:
            return None
        for word in re.split(r'\s+', text):
            word = word.strip(".,;:!?\"'()[]")
            if word.startswith(("http://", "https://")) and is_terabox_url(word):
                return word
        return None

    # ════════════════════════════════════════════════════════════════════════
    # TERABOX API
    # ════════════════════════════════════════════════════════════════════════

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

            file_list = data.get("list") or data.get("data") or[]
            if isinstance(file_list, list) and len(file_list) > 0:
                results =[]
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
                return True,[{"download_url": dl_url, "zip_url": zip_url, "file_name": fname}]

            return False, f"API রেসপন্সে ডাউনলোড লিংক পাওয়া যায়নি।\nRaw: {str(data)[:300]}"

        except aiohttp.ClientError as e:
            return False, f"API কানেকশন সমস্যা: {str(e)}"
        except Exception as e:
            return False, f"Terabox API এরর: {str(e)}"

    # ════════════════════════════════════════════════════════════════════════
    # ZIP
    # ════════════════════════════════════════════════════════════════════════

    def find_videos_in_zip(extract_dir: str):
        videos =[]
        for root, dirs, files in os.walk(extract_dir):
            for fname in files:
                if fname.lower().endswith(VIDEO_EXTENSIONS):
                    full_path = os.path.join(root, fname)
                    videos.append((full_path, fname))
        videos.sort(key=lambda x: os.path.getsize(x[0]), reverse=True)
        return videos

    # ════════════════════════════════════════════════════════════════════════
    # DOWNLOAD
    # ════════════════════════════════════════════════════════════════════════

    async def download_file(url: str, save_path: str, status_msg):
        timeout = aiohttp.ClientTimeout(connect=30, sock_read=120, total=None)
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        err = "অজানা সমস্যা।"
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout, headers=req_headers) as session:
                    async with session.get(url) as response:
                        if response.status != 200:
                            return False, f"সার্ভার {response.status} রেসপন্স দিয়েছে।"
                        content_type = response.headers.get("Content-Type", "")
                        if "text/html" in content_type:
                            return False, "এটি ডাইরেক্ট ডাউনলোড লিংক নয়, HTML পেজ।"
                        total_size = int(response.headers.get("Content-Length", 0))
                        if total_size > MAX_FILE_SIZE:
                            return False, f"ফাইলটি অনেক বড় ({total_size/(1024**3):.2f} GB)। সর্বোচ্চ ২ GB।"
                        downloaded = 0
                        last_update = time.time()
                        with open(save_path, "wb") as f:
                            async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                                f.write(chunk)
                                downloaded += len(chunk)
                                now = time.time()
                                if now - last_update >= 5:
                                    last_update = now
                                    dl_mb = downloaded / (1024 * 1024)
                                    if total_size > 0:
                                        pct = (downloaded / total_size) * 100
                                        total_mb = total_size / (1024 * 1024)
                                        txt = f"⬇️ ডাউনলোড হচ্ছে...\n{dl_mb:.1f} MB / {total_mb:.1f} MB ({pct:.0f}%)"
                                    else:
                                        txt = f"⬇️ ডাউনলোড হচ্ছে... {dl_mb:.1f} MB"
                                    try:
                                        await status_msg.edit_text(txt)
                                    except Exception:
                                        pass
                        actual_size = os.path.getsize(save_path)
                        if actual_size == 0:
                            return False, "ডাউনলোড করা ফাইলটি খালি।"
                        # HTML error page চেক
                        with open(save_path, "rb") as f:
                            head = f.read(128).lower()
                        if head.startswith(b"<!") or b"<html" in head or head.startswith(b"<html"):
                            return False, "সার্ভার ভিডিওর বদলে HTML পেজ পাঠিয়েছে। লিংকটি সঠিক নয়।"
                        if actual_size < MIN_VIDEO_SIZE:
                            return False, f"ডাউনলোড হওয়া ফাইল অনেক ছোট ({actual_size} bytes)। সঠিক ভিডিও নয়।"
                        if total_size > 0 and actual_size < total_size * 0.99:
                            return False, f"ফাইল অসম্পূর্ণ ({actual_size}/{total_size} bytes)।"
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
                await asyncio.sleep(3)
                if os.path.exists(save_path):
                    os.remove(save_path)
        return False, f"{MAX_RETRIES} বার চেষ্টার পরও ব্যর্থ: {err}"

    async def download_terabox_with_fallback(
        primary_url: str, fallback_url: str | None, save_path: str, status_msg
    ):
        """primary URL দিয়ে চেষ্টা করো, ব্যর্থ হলে fallback (zip_dlink) দিয়ে চেষ্টা করো।"""
        ok, result = await download_file(primary_url, save_path, status_msg)
        if ok:
            return True, result
        # primary ব্যর্থ — fallback চেষ্টা
        if fallback_url and fallback_url != primary_url:
            print(f"Primary URL failed ({result}), trying fallback zip_dlink...", flush=True)
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

    def ensure_mp4_path(path: str) -> str:
        """ফাইলটি .mp4 হিসেবে নামকরণ নিশ্চিত করো।"""
        if not path.lower().endswith(".mp4"):
            new_path = path.rsplit(".", 1)[0] + ".mp4"
            if os.path.exists(path):
                os.rename(path, new_path)
            return new_path
        return path

    async def send_video_file(client, message, status_msg, file_path: str, caption: str):
        file_path = ensure_mp4_path(file_path)
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        try:
            await status_msg.edit_text(
                f"✅ ডাউনলোড সম্পন্ন ({size_mb:.2f} MB)।\n⬆️ টেলিগ্রামে আপলোড হচ্ছে... 🚀"
            )
        except Exception:
            pass
        await client.send_video(
            chat_id=message.chat.id,
            video=file_path,
            caption=caption,
            reply_to_message_id=message.id,
            supports_streaming=True,
        )
        await status_msg.delete()

    # ════════════════════════════════════════════════════════════════════════
    # CHANNEL POST HELPER
    # ════════════════════════════════════════════════════════════════════════

    async def post_to_channels(client, user_id: int, channels: list, status_msg,
                               photo_file_id=None, video_file_id=None,
                               original_caption="", downloaded_video_path=None,
                               downloaded_video_name=""):
        """
        সেভ করা সব চ্যানেলে মিডিয়া ও ডাউনলোড করা ভিডিও পোস্ট করো।
        """
        success_count = 0
        fail_msgs =[]

        for ch in channels:
            ch_id = ch["id"]
            ch_title = ch["title"]
            try:
                # ১. অরিজিনাল মিডিয়া পোস্ট করো
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

                # ২. ডাউনলোড করা Terabox ভিডিও পোস্ট করো
                if downloaded_video_path and os.path.exists(downloaded_video_path):
                    vid_path = ensure_mp4_path(downloaded_video_path)
                    size_mb = os.path.getsize(vid_path) / (1024 * 1024)
                    await client.send_video(
                        chat_id=ch_id,
                        video=vid_path,
                        caption=f"🎬 {downloaded_video_name}\nআকার: {size_mb:.2f} MB",
                        supports_streaming=True,
                    )
                success_count += 1
            except Exception as e:
                fail_msgs.append(f"❌ {ch_title}: {str(e)}")
                print(f"Channel post error ({ch_title}): {e}", flush=True)

        return success_count, fail_msgs

    # ════════════════════════════════════════════════════════════════════════
    # COMMANDS
    # ════════════════════════════════════════════════════════════════════════

    @app.on_message(filters.command("start"))
    async def start_cmd(client, message: Message):
        await message.reply_text(
            "হ্যালো! 👋\n"
            "নিচের যেকোনো ধরনের লিংক দিন:\n\n"
            "🎬 ডাইরেক্ট MP4/ভিডিও লিংক\n"
            "📦 ZIP ফাইল লিংক (ভেতরে MP4 থাকলে)\n"
            "☁️ Terabox লিংক\n\n"
            "⚙️ Terabox API Key ম্যানেজ করতে: /api\n"
            "📢 চ্যানেল ম্যানেজ করতে: /channel\n\n"
            "আমি ডাউনলোড করে ভিডিও হিসেবে পাঠিয়ে দেবো। 🚀"
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
            await message.reply_text("কোনো সক্রিয় অপেক্ষা নেই।")

    # ════════════════════════════════════════════════════════════════════════
    # CALLBACK QUERIES
    # ════════════════════════════════════════════════════════════════════════

    @app.on_callback_query()
    async def callback_handler(client, callback: CallbackQuery):
        user_id = callback.from_user.id
        data = callback.data

        # ── API Callbacks ─────────────────────────────────────────────────
        if data == "api_menu":
            await callback.message.edit_text(
                api_menu_text(user_id), reply_markup=api_main_keyboard(user_id)
            )
        elif data == "api_add":
            waiting_state[user_id] = {"step": "key"}
            await callback.message.edit_text(
                "✏️ **নতুন API Key এর নাম দিন**\n\n"
                "প্রথমে একটি নাম পাঠান (যেমন: `personal`, `work`, `mykey1`)\n"
                "বাতিল করতে /cancel লিখুন।",
                reply_markup=None,
            )
            # দুই ধাপ: প্রথমে নাম, তারপর key
            waiting_state[user_id] = {"step": "label"}

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

        # ── Channel Callbacks ─────────────────────────────────────────────
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
                "⚠️ বটকে অবশ্যই চ্যানেলের Admin করতে মৃদু হবে।\n"
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

    # ════════════════════════════════════════════════════════════════════════
    # FORWARDED MEDIA HANDLER (photo বা video সহ ফরওয়ার্ড)
    # ════════════════════════════════════════════════════════════════════════

    @app.on_message(filters.forwarded & (filters.photo | filters.video))
    async def handle_forwarded_media(client, message: Message):
        if not message.from_user:
            return
        user_id = message.from_user.id

        # ── চ্যানেল যোগের মোডে আছে? ─────────────────────────────────────
        if user_id in waiting_state and waiting_state[user_id].get("step") == "add_channel":
            waiting_state.pop(user_id, None)
            fwd_chat = message.forward_from_chat
            if not fwd_chat:
                await message.reply_text(
                    "❌ এই পোস্ট থেকে চ্যানেল ID পাওয়া যায়নি।\n"
                    "চ্যানেলের Privacy setting বন্ধ থাকতে পারে।\n"
                    "চ্যানেল ID সরাসরি পাঠান।"
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

        # ── Terabox লিংক আছে? ────────────────────────────────────────────
        caption = message.caption or ""
        terabox_url = extract_terabox_url(caption)
        if not terabox_url:
            return  # Terabox লিংক নেই, এড়িয়ে যাও

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

        # ── Photo/Video file_id সংগ্রহ ────────────────────────────────────
        photo_file_id = None
        video_file_id = None
        if message.photo:
            photo_file_id = message.photo.file_id
        elif message.video:
            video_file_id = message.video.file_id

        # ── Terabox ডাউনলোড ───────────────────────────────────────────────
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

                # শুধুমাত্র প্রথম ভিডিওর সাথে অরিজিনাল মিডিয়া পাঠাও
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

    # ════════════════════════════════════════════════════════════════════════
    # TEXT HANDLER
    # ════════════════════════════════════════════════════════════════════════

    @app.on_message(filters.text & ~filters.regex(r"^/"))
    async def handle_text(client, message: Message):
        if not message.from_user:
            return
        user_id = message.from_user.id
        text = message.text.strip()

        # ── Waiting state ─────────────────────────────────────────────────
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

            # চ্যানেল যোগ — টেক্সট দিয়ে (ID বা @username বা ফরওয়ার্ড)
            elif state["step"] == "add_channel":

                # ফরওয়ার্ড করা টেক্সট মেসেজ
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
                            f"⚠️ এই চ্যানেল আগেই সেভ আছে।",
                            reply_markup=channel_main_keyboard(user_id),
                        )
                    return

                # সরাসরি ID বা @username — get_chat() ছাড়াই সেভ করো
                channel_input = text.strip()
                waiting_state.pop(user_id, None)

                # int ID নাকি @username?
                try:
                    channel_id = int(channel_input)
                    title = f"Channel {channel_id}"
                except ValueError:
                    # @username হিসেবে রাখো
                    channel_id = channel_input
                    title = channel_input

                added = add_user_channel(user_id, channel_id, title)
                if added:
                    await message.reply_text(
                        f"✅ চ্যানেল সেভ হয়েছে!\n"
                        f"ID: `{channel_id}`\n\n"
                        "⚠️ নিশ্চিত করুন বটকে চ্যানেলের Admin করা হয়েছে।\n"
                        "💡 চ্যানেল থেকে পোস্ট ফরওয়ার্ড করলে নামও সেভ হবে।",
                        reply_markup=channel_main_keyboard(user_id),
                    )
                else:
                    await message.reply_text(
                        "⚠️ এই চ্যানেল আগেই সেভ আছে।",
                        reply_markup=channel_main_keyboard(user_id),
                    )
                return

        # ── URL হ্যান্ডেলিং ───────────────────────────────────────────────
        if not (text.startswith("http://") or text.startswith("https://")):
            await message.reply_text("❌ সঠিক URL দিন (http:// বা https:// দিয়ে শুরু)।")
            return

        url = text
        status_msg = await message.reply_text("⏳ লিংকটি চেক করা হচ্ছে...")

        uid      = f"{user_id}_{int(time.time())}"
        temp_dir = f"temp_{uid}"
        zip_path = f"{temp_dir}.zip"
        mp4_path = f"video_{uid}.mp4"
        temp_dl  = f"dl_{uid}.tmp"

        try:
            # ── Terabox ───────────────────────────────────────────────────
            if is_terabox_url(url):
                active_key = get_active_key(user_id) or DEFAULT_TERABOX_KEY
                udata = get_user_data(user_id)
                active_label = udata.get("active")
                key_label = f"🔑 {active_label}" if get_active_key(user_id) else "🌐 ডিফল্ট API"

                await status_msg.edit_text(
                    f"☁️ Terabox লিংক শনাক্ত হয়েছে!\nব্যবহার হচ্ছে: {key_label}\n"
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
                        dl_path = ensure_mp4_path(dl_path)
                        size_mb = os.path.getsize(dl_path) / (1024 * 1024)
                        await send_video_file(
                            client, message, status_msg, dl_path,
                            f"☁️ Terabox: {file_name}\nআকার: {size_mb:.2f} MB"
                            + (f" ({i}/{total})" if total > 1 else "")
                        )
                    finally:
                        if os.path.exists(dl_path):
                            os.remove(dl_path)
                return

            # ── সাধারণ লিংক ──────────────────────────────────────────────
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
                        video_names =[n for n in names if n.lower().endswith(VIDEO_EXTENSIONS)]
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
                    video_path = ensure_mp4_path(video_path)
                    size_mb = os.path.getsize(video_path) / (1024 * 1024)
                    try:
                        await status_msg.edit_text(
                            f"⬆️ আপলোড হচ্ছে ({i}/{total_videos}): {video_fname}\nআকার: {size_mb:.2f} MB"
                        )
                    except Exception:
                        pass
                    await client.send_video(
                        chat_id=message.chat.id,
                        video=video_path,
                        caption=f"🎬 {video_fname}\nআকার: {size_mb:.2f} MB ({i}/{total_videos})",
                        reply_to_message_id=message.id,
                        supports_streaming=True,
                    )
                await status_msg.delete()

            else:
                os.rename(temp_dl, mp4_path)
                size_mb = os.path.getsize(mp4_path) / (1024 * 1024)
                await send_video_file(
                    client, message, status_msg, mp4_path,
                    f"✅ ভিডিও ডাউনলোড সম্পন্ন!\nআকার: {size_mb:.2f} MB"
                )

        except Exception as e:
            print(f"Error: {e}", flush=True)
            traceback.print_exc()
            try:
                await status_msg.edit_text(f"⚠️ একটি সমস্যা হয়েছে:\n{str(e)}")
            except Exception:
                pass
        finally:
            for path in[temp_dl, zip_path, mp4_path]:
                if os.path.exists(path):
                    os.remove(path)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    # ── Run ───────────────────────────────────────────────────────────────
    if __name__ == "__main__":
        print("✅ Bot is successfully running...", flush=True)

        keep_alive()

        app.start()
        print("🤖 Bot started and listening for messages...", flush=True)

        try:
            from pyrogram import idle
            idle()
        except KeyboardInterrupt:
            print("🛑 Bot stopped manually")

        app.stop()

except Exception as e:
    print("❌ CRITICAL ERROR:", flush=True)
    traceback.print_exc()
    sys.exit(1)
