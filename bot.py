import discord
import asyncio
import os
import sys
import traceback
import re
from discord.ext import commands
from discord import app_commands
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime, timedelta

import discord
from discord import app_commands
import os
import sys
import asyncio
import re
from pymongo import MongoClient
from dotenv import load_dotenv

# 📌 Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# 📌 MongoDB Setup
client = MongoClient(MONGO_URI)
db = client["DiscordBot"]
users_collection = db["users"]

# 📌 Bot Class (Slash Commands Only)
class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)
        self.log_channel_id = None  # Set dynamically

    async def on_ready(self):
        print(f"✅ {self.user} is online and connected to MongoDB!")
        
        for guild in self.guilds:
            await self.setup_log_channel(guild)

        await self.tree.sync()  # Sync slash commands
        print("✅ Slash commands synced!")

        # 🔹 Check if restart file exists (To send success message)
        if os.path.exists("restart_status.txt"):
            with open("restart_status.txt", "r") as f:
                channel_id = int(f.read().strip())
                channel = self.get_channel(channel_id)
                if channel:
                    await channel.send("✅ **Bot restarted successfully and is back online!**")
            os.remove("restart_status.txt")  # Cleanup file after sending the message

    async def setup_log_channel(self, guild):
        """Ensure 'bot-logs' channel exists in every server."""
        existing_channel = discord.utils.get(guild.channels, name="bot-logs")
        if existing_channel:
            self.log_channel_id = existing_channel.id
        else:
            new_channel = await guild.create_text_channel("bot-logs")
            self.log_channel_id = new_channel.id


# 📌 Convert Time Format (e.g., "1h" → seconds)
def convert_time(duration: str):
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "y": 31536000}
    match = re.match(r"(\d+)([smhdy])", duration.lower())
    if match:
        return int(match[1]) * time_units[match[2]]
    return None


# 📌 Create Bot Instance
bot = MyBot()

# 📌 Slash Command: Restart Bot
@bot.tree.command(name="restart", description="Restart the bot and refresh the database")
async def restart(interaction: discord.Interaction):
    authorized_user_id = 812347860128497694  # 🔹 Replace with your Discord ID

    if interaction.user.id != authorized_user_id:
        return await interaction.response.send_message("⛔ You are not authorized to restart the bot!", ephemeral=True)

    await interaction.response.send_message("🔄 **Restarting bot and refreshing database...**", ephemeral=True)

    # 🔹 Refresh MongoDB connection
    global client, db, users_collection
    client.close()  # Close old MongoDB connection
    client = MongoClient(MONGO_URI)  # Reconnect
    db = client["DiscordBot"]
    users_collection = db["users"]
    print("✅ Database connection refreshed!")

    # 🔹 Save restart indicator (so bot can send a message after restart)
    with open("restart_status.txt", "w") as f:
        f.write(str(interaction.channel.id))

    # 🔹 Restart the bot without closing CMD
    print("🔄 Restarting bot...")
    os.execv(sys.executable, [sys.executable] + sys.argv)


#-----------------------------------------------------------------------------------------------

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


#record penalties

async def record_penalty(user_id: int, penalty_type: str, reason: str = "No reason provided"):
    """Asynchronously records a mute or ban penalty in the user's history."""
    penalty_entry = {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),  # Store the date of the penalty
        "reason": reason
    }
    
    if penalty_type == "mute":
        await users_collection.update_one({"_id": user_id}, {"$push": {"mute_history": penalty_entry}}, upsert=True)
    elif penalty_type == "ban":
        await users_collection.update_one({"_id": user_id}, {"$push": {"ban_history": penalty_entry}}, upsert=True)

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

