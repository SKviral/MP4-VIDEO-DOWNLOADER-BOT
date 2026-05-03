# 🤖 Terabox Video Downloader Bot — Premium v2.0

একটি প্রিমিয়াম টেলিগ্রাম বট যা Terabox, ডাইরেক্ট MP4, এবং ZIP ফাইল থেকে ভিডিও ডাউনলোড করে টেলিগ্রাম চ্যানেলে পোস্ট করে।

---

## ✨ নতুন ফিচার (v2.0)

| ফিচার | বিবরণ |
|-------|-------|
| 🔧 **ভিডিও বাগ ফিক্স** | ffmpeg দিয়ে moov atom ও faststart ঠিক করা |
| 🖼️ **অটো থাম্বনেইল** | ffmpeg দিয়ে ভিডিওর প্রথম ফ্রেম থেকে থাম্ব তৈরি |
| 📢 **চ্যানেল পোস্ট অর্ডার** | ভিডিও আগে, ইমেজ পরে |
| 💾 **ব্যাকআপ সিস্টেম** | /backup দিয়ে সব ডেটা ZIP করে ডাউনলোড |
| 🔄 **ব্যাকআপ রিস্টোর** | ZIP ফাইল পাঠালে অটো রিস্টোর |
| 📊 **স্ট্যাটস** | /stats — ডাউনলোড কাউন্ট, আপটাইম, ইউজার সংখ্যা |
| ⚡ **স্পিড ও ETA** | ডাউনলোড প্রগ্রেস বার + স্পিড + ETA |
| 📣 **ব্রডকাস্ট** | Admin দিয়ে সব ইউজারকে মেসেজ |
| 🌐 **Health Endpoint** | /health — Render uptime monitoring |

---

## 📋 কমান্ড তালিকা

| কমান্ড | কাজ |
|--------|-----|
| /start | বট শুরু করুন |
| /help | বিস্তারিত সাহায্য |
| /api | Terabox API Key ম্যানেজ |
| /channel | চ্যানেল যোগ/মুছুন |
| /backup | ডেটা ব্যাকআপ ডাউনলোড |
| /stats | বটের পরিসংখ্যান |
| /cancel | চলমান অপারেশন বাতিল |
| /broadcast | (Admin) সব ইউজারকে মেসেজ |

---

## 🚀 GitHub → Render Deploy গাইড

### ধাপ ১: GitHub রেপো

```bash
git init
git add .
git commit -m "Terabox Bot v2.0"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/terabox-bot.git
git push -u origin main
```

### ধাপ ২: Render সেটিংস

| সেটিং | মান |
|-------|-----|
| Environment | Python |
| Build Command | apt-get update && apt-get install -y ffmpeg && pip install -r requirements.txt |
| Start Command | python main.py |
| Plan | Free |

### ধাপ ৩: Environment Variables

| Key | মান |
|-----|-----|
| API_ID | Telegram API ID |
| API_HASH | Telegram API Hash |
| BOT_TOKEN | BotFather Bot Token |
| TERABOX_API_KEY | xapiverse.com API Key (optional) |
| ADMIN_IDS | আপনার Telegram ID (optional) |

---

## 💾 ব্যাকআপ ও রিস্টোর

- ব্যাকআপ: /backup কমান্ড দিন
- রিস্টোর: ZIP ফাইল বটে পাঠান → রিস্টোর বাটন চাপুন

> ⚠️ Render Free Plan-এ restart-এ ডেটা মুছে যায়। নিয়মিত /backup নিন।

---

## 🗂️ ফাইল স্ট্রাকচার

```
├── main.py           # মূল বট কোড
├── keep_alive.py     # Flask web server
├── requirements.txt  # Dependencies
├── render.yaml       # Render config
├── .gitignore
└── README.md
```
