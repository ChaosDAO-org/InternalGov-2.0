import discord
from discord.ext import tasks
from discord import app_commands
from discord.ui import Button, View

class ButtonHandler(View):
    def __init__(self, bot_instance, message_id):
        super().__init__(timeout=10.0)
        self.bot_instance = bot_instance
        self.message_id = message_id
        self.add_item(Button(label="AYE", custom_id="aye_button", style=discord.ButtonStyle.green))
        self.add_item(Button(label="NAY", custom_id="nay_button", style=discord.ButtonStyle.red))
        self.add_item(Button(label="RECUSE", custom_id="recuse_button", style=discord.ButtonStyle.primary))

    async def on_aye_button(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def on_nay_button(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def on_recuse_button(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
    def set_buttons_lock_status(self, lock_status: bool):
        for item in self.children:
            if isinstance(item, Button):
                item.disabled = lock_status

