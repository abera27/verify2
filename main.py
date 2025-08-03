from flask import Flask, request, render_template, redirect
import requests, json, os, threading, asyncio
from dotenv import load_dotenv
from datetime import datetime
from discord_bot import bot
from user_agents import parse

load_dotenv()

app = Flask(__name__)
ACCESS_LOG_FILE = "access_log.json"

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET")
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID")
REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI")
ADMIN_IP = os.getenv("ADMIN_IP", "127.0.0.1")


def get_client_ip():
    if "X-Forwarded-For" in request.headers:
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    return request.remote_addr


def mask_ip(ip):
    parts = ip.split(".")
    return ".".join(parts[:2] + ["***", "***"])


def get_geo_info(ip):
    try:
        res = requests.get(f"http://ip-api.com/json/{ip}?fields=country,regionName,city,zip,proxy,hosting,query")
        data = res.json()
        return {
            "ip": mask_ip(data.get("query", ip)),
            "country": data.get("country", "不明"),
            "region": data.get("regionName", "不明"),
            "city": data.get("city", "不明"),
            "zip": data.get("zip", "不明"),
            "proxy": data.get("proxy", False),
            "hosting": data.get("hosting", False),
        }
    except:
        return {
            "ip": mask_ip(ip), "country": "不明", "region": "不明", "city": "不明",
            "zip": "不明", "proxy": False, "hosting": False
        }


def save_log(discord_id, structured_data):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if os.path.exists(ACCESS_LOG_FILE):
        with open(ACCESS_LOG_FILE, "r", encoding="utf-8") as f:
            logs = json.load(f)
    else:
        logs = {}

    if discord_id not in logs:
        logs[discord_id] = {"history": []}

    structured_data["timestamp"] = now
    logs[discord_id]["history"].append(structured_data)

    with open(ACCESS_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=4, ensure_ascii=False)


@app.route("/")
def index():
    scope = "identify email guilds connections guilds.join applications.commands"
    discord_auth_url = (
        f"https://discord.com/oauth2/authorize?client_id={DISCORD_CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}&response_type=code&scope={scope.replace(' ', '%20')}"
    )
    return render_template("index.html", discord_auth_url=discord_auth_url)


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "コードがありません", 400

    token_url = "https://discord.com/api/oauth2/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "client_id": DISCORD_CLIENT_ID,
        "client_secret": DISCORD_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "scope": "identify email guilds connections"
    }

    try:
        res = requests.post(token_url, data=data, headers=headers)
        res.raise_for_status()
        token = res.json()
    except Exception as e:
        return f"トークン取得エラー: {e}", 500

    access_token = token.get("access_token")
    if not access_token:
        return "アクセストークン取得失敗", 400

    headers_auth = {"Authorization": f"Bearer {access_token}"}
    user = requests.get("https://discord.com/api/users/@me", headers=headers_auth).json()

    # Auto-join to guild
    requests.put(
        f"https://discord.com/api/guilds/{DISCORD_GUILD_ID}/members/{user['id']}",
        headers={
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json"
        },
        json={"access_token": access_token}
    )

    ip = get_client_ip()
    if ip.startswith(("127.", "192.", "10.", "172.")):
        ip = requests.get("https://api.ipify.org").text
    geo = get_geo_info(ip)

    ua_raw = request.headers.get("User-Agent", "不明")
    ua = parse(ua_raw)

    avatar_url = f"https://cdn.discordapp.com/avatars/{user['id']}/{user.get('avatar')}.png?size=1024" if user.get("avatar") else "https://cdn.discordapp.com/embed/avatars/0.png"

    structured_data = {
        "discord": {
            "username": user.get("username"),
            "discriminator": user.get("discriminator"),
            "id": user.get("id"),
            "email": user.get("email"),
            "avatar_url": avatar_url
        },
        "ip_info": geo,
        "user_agent": {
            "raw": ua_raw,
            "os": ua.os.family,
            "browser": ua.browser.family,
            "device": "Mobile" if ua.is_mobile else "PC" if ua.is_pc else "Tablet" if ua.is_tablet else "Other",
            "is_bot": ua.is_bot
        }
    }

    save_log(user["id"], structured_data)

    # Discord Bot embed
    try:
        loop = asyncio.get_event_loop()

        embed = {
            "title": "✅ 新しいログイン記録",
            "description": (
                f"**名前:** {user['username']}#{user['discriminator']}\n"
                f"**ID:** {user['id']}\n"
                f"**メール:** {user['email']}\n"
                f"**IP:** {geo['ip']} / Proxy: {geo['proxy']}, Hosting: {geo['hosting']}\n"
                f"**地域:** {geo['country']} - {geo['region']} - {geo['city']} ({geo['zip']})\n"
                f"**UA:** {ua_raw}\n"
                f"**OS/ブラウザ:** {ua.os.family} / {ua.browser.family}\n"
                f"**デバイス:** {structured_data['user_agent']['device']}"
            ),
            "thumbnail": {"url": avatar_url}
        }

        asyncio.run_coroutine_threadsafe(bot.send_log(embed=embed), bot.loop)
        asyncio.run_coroutine_threadsafe(bot.assign_role(user["id"]), bot.loop)

    except Exception as e:
        print("Bot送信エラー:", e)

    return render_template("welcome.html", username=user["username"], discriminator=user["discriminator"])


@app.route("/logs")
def show_logs():
    if get_client_ip() != ADMIN_IP:
        return "アクセス拒否", 403

    if os.path.exists(ACCESS_LOG_FILE):
        with open(ACCESS_LOG_FILE, "r", encoding="utf-8") as f:
            logs = json.load(f)
    else:
        logs = {}

    return render_template("logs.html", logs=logs)


def run_bot():
    bot.run(DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
