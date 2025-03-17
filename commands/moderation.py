import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta, timezone
import asyncio
import re

# 📌 Import helper functions and database collections from utils
from utils.time_utils import convert_time
from utils.permissions import check_moderation_access
from utils.database import users_collection, roles_collection

# 📌 A view containing a button to copy the User ID.
class CopyUserIDView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id

    @discord.ui.button(label="Copy User ID", style=discord.ButtonStyle.primary, custom_id="copy_user_id")
    async def copy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        📌 Button callback: Sends an ephemeral message with the user ID.
        """
        await interaction.response.send_message(f"🔢 User ID: `{self.user_id}`", ephemeral=True)

# 📌 Moderation Cog: Contains moderation commands.
class Moderation(commands.Cog):
    """
    📌 A Cog containing moderation commands.
    📌 These commands are restricted via permission checks.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.describe(user="User to timeout", duration="Duration (e.g., 1h, 30m, 45s)", reason="Reason for timeout")
    @app_commands.command(name="timeout", description="Timeout a user (Moderation)")
    async def timeout(self, interaction: discord.Interaction, user: discord.Member, duration: str, reason: str = "No reason provided"):
        """
        📌 The /timeout command times out a user for a given duration.
        📌 Converts the duration string to seconds, applies the timeout, updates the database, and schedules removal.
        """
        # 📌 Defer response so we can process the command in the background (ephemeral response)
        await interaction.response.defer(ephemeral=True)

        # 📌 Convert the duration string to seconds.
        time_in_seconds = convert_time(duration)
        if time_in_seconds is None:
            return await interaction.followup.send("❌ Invalid time format! Use `1h`, `30m`, or `45s`.", ephemeral=True)

        # 📌 Use discord's UTC helper to ensure consistency.
        now = discord.utils.utcnow()
        until = now + timedelta(seconds=time_in_seconds)

        try:
            await user.timeout(until, reason=reason)
        except Exception as e:
            return await interaction.followup.send(f"❌ Failed to timeout user: {e}", ephemeral=True)

        # 📌 Update the database with timeout details.
        users_collection.update_one(
            {"_id": user.id},
            {"$set": {"muted": True, "mute_end": until.isoformat()},
             "$push": {"timeout_history": {"date": now.strftime("%Y-%m-%d"), "reason": reason}}},
            upsert=True
        )

        await interaction.followup.send(f"🔇 {user.mention} has been timed out for `{duration}`. Reason: `{reason}`")

        # 📌 Schedule a background task to remove the timeout after the specified duration.
        self.bot.loop.create_task(self.remove_timeout_after(user, time_in_seconds))

    async def remove_timeout_after(self, user: discord.Member, delay: int):
        """
        📌 Background task to remove the timeout after a delay.
        """
        await asyncio.sleep(delay)
        try:
            await user.timeout(None, reason="Timeout expired")
        except Exception as e:
            if user.guild.system_channel:
                await user.guild.system_channel.send(f"❌ Failed to remove timeout for {user.mention}: {e}")
            return
        users_collection.update_one({"_id": user.id}, {"$set": {"muted": False}})
        if user.guild.system_channel:
            await user.guild.system_channel.send(f"🔊 {user.mention} is no longer timed out.")

    @app_commands.describe(user="User to remove timeout from")
    @app_commands.command(name="removetimeout", description="Remove timeout from a user manually (Moderation)")
    async def removetimeout(self, interaction: discord.Interaction, user: discord.Member):
        """
        📌 The /removetimeout command manually removes a timeout from a user.
        """
        await interaction.response.defer(ephemeral=True)
        if not user.timed_out_until or user.timed_out_until <= discord.utils.utcnow():
            return await interaction.followup.send(f"⚠️ {user.mention} is not currently timed out!", ephemeral=True)
        try:
            await user.timeout(None, reason="Manual timeout removal")
        except Exception as e:
            return await interaction.followup.send(f"❌ Failed to remove timeout: {e}", ephemeral=True)
        users_collection.update_one({"_id": user.id}, {"$set": {"muted": False}})
        await interaction.followup.send(f"🔊 {user.mention} has been removed from timeout.")

    @app_commands.describe(user="User to ban", reason="Reason for ban")
    @app_commands.command(name="ban", description="Ban a user (Moderation)")
    async def ban(self, interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
        """
        📌 The /ban command bans a user.
        📌 It checks if the invoker has the required permissions before banning.
        """
        if not await check_moderation_access(interaction, interaction.user):
            return
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("❌ You don’t have permission to ban users!", ephemeral=True)
        try:
            await user.ban(reason=reason)
        except Exception as e:
            return await interaction.response.send_message(f"❌ Failed to ban {user.mention}: {e}", ephemeral=True)
        users_collection.update_one({"_id": user.id}, {"$set": {"banned": True, "ban_reason": reason}}, upsert=True)
        await interaction.response.send_message(f"✅ {user.mention} was banned! Reason: {reason}")

    @app_commands.describe(user_id="User ID of the user to unban", reason="Reason for unban (optional)")
    @app_commands.command(name="unban", description="Unban a user by their ID (Moderation)")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
        """
        📌 The /unban command unbans a user using their numeric ID.
        📌 It iterates over the ban list to find the user to unban.
        """
        if not await check_moderation_access(interaction, interaction.user):
            return
        if not interaction.user.guild_permissions.ban_members:
            return await interaction.response.send_message("⛔ You don’t have permission to unban users!", ephemeral=True)
        try:
            user_id_int = int(user_id)
        except ValueError:
            return await interaction.response.send_message("❌ Invalid user ID format. Please provide a valid numeric ID.", ephemeral=True)
        try:
            user_to_unban = None
            async for ban_entry in interaction.guild.bans():
                if ban_entry.user.id == user_id_int:
                    user_to_unban = ban_entry.user
                    break
            if user_to_unban is None:
                return await interaction.response.send_message("❌ That user is not currently banned.", ephemeral=True)
            await interaction.guild.unban(user_to_unban, reason=reason)
            users_collection.update_one({"_id": user_id_int}, {"$set": {"banned": False}}, upsert=True)
            await interaction.response.send_message(f"✅ Successfully unbanned {user_to_unban.mention}!")
        except discord.Forbidden:
            await interaction.response.send_message("❌ I don't have permission to unban users.", ephemeral=True)

    @app_commands.describe(user="User to assign temporary role", role="Role to assign", duration="Duration (e.g., 1h, 30m, 45s)")
    @app_commands.command(name="temprole", description="Assign a temporary role to a user (Moderation)")
    async def temprole(self, interaction: discord.Interaction, user: discord.Member, role: discord.Role, duration: str):
        """
        📌 The /temprole command assigns a temporary role to a user for a given duration.
        """
        time_in_seconds = convert_time(duration)
        if time_in_seconds is None:
            return await interaction.response.send_message("❌ Invalid time format! Use `1h`, `30m`, or `45s`.", ephemeral=True)
        # 📌 Assign the role to the user.
        await user.add_roles(role, reason="Temporary role assignment")
        await interaction.response.send_message(f"✅ {role.mention} role has been assigned to {user.mention} for `{duration}`.")
        # 📌 Wait for the duration to expire, then remove the role.
        await asyncio.sleep(time_in_seconds)
        await user.remove_roles(role, reason="Temporary role expired")
        if interaction.channel:
            await interaction.channel.send(f"🔔 The temporary role {role.mention} for {user.mention} has expired.")

    @app_commands.describe(user="User to get information about")
    @app_commands.command(name="userinfo", description="Get information about a user (Moderation)")
    async def userinfo(self, interaction: discord.Interaction, user: discord.Member = None):
        """
        📌 The /userinfo command displays information about a user.
        📌 If no user is provided, it defaults to the command invoker.
        📌 It shows penalty details (timeouts, bans, and mutes in the last 30 days) and active penalties.
        """
        user = user or interaction.user

        # 📌 Retrieve user penalty data from the database.
        doc = users_collection.find_one({"_id": user.id}) or {}
        timeout_history = doc.get("timeout_history", [])
        now_date = datetime.utcnow().date()
        count_timeouts = 0
        for entry in timeout_history:
            try:
                entry_date = datetime.strptime(entry.get("date", ""), "%Y-%m-%d").date()
                if (now_date - entry_date).days <= 30:
                    count_timeouts += 1
            except Exception:
                continue

        banned_status = doc.get("banned", False)
        ban_status_str = "🚫 Banned" if banned_status else "✅ Not banned"

        active_penalties = []
        if user.timed_out_until and user.timed_out_until > discord.utils.utcnow():
            active_penalties.append("⏳ Active Timeout")
        if banned_status:
            active_penalties.append("🚫 Active Ban")
        active_penalties_str = ", ".join(active_penalties) if active_penalties else "None"

        # 📌 Create an embed to display user information with emojis.
        embed = discord.Embed(
            title="👤 User Information",
            color=discord.Color.blue(),
            timestamp=discord.utils.utcnow()
        )
        avatar_url = user.avatar.url if user.avatar else user.default_avatar.url
        embed.set_thumbnail(url=avatar_url)

        # 📌 Add basic user details.
        embed.add_field(name="👤 Username", value=str(user), inline=True)
        embed.add_field(name="🔢 User ID", value=user.id, inline=True)
        embed.add_field(name="📆 Account Created", value=user.created_at.strftime("%Y-%m-%d %H:%M:%S UTC"), inline=False)

        # 📌 If used in a guild, add server-specific information.
        if interaction.guild:
            member = interaction.guild.get_member(user.id)
            if member:
                joined_at = member.joined_at.strftime("%Y-%m-%d %H:%M:%S UTC") if member.joined_at else "N/A"
                embed.add_field(name="🤝 Joined Server", value=joined_at, inline=False)
                roles = [role.mention for role in member.roles if role.name != "@everyone"]
                embed.add_field(name="🎭 Roles", value=", ".join(roles) if roles else "None", inline=False)

        # 📌 Add penalty information fields.
        embed.add_field(name="⏳ Timeouts (Last 30 days)", value=str(count_timeouts), inline=True)
        embed.add_field(name="🚫 Ban Status", value=ban_status_str, inline=True)
        embed.add_field(name="⚠️ Active Penalties", value=active_penalties_str, inline=False)

        # 📌 Create a view with a button to copy the User ID.
        view = CopyUserIDView(user.id)
        await interaction.response.send_message(embed=embed, view=view)

# 📌 Setup function to add this Cog to the bot.
async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
