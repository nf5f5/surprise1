import telebot
import os
import logging
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import datetime
from flask import Flask
import threading

logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8449089753

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive"

# ================= CONFIG / STORAGE =================
MAX_PLAYERS = 100

player_mode = {}          # user_id -> "solo"/"team"
mode_change_used = set()  # user_id who already changed once
original_mode = {}        # ⭐ أول اختيار للنمط (إصلاح المشكلة)

minecraft_users = {}      # user_id -> {"mc": str, "user": str}
minecraft_taken = set()   # lower(mc)

banned_users = set()      # user_id
joined_users = set()      # user_id (first time start)

pending_teams = {}        # owner_id -> {"name": str, "count": int}
teams_data = {}           # topic_id -> {"name","needed","members":[],"owner","closed":bool}
user_team = {}            # user_id -> topic_id
team_logs = {}            # topic_id -> [str logs]

data = {
    "channel": "Not Set",         # @channelusername
    "server_group": "Not Set",    # -100...
    "ip": "Not Set",
    "port": "Not Set",
    "link": "Not Set"
}

START_IMAGE = "https://i.postimg.cc/K8dLMMXj/file_00000000a69871f4b3c43df6a626ed56.png"
DONE_IMAGE  = "https://i.postimg.cc/Bb6tyS9W/file-00000000ac2071f498a14f990191d9b0.png"

# ================= UTIL =================
def is_admin(uid):
    return uid == ADMIN_ID

def check_sub(uid):
    if data["channel"] == "Not Set":
        return True
    try:
        m = bot.get_chat_member(data["channel"], uid)
        return m.status in ["member", "administrator", "creator"]
    except:
        return False

def smart_close_topic(chat_id, topic_id):
    try:
        bot.close_forum_topic(chat_id=chat_id, message_thread_id=topic_id)
        return True
    except:
        return False

def smart_reopen_topic(chat_id, topic_id):
    try:
        bot.reopen_forum_topic(chat_id=chat_id, message_thread_id=topic_id)
        return True
    except:
        return False

def needed_text(n):
    return f"🚨 مطلوب {n} عضو للتيم"

# ================= KEYBOARDS =================
def user_buttons(uid):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📋 نسخ IP", callback_data="copy_ip"),
        InlineKeyboardButton("📋 نسخ PORT", callback_data="copy_port"),
    )
    kb.add(InlineKeyboardButton("👥 انشاء تيم", callback_data="create_team"))
    kb.add(InlineKeyboardButton("🔄 تغيير النمط", callback_data="change_mode"))
    if data["link"] != "Not Set":
        kb.add(InlineKeyboardButton("🌐 دخول مباشر", url=data["link"]))
    if is_admin(uid):
        kb.add(InlineKeyboardButton("👑 لوحة التحكم", callback_data="admin_panel"))
    return kb

def admin_buttons():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📢 تحديد القناة", callback_data="set_channel"),
        InlineKeyboardButton("👥 تحديد الكروب", callback_data="set_group"),
    )
    kb.add(
        InlineKeyboardButton("🌐 تغيير IP", callback_data="set_ip"),
        InlineKeyboardButton("📡 تغيير PORT", callback_data="set_port"),
    )
    kb.add(InlineKeyboardButton("🔗 تغيير LINK", callback_data="set_link"))
    kb.add(
        InlineKeyboardButton("📜 اللاعبين", callback_data="players_list"),
        InlineKeyboardButton("🔎 بحث لاعب", callback_data="search_player"),
    )
    kb.add(
        InlineKeyboardButton("📛 المحظورين", callback_data="show_banned"),
        InlineKeyboardButton("🗑 حذف المحظورين", callback_data="clear_banned"),
    )
    kb.add(InlineKeyboardButton("🔎 بحث محظور", callback_data="search_banned"))
    kb.add(InlineKeyboardButton("📊 الإحصائيات", callback_data="stats"))
    return kb

# ================= START =================
@bot.message_handler(commands=['start'])
def start(msg):
    uid = msg.from_user.id

    if uid in banned_users:
        bot.send_message(msg.chat.id, "❌ انت محظور من البوت")
        return

    if not check_sub(uid):
        bot.send_message(msg.chat.id, f"⚠️ اشترك بالقناة {data['channel']} ثم ارسل /start")
        return

    if uid not in joined_users:
        joined_users.add(uid)
        uname = msg.from_user.username or msg.from_user.first_name
        bot.send_message(ADMIN_ID, f"🚀 دخول مستخدم جديد: @{uname}")

    if uid in minecraft_users and uid in player_mode:
        show_done(msg)
    else:
        show_start(msg)