class CopyUserIDButton(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.add_item(CopyUserIDButton.CopyButton(user_id))

    class CopyButton(discord.ui.Button):
        def __init__(self, user_id: int):
            super().__init__(label="📋 Copy User ID", style=discord.ButtonStyle.primary, custom_id=f"copy_{user_id}")
            self.user_id = user_id

        async def callback(self, interaction: discord.Interaction):
            await interaction.response.send_message(
                f"✅ Copied!\n```\n{self.user_id}\n```",
                ephemeral=True
            )

@bot.tree.command(name="userinfo", description="Get user information from the database")
@app_commands.describe(user="User to check")
async def userinfo(interaction: discord.Interaction, user: discord.Member):
    user_data = users_collection.find_one({"_id": user.id})
    if not user_data:
        return await interaction.response.send_message(f"❌ {user.mention} is not registered!", ephemeral=True)

    # 🔹 Check if user is muted
    mute_status = "🔇 **Muted**" if user_data.get("muted") else "✅ Not Muted"

    # 🔹 Get join date
    join_date = user.joined_at.strftime("%Y-%m-%d %H:%M:%S") if user.joined_at else "Unknown"

    # 🔹 Check if user is banned
    try:
        ban_entry = await interaction.guild.fetch_ban(user)
        ban_status = f"❌ **Banned** (Reason: {ban_entry.reason})" if ban_entry else "✅ Not Banned"
    except discord.NotFound:
        ban_status = "✅ Not Banned"

    # 🔹 Check for penalties in the last 30 days
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_penalties = []
    
    if "mute_history" in user_data:
        recent_mutes = [m for m in user_data["mute_history"] if datetime.strptime(m["date"], "%Y-%m-%d") >= thirty_days_ago]
        if recent_mutes:
            recent_penalties.append(f"🔇 **Muted {len(recent_mutes)} times** in the last 30 days")

    if "ban_history" in user_data:
        recent_bans = [b for b in user_data["ban_history"] if datetime.strptime(b["date"], "%Y-%m-%d") >= thirty_days_ago]
        if recent_bans:
            recent_penalties.append(f"🚫 **Banned {len(recent_bans)} times** in the last 30 days")

    penalty_status = "\n".join(recent_penalties) if recent_penalties else "✅ No penalties in the last 30 days"

    # 📌 Create Embed
    embed = discord.Embed(title=f"User Info - {user.name}", color=discord.Color.blue())
    embed.add_field(name="🆔 ID", value=f"`{user.id}`", inline=True)
    embed.add_field(name="🚨 Status", value=mute_status, inline=True)
    embed.add_field(name="🚫 Ban Status", value=ban_status, inline=False)
    embed.add_field(name="📅 Joined Server", value=join_date, inline=False)
    embed.add_field(name="⚖️ Recent Penalties", value=penalty_status, inline=False)

    view = CopyUserIDButton(user.id)  # Attach the copy button

    await interaction.response.send_message(embed=embed, view=view)



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

# ⚡ **Command: Unban User**
@bot.tree.command(name="unban", description="Unban a user using their ID")
@app_commands.describe(user_id="User ID to unban")
async def unban(interaction: discord.Interaction, user_id: str):
    """Unbans a user from the server."""
    
    # Check if the command user has permission to unban
    if not interaction.user.guild_permissions.ban_members:
        return await interaction.response.send_message("⛔ You don’t have permission to unban users!", ephemeral=True)

    try:
        user_id = int(user_id)  # Convert to integer
        banned_users = await interaction.guild.bans()  # Get ban list

        # Find the user in the ban list
        banned_user = next((ban_entry.user for ban_entry in banned_users if ban_entry.user.id == user_id), None)

        if banned_user:
            await interaction.guild.unban(banned_user)
            users_collection.update_one({"_id": user_id}, {"$set": {"banned": False, "ban_reason": None}}, upsert=True)

            await interaction.response.send_message(f"✅ {banned_user.mention} has been unbanned!")
        else:
            await interaction.response.send_message("❌ User is not banned!", ephemeral=True)

    except ValueError:
        await interaction.response.send_message("❌ Invalid user ID! Please enter a valid numeric ID.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don’t have permission to unban this user!", ephemeral=True)
    except Exception as e:
        error_msg = f"❌ Error in /unban: {e}"
        print(error_msg)

        # Log the error in bot logs
        if bot.log_channel_id:
            log_channel = bot.get_channel(bot.log_channel_id)
            if log_channel:
                await log_channel.send(f"🚨 **Error Log** 🚨\n```{error_msg}```")

        await interaction.response.send_message("❌ An error occurred while unbanning! Check the logs.", ephemeral=True)



# ⚡ **Command: Mute User**
def convert_time(duration: str):
    """Converts time duration (e.g., '1h', '30m', '45s') into seconds."""
    try:
        unit = duration[-1]
        value = int(duration[:-1])
        if unit == 'h':
            return value * 3600
        elif unit == 'm':
            return value * 60
        elif unit == 's':
            return value
    except ValueError:
        return None  # Invalid format

@bot.tree.command(name="mute", description="Mute a user")
@app_commands.describe(user="User to mute", duration="Duration (e.g., 1h, 30m, 45s)", reason="Reason for mute")
async def mute(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str = "No reason provided"):
    await interaction.response.defer()

    time_in_seconds = convert_time(duration)
    if time_in_seconds is None:
        return await interaction.followup.send("❌ Invalid time format! Use `1h`, `30m`, `45s`, etc.", ephemeral=True)

    # Check if user is already muted
    existing_mute = users_collection.find_one({"_id": user.id, "muted": True})
    if existing_mute:
        return await interaction.followup.send(f"⚠️ {user.mention} is already muted!", ephemeral=True)

    # Get or create the 'Muted' role
    muted_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not muted_role:
        muted_role = await interaction.guild.create_role(name="Muted", permissions=discord.Permissions(send_messages=False))
        for channel in interaction.guild.channels:
            await channel.set_permissions(muted_role, send_messages=False, speak=False)

    # Add muted role to user
    await user.add_roles(muted_role)
    mute_end_time = datetime.utcnow() + timedelta(seconds=time_in_seconds)

    # Save mute status in DB
    users_collection.update_one(
        {"_id": user.id},
        {
            "$set": {"muted": True, "mute_end": mute_end_time.isoformat()},
            "$push": {"mute_history": {"date": datetime.utcnow().strftime("%Y-%m-%d"), "reason": reason}}
        },
        upsert=True
    )

    await interaction.followup.send(f"🔇 {user.mention} has been muted for `{duration}`. Reason: `{reason}`")

    # Unmute logic after duration
    await asyncio.sleep(time_in_seconds)

    # Ensure user is still in the server before unmuting
    if user in interaction.guild.members:
        await user.remove_roles(muted_role)
        users_collection.update_one({"_id": user.id}, {"$set": {"muted": False}})
        await interaction.channel.send(f"🔊 {user.mention} has been unmuted.")

# ⚡ **Command: Unmute User**
@bot.tree.command(name="unmute", description="Unmute a user manually")
@app_commands.describe(user="User to unmute")
async def unmute(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()

    muted_role = discord.utils.get(interaction.guild.roles, name="Muted")
    if not muted_role or muted_role not in user.roles:
        return await interaction.followup.send(f"⚠️ {user.mention} is not muted!", ephemeral=True)

    await user.remove_roles(muted_role)
    users_collection.update_one({"_id": user.id}, {"$set": {"muted": False}})

    await interaction.followup.send(f"🔊 {user.mention} has been manually unmuted.")





# 🔥 **Run the Bot**
bot.run(TOKEN)
