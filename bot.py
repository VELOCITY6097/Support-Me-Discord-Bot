import discord
import asyncio
import os
import traceback
import re
from discord.ext import commands
from discord import app_commands
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# MongoDB Setup
client = MongoClient(MONGO_URI)
db = client["DiscordBot"]
users_collection = db["users"]
roles_collection = db["roles"]

# Discord Bot Setup
intents = discord.Intents.default()
intents.members = True  # Required for member join events
bot = commands.Bot(command_prefix="!", intents=intents)

# Log channel ID (Set dynamically)
log_channel_id = None


# 📌 Utility Function: Convert Time Format (e.g., 1h -> seconds)
def convert_time(duration: str):
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "y": 31536000}
    match = re.match(r"(\d+)([smhdy])", duration.lower())
    if match:
        return int(match[1]) * time_units[match[2]]
    return None


# 📌 Setup Log Channel
async def setup_log_channel(guild):
    global log_channel_id
    existing_channel = discord.utils.get(guild.channels, name="bot-logs")

    if existing_channel:
        log_channel_id = existing_channel.id
    else:
        new_channel = await guild.create_text_channel("bot-logs")
        log_channel_id = new_channel.id


# 📌 Bot Ready Event
@bot.event
async def on_ready():
    print(f"✅ {bot.user} is online and connected to MongoDB!")

    for guild in bot.guilds:
        await setup_log_channel(guild)

    await bot.tree.sync()
    print("✅ Slash commands synced!")


# 📌 Auto-Register Users on Join
@bot.event
async def on_member_join(member):
    if not users_collection.find_one({"_id": member.id}):
        users_collection.insert_one({
            "_id": member.id,
            "name": member.name,
            "roles": [],
            "banned": False,
            "muted": False
        })
        print(f"✅ {member.name} has been auto-registered in the database.")


# 📌 Error Handling for Commands
@bot.event
async def on_command_error(ctx, error):
    error_msg = f"❌ Error in {ctx.command}: {error}"
    print(error_msg)

    if log_channel_id:
        log_channel = bot.get_channel(log_channel_id)
        if log_channel:
            await log_channel.send(f"🚨 **Error Log** 🚨\n{error_msg}")

    await ctx.send("❌ An error occurred. The issue has been logged.")


# 📌 Error Handling for Slash Commands
@bot.event
async def on_application_command_error(interaction: discord.Interaction, error):
    error_msg = f"❌ Error in {interaction.command.name}: {error}"
    print(error_msg)

    if log_channel_id:
        log_channel = bot.get_channel(log_channel_id)
        if log_channel:
            await log_channel.send(f"🚨 **Error Log** 🚨\n{traceback.format_exc()}")

    await interaction.response.send_message("❌ An error occurred. Check the logs.", ephemeral=True)


# ⚡ **Command: Assign Temporary Role**
@bot.tree.command(name="temprole", description="Assign a temporary role")
@app_commands.describe(user="User to assign role", role="Role to assign", duration="Duration (e.g., 1h, 30m)")
async def temprole(interaction: discord.Interaction, user: discord.Member, role: discord.Role, duration: str):
    await interaction.response.defer()
    
    time_in_seconds = convert_time(duration)
    if time_in_seconds is None:
        return await interaction.followup.send("❌ Invalid time format! Use `1h`, `30m`, etc.")

    await user.add_roles(role)
    roles_collection.insert_one({"user_id": user.id, "role_id": role.id, "expires_in": time_in_seconds})

    await interaction.followup.send(f"✅ {user.mention} has been given {role.mention} for {duration}.")

    await asyncio.sleep(time_in_seconds)
    await user.remove_roles(role)
    roles_collection.delete_one({"user_id": user.id, "role_id": role.id})

    await interaction.followup.send(f"❌ {role.mention} removed from {user.mention} after {duration}.")


# ⚡ **Command: Ban User**
@bot.tree.command(name="ban", description="Ban a user")
@app_commands.describe(user="User to ban", reason="Reason for ban")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.ban_members:
        return await interaction.response.send_message("❌ You don’t have permission to ban!", ephemeral=True)

    await user.ban(reason=reason)
    users_collection.update_one({"_id": user.id}, {"$set": {"banned": True, "ban_reason": reason}}, upsert=True)

    await interaction.response.send_message(f"✅ {user.mention} was banned! Reason: {reason}")


# ⚡ **Command: Mute User**
@bot.tree.command(name="mute", description="Mute a user")
@app_commands.describe(user="User to mute", duration="Duration (e.g., 1h, 30m)")
async def mute(interaction: discord.Interaction, user: discord.Member, duration: str):
    await interaction.response.defer()

    time_in_seconds = convert_time(duration)
    if time_in_seconds is None:
        return await interaction.followup.send("❌ Invalid time format! Use `1h`, `30m`, etc.")

    muted_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not muted_role:
        muted_role = await interaction.guild.create_role(name="Muted", permissions=discord.Permissions(send_messages=False))

    await user.add_roles(muted_role)
    users_collection.update_one({"_id": user.id}, {"$set": {"muted": True}}, upsert=True)

    await interaction.followup.send(f"🔇 {user.mention} has been muted for {duration}.")

    await asyncio.sleep(time_in_seconds)
    await user.remove_roles(muted_role)
    users_collection.update_one({"_id": user.id}, {"$set": {"muted": False}}, upsert=True)

    await interaction.followup.send(f"🔊 {user.mention} has been unmuted.")


# ⚡ **Command: Unmute User**
@bot.tree.command(name="unmute", description="Unmute a user")
@app_commands.describe(user="User to unmute")
async def unmute(interaction: discord.Interaction, user: discord.Member):
    muted_role = discord.utils.get(interaction.guild.roles, name="Muted")

    if muted_role in user.roles:
        await user.remove_roles(muted_role)
        users_collection.update_one({"_id": user.id}, {"$set": {"muted": False}}, upsert=True)
        await interaction.response.send_message(f"🔊 {user.mention} has been unmuted.")
    else:
        await interaction.response.send_message("❌ User is not muted!", ephemeral=True)


# ⚡ **Command: Get User Info**
@bot.tree.command(name="userinfo", description="Get user information from the database")
@app_commands.describe(user="User to check")
async def userinfo(interaction: discord.Interaction, user: discord.Member):
    user_data = users_collection.find_one({"_id": user.id})
    if not user_data:
        return await interaction.response.send_message(f"❌ {user.mention} is not registered!", ephemeral=True)

    mute_status = "🔇 **Muted**" if user_data.get("muted") else "✅ Not Muted"
    embed = discord.Embed(title=f"User Info - {user.name}", color=discord.Color.blue())
    embed.add_field(name="🚨 Status", value=mute_status, inline=False)

    await interaction.response.send_message(embed=embed)


# 🔥 **Run the Bot**
bot.run(TOKEN)