# ================= REG FLOW =================
def show_start(msg):
    text = """
<b><blockquote>انرت سيرفر سبرايز 🔥
ارسل اسمك الماينكرافتي لتسجيلك:</blockquote></b>

<b><blockquote>Welcome to the server surprise 🔥
Send your Minecraft name to register:</blockquote></b>
"""
    bot.send_photo(msg.chat.id, START_IMAGE, caption=text)
    bot.register_next_step_handler(msg, save_mc)

def save_mc(msg):
    uid = msg.from_user.id
    mc = (msg.text or "").strip()
    if not mc:
        bot.send_message(msg.chat.id, "❌ ارسل اسم صحيح")
        return

    if mc.lower() in minecraft_taken:
        bot.send_message(msg.chat.id, "❌ تم تكرار الاسم")
        return

    username = msg.from_user.username or msg.from_user.first_name
    minecraft_users[uid] = {"mc": mc, "user": username}
    minecraft_taken.add(mc.lower())

    bot.send_message(ADMIN_ID, f"Person's username: @{username}\nName Minecraft: {mc}")
    ask_play_mode(msg)

def ask_play_mode(msg):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎮 فردي", callback_data="mode_solo"),
        InlineKeyboardButton("👥 تيم", callback_data="mode_team"),
    )
    bot.send_message(msg.chat.id, "شنو تلعب؟", reply_markup=kb)

def show_done(msg):
    text = """
<b><blockquote>الان يمكنك الدخول رسمياً الى سيرفر سبرايز🔥
انسخ الايبي والبورت عبر الازرار</blockquote></b>

<b><blockquote>You can now officially log in to the Surprise server 🔥
Copy IP and PORT using buttons</blockquote></b>
"""
    bot.send_photo(msg.chat.id, DONE_IMAGE, caption=text, reply_markup=user_buttons(msg.from_user.id))

