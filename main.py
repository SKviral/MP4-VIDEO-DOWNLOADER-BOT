import os
import sys
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
    MAX_RETRIES      = 3
    VIDEO_EXTENSIONS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v")
    USER_API_FILE    = "user_apis.json"
    TERABOX_API_URL  = "https://xapiverse.com/api/terabox"

    TERABOX_DOMAINS = (
        "terabox.com", "1024terabox.com", "teraboxapp.com",
        "freeterabox.com", "4funbox.co", "mirrobox.com",
        "momerybox.com", "tibibox.com", "nephobox.com", "terabox.app",
    )

    # ── State tracking ────────────────────────────────────────────────────
    # { user_id: {"step": "label"|"key", "label": "নামটি"} }
    waiting_state: dict = {}

    # ── Storage helpers ───────────────────────────────────────────────────
    # ফরম্যাট:
    # {
    #   "user_id": {
    #     "active": "label1",
    #     "keys": { "label1": "sk_xxx", "label2": "sk_yyy" }
    #   }
    # }

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
        return data.get(str(user_id), {"active": None, "keys": {}})

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

    # ── Keyboards ─────────────────────────────────────────────────────────
    def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
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

    def back_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 পিছনে যান", callback_data="api_menu")]
        ])

    def menu_text(user_id: int) -> str:
        udata = get_user_data(user_id)
        keys = udata.get("keys", {})
        active = udata.get("active")
        if not keys:
            status = "❌ কোনো API Key সেট নেই।\nএখন **ডিফল্ট API** ব্যবহার হচ্ছে।"
        else:
            active_key = keys.get(active, "")
            status = (
                f"✅ **{len(keys)}টি** API Key সেভ আছে।\n"
                f"🟢 Active: **{active}** (`{mask_key(active_key)}`)\n"
                "এই Key দিয়ে Terabox ডাউনলোড হচ্ছে।"
            )
        return f"⚙️ **Terabox API Key ম্যানেজমেন্ট**\n\n{status}"

    # ── Terabox ───────────────────────────────────────────────────────────
    def is_terabox_url(url: str) -> bool:
        url_lower = url.lower()
        return any(domain in url_lower for domain in TERABOX_DOMAINS)

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
                return False, str(msg)

            file_list = data.get("list") or data.get("data") or []
            if isinstance(file_list, list) and len(file_list) > 0:
                results = []
                for item in file_list:
                    dl_url = (
                        item.get("normal_dlink") or item.get("dlink")
                        or item.get("download_url") or item.get("url") or item.get("link")
                    )
                    fname = (
                        item.get("name") or item.get("file_name")
                        or item.get("filename") or "terabox_video.mp4"
                    )
                    if dl_url:
                        results.append({"download_url": dl_url, "file_name": fname})
                if results:
                    return True, results

            dl_url = (
                data.get("normal_dlink") or data.get("dlink")
                or data.get("download_url") or data.get("url") or data.get("link")
            )
            if dl_url:
                fname = data.get("name") or data.get("file_name") or "terabox_video.mp4"
                return True, [{"download_url": dl_url, "file_name": fname}]

            return False, f"API রেসপন্সে ডাউনলোড লিংক পাওয়া যায়নি।\nRaw: {str(data)[:300]}"

        except aiohttp.ClientError as e:
            return False, f"API কানেকশন সমস্যা: {str(e)}"
        except Exception as e:
            return False, f"Terabox API এরর: {str(e)}"

    # ── ZIP ───────────────────────────────────────────────────────────────
    def find_videos_in_zip(extract_dir: str):
        videos = []
        for root, dirs, files in os.walk(extract_dir):
            for fname in files:
                if fname.lower().endswith(VIDEO_EXTENSIONS):
                    full_path = os.path.join(root, fname)
                    videos.append((full_path, fname))
        videos.sort(key=lambda x: os.path.getsize(x[0]), reverse=True)
        return videos

    # ── Download ──────────────────────────────────────────────────────────
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

    async def send_video_file(client, message, status_msg, file_path: str, caption: str):
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

    # ── Commands ──────────────────────────────────────────────────────────
    @app.on_message(filters.command("start"))
    async def start_cmd(client, message: Message):
        await message.reply_text(
            "হ্যালো! 👋\n"
            "নিচের যেকোনো ধরনের লিংক দিন:\n\n"
            "🎬 ডাইরেক্ট MP4/ভিডিও লিংক\n"
            "📦 ZIP ফাইল লিংক (ভেতরে MP4 থাকলে)\n"
            "☁️ Terabox লিংক\n\n"
            "⚙️ নিজের Terabox API Key ম্যানেজ করতে /api কমান্ড দিন।\n\n"
            "আমি ডাউনলোড করে ভিডিও হিসেবে পাঠিয়ে দেবো। 🚀"
        )

    @app.on_message(filters.command("api"))
    async def api_cmd(client, message: Message):
        user_id = message.from_user.id
        await message.reply_text(
            menu_text(user_id),
            reply_markup=main_menu_keyboard(user_id),
        )

    @app.on_message(filters.command("cancel"))
    async def cancel_cmd(client, message: Message):
        user_id = message.from_user.id
        if user_id in waiting_state:
            waiting_state.pop(user_id, None)
            await message.reply_text("❌ বাতিল করা হয়েছে।")
        else:
            await message.reply_text("কোনো সক্রিয় অপেক্ষা নেই।")

    # ── Callback Queries ──────────────────────────────────────────────────
    @app.on_callback_query()
    async def callback_handler(client, callback: CallbackQuery):
        user_id = callback.from_user.id
        data = callback.data

        # মেইন মেনু
        if data == "api_menu":
            await callback.message.edit_text(
                menu_text(user_id),
                reply_markup=main_menu_keyboard(user_id),
            )

        # নতুন Key যোগের ধাপ ১: নাম চাও
        elif data == "api_add":
            waiting_state[user_id] = {"step": "label"}
            await callback.message.edit_text(
                "✏️ **নতুন API Key এর নাম দিন**\n\n"
                "উদাহরণ: `mykey1`, `personal`, `work`\n"
                "বাতিল করতে /cancel লিখুন।",
                reply_markup=None,
            )

        # সব Key তালিকা
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
            await callback.message.edit_text(text, reply_markup=back_keyboard())

        # Active Key পরিবর্তন — Key সিলেক্ট করো
        elif data == "api_switch":
            udata = get_user_data(user_id)
            keys = udata.get("keys", {})
            if not keys:
                await callback.message.edit_text(
                    "❌ কোনো Key নেই। আগে যোগ করুন।",
                    reply_markup=back_keyboard(),
                )
            else:
                await callback.message.edit_text(
                    "🔄 **কোন Key Active করবেন?**\n"
                    "✅ চিহ্নিতটি এখন Active।",
                    reply_markup=keys_select_keyboard(user_id, "switch"),
                )

        # Active Key সেট করো
        elif data.startswith("switch:"):
            label = data.split(":", 1)[1]
            set_active_key(user_id, label)
            await callback.message.edit_text(
                f"✅ **{label}** এখন Active Key হিসেবে সেট হয়েছে।",
                reply_markup=back_keyboard(),
            )

        # মুছার তালিকা
        elif data == "api_delete_list":
            udata = get_user_data(user_id)
            keys = udata.get("keys", {})
            if not keys:
                await callback.message.edit_text(
                    "❌ কোনো Key নেই।",
                    reply_markup=back_keyboard(),
                )
            else:
                await callback.message.edit_text(
                    "🗑️ **কোন Key মুছতে চান?**\nক্লিক করলেই মুছে যাবে।",
                    reply_markup=keys_select_keyboard(user_id, "del"),
                )

        # নির্দিষ্ট Key মুছো
        elif data.startswith("del:"):
            label = data.split(":", 1)[1]
            delete_user_key(user_id, label)
            udata = get_user_data(user_id)
            keys = udata.get("keys", {})
            await callback.message.edit_text(
                f"🗑️ **{label}** মুছে ফেলা হয়েছে।",
                reply_markup=(
                    keys_select_keyboard(user_id, "del")
                    if keys else back_keyboard()
                ),
            )

        # সাহায্য
        elif data == "api_help":
            await callback.message.edit_text(
                "❓ **Terabox API Key কোথায় পাবেন?**\n\n"
                "১. [xapiverse.com](https://xapiverse.com) এ যান\n"
                "২. রেজিস্ট্রেশন করুন\n"
                "৩. Dashboard থেকে API Key কপি করুন\n"
                "৪. বটে /api দিয়ে **➕ নতুন API Key যোগ করুন** চাপুন\n\n"
                "নিজের Key ব্যবহার করলে আলাদা limit ও speed পাবেন।",
                reply_markup=back_keyboard(),
            )

        await callback.answer()

    # ── Text Handler ──────────────────────────────────────────────────────
    @app.on_message(filters.text & ~filters.regex(r"^/"))
    async def handle_text(client, message: Message):
        user_id = message.from_user.id
        text = message.text.strip()

        # ── API Key যোগের মাল্টি-স্টেপ ইনপুট ───────────────────────────
        if user_id in waiting_state:
            state = waiting_state[user_id]

            if state["step"] == "label":
                label = text.strip()
                if len(label) < 1 or len(label) > 30:
                    await message.reply_text("❌ নামটি ১–৩০ অক্ষরের মধ্যে হতে হবে। আবার লিখুন।")
                    return
                waiting_state[user_id] = {"step": "key", "label": label}
                await message.reply_text(
                    f"✅ নাম: **{label}**\n\n"
                    "এখন xapiverse.com এর API Key টি পাঠান:\n"
                    "বাতিল করতে /cancel লিখুন।"
                )
                return

            elif state["step"] == "key":
                api_key = text.strip()
                label = state["label"]
                waiting_state.pop(user_id, None)

                if len(api_key) < 10:
                    await message.reply_text(
                        "❌ API Key টি সঠিক মনে হচ্ছে না। আবার /api দিয়ে চেষ্টা করুন।"
                    )
                    return

                add_user_key(user_id, label, api_key)
                await message.reply_text(
                    f"✅ **API Key সফলভাবে সেভ হয়েছে!**\n\n"
                    f"🏷️ নাম: **{label}**\n"
                    f"🔑 Key: `{mask_key(api_key)}`\n\n"
                    "এখন এই Key টি Active আছে।",
                    reply_markup=main_menu_keyboard(user_id),
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
                if get_active_key(user_id):
                    key_label = f"🔑 {active_label}"
                else:
                    key_label = "🌐 ডিফল্ট API"

                await status_msg.edit_text(
                    f"☁️ Terabox লিংক শনাক্ত হয়েছে!\n"
                    f"ব্যবহার হচ্ছে: {key_label}\n"
                    "🔍 তথ্য সংগ্রহ করা হচ্ছে..."
                )

                ok, info = await get_terabox_info(url, active_key)
                if not ok:
                    await status_msg.edit_text(
                        f"❌ Terabox লিংক প্রসেস করতে ব্যর্থ!\n{info}\n\n"
                        "💡 নিজের API Key যোগ করতে /api কমান্ড দিন।"
                    )
                    return

                file_list = info
                total = len(file_list)

                for i, file_info in enumerate(file_list, 1):
                    dl_url    = file_info["download_url"]
                    file_name = file_info["file_name"]
                    dl_path   = f"terabox_{uid}_{i}.mp4"

                    await status_msg.edit_text(
                        f"📄 ফাইল ({i}/{total}): {file_name}\n⬇️ ডাউনলোড শুরু হচ্ছে..."
                    )
                    success, result = await download_file(dl_url, dl_path, status_msg)
                    if not success:
                        await status_msg.edit_text(
                            f"❌ ডাউনলোড ব্যর্থ ({file_name})!\n{result}"
                        )
                        continue
                    try:
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
            for path in [temp_dl, zip_path, mp4_path]:
                if os.path.exists(path):
                    os.remove(path)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    # ── Run ───────────────────────────────────────────────────────────────
    if __name__ == "__main__":
        keep_alive()
        print("✅ Bot is successfully running...", flush=True)
        app.run()

except Exception as e:
    print("❌ CRITICAL ERROR:", flush=True)
    traceback.print_exc()
    sys.exit(1)
