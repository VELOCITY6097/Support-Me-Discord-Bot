import discord
from discord import app_commands
from discord.ext import commands, tasks
import time

# Start time for uptime calculation
BOT_START_TIME = time.time()

def get_bot_uptime() -> str:
    """Returns the bot's uptime as a formatted string."""
    seconds = int(time.time() - BOT_START_TIME)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}h {minutes}m {secs}s"

class Owner(commands.Cog):
    """
    📌 A Cog for bot owner commands, including a live status panel.
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.live_info_message = None  # Stores the persistent embed message
        self.update_live_info.start()  # Starts the auto-update loop

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Ensures only the bot owner can use these commands."""
        return await self.bot.is_owner(ctx.author)

    async def generate_live_embed(self) -> discord.Embed:
        """Generates a large, styled embed with bot info."""
        ping = round(self.bot.latency * 1000, 2)
        uptime = get_bot_uptime()
        server_count = len(self.bot.guilds)
        online_status = "🟢 **Online**"
        app_info = await self.bot.application_info()
        owner = app_info.owner

        embed = discord.Embed(
            title=f"🤖 {self.bot.user.name} - Live Status",
            description="📊 **Real-time bot statistics** (auto-refreshing every 5 seconds)",
            color=discord.Color.green()
        )
        embed.add_field(name="📡 **Ping**", value=f"⚡ `{ping} ms`", inline=True)
        embed.add_field(name="⏳ **Uptime**", value=f"🔄 `{uptime}`", inline=True)
        embed.add_field(name="🌍 **Servers**", value=f"🏠 `{server_count}`", inline=True)
        embed.add_field(name="🔌 **Status**", value=online_status, inline=True)
        embed.add_field(name="👑 **Owner**", value=f"🛠️ `{owner}`", inline=True)
        embed.set_footer(text="🔄 This panel updates every 5 seconds | Support Me Bot")
        return embed

    @app_commands.command(name="liveinfo", description="Displays a live bot info panel (Owner Only)")
    async def liveinfo(self, interaction: discord.Interaction):
        """
        Posts a live status embed that updates automatically every 5 seconds.
        """
        embed = await self.generate_live_embed()
        
        # Button to contact the owner
        view = discord.ui.View()
        contact_button = discord.ui.Button(
            label="📞 Contact Me",
            style=discord.ButtonStyle.link,
            url="https://discordapp.com/users/812347860128497694"  # Replace with actual invite or contact URL
        )
        view.add_item(contact_button)

        # Send initial message
        await interaction.response.send_message(embed=embed, view=view, ephemeral=False)
        self.live_info_message = await interaction.original_response()

    @tasks.loop(seconds=5.0)  # Refresh every 5 seconds
    async def update_live_info(self):
        """Background task that updates the live status embed every 5 seconds."""
        if self.live_info_message is None:
            return  # No message to update
        try:
            embed = await self.generate_live_embed()
            view = discord.ui.View()
            contact_button = discord.ui.Button(
                label="📞 Contact Me",
                style=discord.ButtonStyle.link,
                url="https://discordapp.com/users/812347860128497694"  # Replace with actual URL
            )
            view.add_item(contact_button)

            await self.live_info_message.edit(embed=embed, view=view)
        except Exception as e:
            print(f"Error updating live info message: {e}")

    @update_live_info.before_loop
    async def before_update_live_info(self):
        await self.bot.wait_until_ready()

    async def cog_unload(self):
        """Stops the update task when the cog is unloaded."""
        self.update_live_info.cancel()

async def setup(bot: commands.Bot):
    await bot.add_cog(Owner(bot))