# ================= CALLBACK CORE =================
@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    uid = call.from_user.id
    chat_id = call.message.chat.id

    # ---- COPY
    if call.data == "copy_ip":
        bot.send_message(chat_id, data["ip"])
        return
    if call.data == "copy_port":
        bot.send_message(chat_id, data["port"])
        return

    # ---- MODE CHOICE (حفظ الاختيار الأصلي مرة واحدة)
    if call.data == "mode_solo":
        if len(player_mode) >= MAX_PLAYERS:
            bot.send_message(chat_id, "❌ اكتمل العدد")
            return
        player_mode[uid] = "solo"
        if uid not in original_mode:
            original_mode[uid] = "solo"
        bot.send_message(chat_id, "✅ تم اختيار فردي")
        show_done(call.message)
        return

    if call.data == "mode_team":
        if len(player_mode) >= MAX_PLAYERS:
            bot.send_message(chat_id, "❌ اكتمل العدد")
            return
        player_mode[uid] = "team"
        if uid not in original_mode:
            original_mode[uid] = "team"
        bot.send_message(chat_id, "✅ تم اختيار تيم")
        show_done(call.message)
        return

    # ---- CHANGE MODE (مرة واحدة، والرجوع للأصل مسموح بدون احتساب)
    if call.data == "change_mode":
        if uid not in player_mode:
            bot.send_message(chat_id, "❌ اختر النمط اولاً")
            return
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🎮 فردي", callback_data="change_to_solo"),
            InlineKeyboardButton("👥 تيم", callback_data="change_to_team"),
        )
        bot.send_message(chat_id, "اختر النمط الجديد", reply_markup=kb)
        return

    if call.data == "change_to_solo":
        if original_mode.get(uid) == "solo":
            player_mode[uid] = "solo"
            bot.send_message(chat_id, "رجعت لاختيارك الاصلي ✅")
            return
        if uid in mode_change_used:
            bot.send_message(chat_id, "❌ استهلكت محاولة التغيير")
            return
        player_mode[uid] = "solo"
        mode_change_used.add(uid)
        bot.send_message(chat_id, "✅ تم التغيير الى فردي")
        return

    if call.data == "change_to_team":
        if original_mode.get(uid) == "team":
            player_mode[uid] = "team"
            bot.send_message(chat_id, "رجعت لاختيارك الاصلي ✅")
            return
        if uid in mode_change_used:
            bot.send_message(chat_id, "❌ استهلكت محاولة التغيير")
            return
        player_mode[uid] = "team"
        mode_change_used.add(uid)
        bot.send_message(chat_id, "✅ تم التغيير الى تيم")
        return

    # ---- ADMIN PANEL
    if call.data == "admin_panel" and is_admin(uid):
        bot.send_message(chat_id, "👑 لوحة التحكم", reply_markup=admin_buttons())
        return

    # ---- ADMIN SETTINGS
    if is_admin(uid) and call.data == "set_channel":
        bot.send_message(chat_id, "ارسل يوزر القناة (مثال: @mychannel)")
        bot.register_next_step_handler(call.message, save_channel)
        return

    if is_admin(uid) and call.data == "set_group":
        bot.send_message(chat_id, "ارسل ID الكروب (مثال: -100xxxxxxxxxx)")
        bot.register_next_step_handler(call.message, save_group)
        return

    if is_admin(uid) and call.data == "set_ip":
        bot.send_message(chat_id, "ارسل IP")
        bot.register_next_step_handler(call.message, save_ip)
        return

    if is_admin(uid) and call.data == "set_port":
        bot.send_message(chat_id, "ارسل PORT")
        bot.register_next_step_handler(call.message, save_port)
        return

    if is_admin(uid) and call.data == "set_link":
        bot.send_message(chat_id, "ارسل LINK")
        bot.register_next_step_handler(call.message, save_link)
        return

    # ---- ADMIN LISTS / SEARCH
    if is_admin(uid) and call.data == "players_list":
        if not minecraft_users:
            bot.send_message(chat_id, "لا يوجد لاعبين")
            return
        lines = []
        for u, d in minecraft_users.items():
            lines.append(f"{d['mc']} ~ @{d['user']}")
        bot.send_message(chat_id, "📜 اللاعبين:\n\n" + "\n".join(lines[:100]))
        return

    if is_admin(uid) and call.data == "search_player":
        bot.send_message(chat_id, "ارسل اسم ماينكرافت للبحث")
        bot.register_next_step_handler(call.message, search_player_name)
        return

    if is_admin(uid) and call.data == "show_banned":
        if not banned_users:
            bot.send_message(chat_id, "لا يوجد محظورين")
            return
        lines = []
        for u in banned_users:
            try:
                ch = bot.get_chat(u)
                nm = ch.username or ch.first_name
            except:
                nm = str(u)
            lines.append(f"{nm} ({u})")
        bot.send_message(chat_id, "📛 المحظورين:\n\n" + "\n".join(lines[:100]))
        return

    if is_admin(uid) and call.data == "clear_banned":
        banned_users.clear()
        bot.send_message(chat_id, "🗑 تم حذف كل المحظورين")
        return

    if is_admin(uid) and call.data == "search_banned":
        bot.send_message(chat_id, "ارسل اسم/يوزر للبحث بالمحظورين")
        bot.register_next_step_handler(call.message, search_banned_user)
        return

    if is_admin(uid) and call.data == "stats":
        total = len(player_mode)
        solo = list(player_mode.values()).count("solo")
        team = list(player_mode.values()).count("team")
        open_teams = len(teams_data)
        banned = len(banned_users)
        bot.send_message(
            chat_id,
            f"""📊 الاحصائيات

👤 اللاعبين الكلي: {total}
🎮 فردي: {solo}
👥 تيم: {team}

🏆 التيمات المفتوحة: {open_teams}
📛 المحظورين: {banned}
"""
        )
        return

    # ---- TEAM CREATE FLOW
    if call.data == "create_team":
        if player_mode.get(uid) != "team":
            bot.send_message(chat_id, "❌ انت مو مختار نظام التيم")
            return
        bot.send_message(chat_id, "اكتب اسم التيم")
        bot.register_next_step_handler(call.message, team_name_step)
        return

    if call.data == "team_confirm_yes":
        team = pending_teams.get(uid)
        if not team:
            return

        mc = minecraft_users.get(uid, {}).get("mc", "Unknown")
        username = call.from_user.username or call.from_user.first_name

        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✅ موافقة", callback_data=f"team_accept_{uid}"),
            InlineKeyboardButton("❌ رفض", callback_data=f"team_reject_{uid}")
        )

        bot.send_message(
            ADMIN_ID,
            f"""{username} ~ {mc}

يريد انشاء تيم
اسم التيم: {team['name']}
عدد الاعضاء: {team['count']}
""",
            reply_markup=kb
        )

        bot.send_message(chat_id, "تم ارسال الطلب للادمن")
        return

    if call.data == "team_confirm_no":
        pending_teams.pop(uid, None)
        bot.send_message(chat_id, "تم الالغاء")
        return

    if call.data.startswith("team_accept_") and is_admin(uid):
        target = int(call.data.split("_")[-1])
        team = pending_teams.get(target)
        if not team:
            return

        if data["server_group"] == "Not Set":
            bot.send_message(ADMIN_ID, "❌ لم يتم تحديد كروب السيرفر")
            return

        bot.send_message(target, "✅ تمت الموافقة على التيم")

        topic = bot.create_forum_topic(
            chat_id=int(data["server_group"]),
            name=team["name"]
        )

        topic_id = topic.message_thread_id

        teams_data[topic_id] = {
            "name": team["name"],
            "needed": int(team["count"]),
            "members": [],
            "owner": target,
            "closed": False
        }

        team_logs[topic_id] = [f"📌 انشاء التيم {team['name']} @ {datetime.datetime.now().strftime('%H:%M')}"]

        owner_mc = minecraft_users.get(target, {}).get("mc", "Unknown")
        owner_user = minecraft_users.get(target, {}).get("user", "Unknown")

        bot.send_message(
            int(data["server_group"]),
            f"""🔥 تيم جديد 🔥

اسم التيم: {team['name']}
عدد الاعضاء المطلوب: {team['count']}

صاحب التيم:
{owner_mc} ~ @{owner_user}

للدخول ارسل كلمة:
تم
""",
            message_thread_id=topic_id
        )

        pending_teams.pop(target, None)
        return

    if call.data.startswith("team_reject_") and is_admin(uid):
        target = int(call.data.split("_")[-1])
        bot.send_message(target, "❌ تم الرفض")
        pending_teams.pop(target, None)
        return

