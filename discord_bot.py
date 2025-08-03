import os
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

LOG_CHANNEL_ID = int(os.getenv("DISCORD_LOG_CHANNEL_ID", 0))
GUILD_ID = int(os.getenv("DISCORD_GUILD_ID", 0))
ROLE_ID = int(os.getenv("DISCORD_ROLE_ID", 0))

user_tokens = {}

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")
    try:
        await bot.tree.sync()
        print("Slash commands synced.")
    except Exception as e:
        print(f"Sync error: {e}")

async def send_log(content=None, embed=None):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        print("⚠️ ログチャンネルが見つかりません")
        return

    if embed:
        embed_obj = discord.Embed(
            title=embed.get("title", "ログ"),
            description=embed.get("description", ""),
            color=0x00ff00
        )
        if "thumbnail" in embed and embed["thumbnail"]:
            embed_obj.set_thumbnail(url=embed["thumbnail"]["url"])
        await channel.send(embed=embed_obj)
    elif content:
        await channel.send(content)

async def assign_role(user_id):
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        print("⚠️ Guild not found.")
        return

    member = guild.get_member(int(user_id))
    if not member:
        try:
            member = await guild.fetch_member(int(user_id))
        except Exception as e:
            print("⚠️ メンバー取得失敗:", e)
            return

    role = guild.get_role(ROLE_ID)
    if role and member:
        try:
            await member.add_roles(role, reason="認証通過により自動付与")
            print(f"✅ {member} にロールを付与しました。")
        except Exception as e:
            print("⚠️ ロール付与失敗:", e)

@bot.tree.command(name="adduser", description="ユーザーをサーバーに追加します")
@discord.app_commands.describe(user_id="追加したいユーザーID", guild_id="サーバーID")
async def adduser(interaction: discord.Interaction, user_id: str, guild_id: str):
    token = user_tokens.get(user_id)
    if not token:
        await interaction.response.send_message(f"ユーザー {user_id} のアクセストークンが見つかりません。", ephemeral=True)
        return

    url = f"https://discord.com/api/guilds/{guild_id}/members/{user_id}"
    headers = {
        "Authorization": f"Bot {os.getenv('DISCORD_BOT_TOKEN')}",
        "Content-Type": "application/json"
    }
    json_data = {"access_token": token}

    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=headers, json=json_data) as resp:
            if resp.status in [201, 204]:
                await interaction.response.send_message(f"ユーザー {user_id} をサーバー {guild_id} に追加しました！")
            else:
                text = await resp.text()
                await interaction.response.send_message(f"追加失敗: {resp.status} {text}", ephemeral=True)

# Flask側で使えるように登録
bot.send_log = send_log
bot.assign_role = assign_role