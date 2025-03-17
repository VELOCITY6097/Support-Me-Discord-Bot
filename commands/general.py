import discord
from discord import app_commands
from discord.ext import commands
from utils.database import settings_collection

# -------------------- UI VIEWS --------------------
class SettingsView(discord.ui.View):
    """📌 Main settings view with buttons for different settings."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CommandAccessButton())

class CommandAccessView(discord.ui.View):
    """📌 View for Command Access settings (Shows info + buttons)."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(AddAllowlistButton())
        self.add_item(RemoveAllowlistButton())
        self.add_item(AddBlacklistButton())
        self.add_item(RemoveBlacklistButton())

    @staticmethod
    def get_embed():
        """📌 Fetches and returns the current Command Access settings embed."""
        data = settings_collection.find_one({"_id": "command_access"}) or {}
        allowed_roles = data.get("allowlist", [])
        blacklisted_roles = data.get("blacklist", [])

        embed = discord.Embed(title="🔧 Command Access Settings", color=discord.Color.blue())
        embed.add_field(name="✅ Allowed Roles", value='\n'.join(f"<@&{r}>" for r in allowed_roles) or "None", inline=False)
        embed.add_field(name="🚫 Blacklisted Roles", value='\n'.join(f"<@&{r}>" for r in blacklisted_roles) or "None", inline=False)
        return embed

# -------------------- BUTTONS --------------------
class CommandAccessButton(discord.ui.Button):
    """📌 Button to open Command Access settings."""
    def __init__(self):
        super().__init__(label="🔧 Command Access", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        """📌 Displays the command access settings."""
        embed = CommandAccessView.get_embed()
        await interaction.response.edit_message(embed=embed, view=CommandAccessView())

class RoleManagementButton(discord.ui.Button):
    """📌 Parent class for role management buttons."""
    def __init__(self, label, style, role_type, remove):
        super().__init__(label=label, style=style)
        self.role_type = role_type
        self.remove = remove

    async def callback(self, interaction: discord.Interaction):
        """📌 Opens the role selection dropdown for allowlist or blacklist."""
        view = RoleSelectionView(self.role_type, self.remove, interaction.guild)
        await interaction.response.edit_message(view=view)

class AddAllowlistButton(RoleManagementButton):
    """📌 Button to add roles to the allowlist."""
    def __init__(self):
        super().__init__("✅ Add Allowlist Role", discord.ButtonStyle.success, "allowlist", False)

class RemoveAllowlistButton(RoleManagementButton):
    """📌 Button to remove roles from the allowlist."""
    def __init__(self):
        super().__init__("❌ Remove Allowlist Role", discord.ButtonStyle.danger, "allowlist", True)

class AddBlacklistButton(RoleManagementButton):
    """📌 Button to add roles to the blacklist."""
    def __init__(self):
        super().__init__("🚫 Add Blacklist Role", discord.ButtonStyle.primary, "blacklist", False)

class RemoveBlacklistButton(RoleManagementButton):
    """📌 Button to remove roles from the blacklist."""
    def __init__(self):
        super().__init__("❌ Remove Blacklist Role", discord.ButtonStyle.danger, "blacklist", True)

# -------------------- ROLE SELECTION DROPDOWN --------------------
class RoleSelectionView(discord.ui.View):
    """📌 View containing dropdown for selecting roles + confirm button."""
    def __init__(self, role_type: str, remove: bool, guild: discord.Guild):
        super().__init__(timeout=60)
        self.role_type = role_type
        self.remove = remove
        self.add_item(RoleDropdown(role_type, remove, guild))
        self.add_item(ConfirmButton(role_type, remove))

class RoleDropdown(discord.ui.Select):
    """📌 Dropdown to select multiple roles for allowlist or blacklist management."""
    def __init__(self, role_type: str, remove: bool, guild: discord.Guild):
        self.role_type = role_type
        self.remove = remove

        data = settings_collection.find_one({"_id": "command_access"}) or {}
        allowlist_roles = set(data.get("allowlist", []))
        blacklist_roles = set(data.get("blacklist", []))

        # Get valid roles based on type
        if remove:
            options = [
                discord.SelectOption(label=guild.get_role(int(role)).name, value=str(role))
                for role in (allowlist_roles if role_type == "allowlist" else blacklist_roles)
                if guild.get_role(int(role))
            ]
        else:
            options = [
                discord.SelectOption(label=role.name, value=str(role.id))
                for role in guild.roles
                if str(role.id) not in (blacklist_roles if role_type == "allowlist" else allowlist_roles)  # Prevent conflicts
            ]

        super().__init__(placeholder=f"Select roles to {'remove' if remove else 'add'}", options=options, min_values=1, max_values=len(options))

class ConfirmButton(discord.ui.Button):
    """📌 Button to confirm role selection and update the database."""
    def __init__(self, role_type: str, remove: bool):
        super().__init__(label="✅ Confirm", style=discord.ButtonStyle.green)
        self.role_type = role_type
        self.remove = remove

    async def callback(self, interaction: discord.Interaction):
        """📌 Updates the allowlist or blacklist roles based on selection."""
        selected_roles = [int(role) for role in interaction.data['values']]
        data = settings_collection.find_one({"_id": "command_access"}) or {}
        roles = set(data.get(self.role_type, []))

        if self.remove:
            roles -= set(selected_roles)
        else:
            roles |= set(selected_roles)

        settings_collection.update_one({"_id": "command_access"}, {"$set": {self.role_type: list(roles)}}, upsert=True)
        
        embed = CommandAccessView.get_embed()
        await interaction.response.edit_message(embed=embed, view=CommandAccessView())

# -------------------- COMMANDS --------------------
class General(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setting", description="Access bot settings (Highest & 2nd Highest Role Only)")
    async def setting(self, interaction: discord.Interaction):
        """
        📌 The /setting command displays settings UI but restricts access to the top 2 roles.
        """
        highest_roles = sorted(interaction.guild.roles, key=lambda r: r.position, reverse=True)[:2]
        
        if not any(role in interaction.user.roles for role in highest_roles):
            return await interaction.response.send_message("❌ Only the top two highest roles can access settings!", ephemeral=True)
        
        await interaction.response.send_message("⚙️ **Bot Settings:**", view=SettingsView(), ephemeral=True)

# 📌 Setup function to add this Cog to the bot.
async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