# ================= TEAM STEPS =================
def team_name_step(msg):
    uid = msg.from_user.id
    name = (msg.text or "").strip()
    if not name:
        bot.send_message(msg.chat.id, "❌ ارسل اسم صحيح")
        return
    pending_teams[uid] = {"name": name}
    bot.send_message(msg.chat.id, "كم عدد الاعضاء؟")
    bot.register_next_step_handler(msg, team_count_step)

def team_count_step(msg):
    uid = msg.from_user.id
    txt = (msg.text or "").strip()
    if not txt.isdigit():
        bot.send_message(msg.chat.id, "❌ ارسل رقم صحيح")
        return
    pending_teams[uid]["count"] = int(txt)

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("✅ نعم", callback_data="team_confirm_yes"),
        InlineKeyboardButton("❌ لا", callback_data="team_confirm_no")
    )

    bot.send_message(
        msg.chat.id,
        """⚠️ تنبيه ⚠️

اذا كنت كاعد اجرب الميزه سيتم حظرك من السيرفر ❌

عند موافقتك سيتم ارسال تيمك الى الادمن وانتظر موافقته ✅""",
        reply_markup=kb
    )

# ================= JOIN TEAM =================
@bot.message_handler(func=lambda m: m.text and m.text.strip().lower() == "تم")
def join_team(msg):
    if not getattr(msg, "is_topic_message", False):
        return

    topic_id = msg.message_thread_id
    team = teams_data.get(topic_id)
    if not team:
        return

    uid = msg.from_user.id

    if player_mode.get(uid) == "solo":
        bot.reply_to(msg, "❌ انت اخترت اللعب فردي")
        return

    if uid in user_team:
        bot.reply_to(msg, "⚠️ انت منضم بتيم ثاني")
        return

    if team["needed"] <= 0:
        return

    team["members"].append(uid)
    team["needed"] -= 1
    user_team[uid] = topic_id

    now = datetime.datetime.now().strftime("%H:%M")
    team_logs[topic_id].append(f"➕ دخول {uid} | {now}")

    try:
        bot.send_message(team["owner"], "🔔 عضو جديد دخل التيم")
    except:
        pass

    bot.reply_to(msg, "✅ تم اضافتك للتيم")

    if team["needed"] == 0 and not team["closed"]:
        smart_close_topic(int(data["server_group"]), topic_id)
        team["closed"] = True

# ================= LEAVE TEAM =================
@bot.message_handler(func=lambda m: m.text and "خروج من التيم" in m.text)
def leave_team(msg):
    uid = msg.from_user.id

    if uid not in user_team:
        return

    topic_id = user_team[uid]
    team = teams_data.get(topic_id)
    if not team:
        return

    if uid in team["members"]:
        team["members"].remove(uid)
        team["needed"] += 1

    user_team.pop(uid, None)

    now = datetime.datetime.now().strftime("%H:%M")
    team_logs[topic_id].append(f"➖ خروج {uid} | {now}")

    try:
        bot.send_message(team["owner"], "⚠️ عضو خرج من التيم")
    except:
        pass

    if team["closed"]:
        smart_reopen_topic(int(data["server_group"]), topic_id)
        team["closed"] = False

    bot.send_message(
        int(data["server_group"]),
        needed_text(team["needed"]),
        message_thread_id=topic_id
    )

# ================= SEARCH HELPERS =================
def search_player_name(msg):
    name = (msg.text or "").lower()
    for p in minecraft_users.values():
        if p["mc"].lower() == name:
            bot.send_message(msg.chat.id, f"{p['mc']} ~ @{p['user']}")
            return
    bot.send_message(msg.chat.id, "❌ غير موجود")

def search_banned_user(msg):
    name = (msg.text or "").lower()
    for uid in banned_users:
        try:
            u = bot.get_chat(uid)
            uname = (u.username or u.first_name).lower()
            if name in uname:
                bot.send_message(msg.chat.id, f"✅ الشخص محظور: @{uname}")
                return
        except:
            pass
    bot.send_message(msg.chat.id, "❌ غير موجود")

# ================= SAVE DATA STEPS =================
def save_channel(msg):
    data["channel"] = (msg.text or "").strip()
    bot.send_message(msg.chat.id, "✅ تم حفظ القناة")

def save_group(msg):
    data["server_group"] = (msg.text or "").strip()
    bot.send_message(msg.chat.id, "✅ تم حفظ كروب السيرفر")

def save_ip(msg):
    data["ip"] = (msg.text or "").strip()
    bot.send_message(msg.chat.id, "✅ تم حفظ IP")

def save_port(msg):
    data["port"] = (msg.text or "").strip()
    bot.send_message(msg.chat.id, "✅ تم حفظ PORT")

def save_link(msg):
    data["link"] = (msg.text or "").strip()
    bot.send_message(msg.chat.id, "✅ تم حفظ الرابط")

# ================= CHANNEL LEAVE TRACK =================
@bot.chat_member_handler()
def track_left(update):
    try:
        if data["channel"] == "Not Set":
            return

        if update.chat.username:
            if ("@" + update.chat.username) != data["channel"]:
                return

        old = update.old_chat_member.status
        new = update.new_chat_member.status
        user = update.new_chat_member.user
        uid = user.id

        if old in ["member", "administrator", "creator"] and new in ["left", "kicked"]:
            banned_users.add(uid)

            try:
                if data["server_group"] != "Not Set":
                    bot.ban_chat_member(int(data["server_group"]), uid)
            except:
                pass

            if uid in minecraft_users:
                mc = minecraft_users[uid]["mc"]
                uname = minecraft_users[uid]["user"]
                bot.send_message(ADMIN_ID, f"🚫 غادر القناة وتم حظره: {uname} ~ {mc}")
            else:
                uname = user.username or user.first_name
                bot.send_message(ADMIN_ID, f"🚫 غادر القناة وتم حظره: {uname} (غير مسجل)")

    except Exception as e:
        print(e)

# ================= RUN =================
def run_web():
    app.run(host="0.0.0.0", port=10000)

print("Bot Running...")

threading.Thread(target=run_web).start()

threading.Thread(
    target=lambda: bot.infinity_polling(
        skip_pending=True,
        timeout=60,
        long_polling_timeout=60
    )
).start()
