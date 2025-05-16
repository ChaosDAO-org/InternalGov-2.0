import discord
from discord.ext import tasks
from discord import app_commands, PartialEmoji
from discord.ui import Button, View


class ButtonHandler(View):
    def __init__(self, bot_instance, message_id):
        super().__init__(timeout=15.0)
        self.bot_instance = bot_instance
        self.message_id = message_id
        self.add_item(Button(label="AYE", custom_id="aye_button", style=discord.ButtonStyle.green, emoji="👍"))
        self.add_item(Button(label="NAY", custom_id="nay_button", style=discord.ButtonStyle.red, emoji="👎"))
        self.add_item(Button(label="RECUSE", custom_id="recuse_button", style=discord.ButtonStyle.primary, emoji="\u26d4"))

    async def set_buttons_lock_status(self, lock_status: bool):
        for item in self.children:
            if isinstance(item, Button):
                item.disabled = lock_status


class ExternalLinkButton(View):
    def __init__(self, index, network_name):
        super().__init__(timeout=5.0)  # Initialize the parent class
        self.index = index
        self.network_name = network_name
        # External link buttons on row 1
        self.add_item(Button(label="Subsquare", style=discord.ButtonStyle.url, url=f"https://{self.network_name}.subsquare.io/referenda/referendum/{self.index}"))
        
        # Only add Polkassembly button if the network is not Hydration
        if self.network_name.lower() != "hydration":
            self.add_item(Button(label="Polkassembly", style=discord.ButtonStyle.url, url=f"https://{self.network_name}.polkassembly.io/referenda/{self.index}"))
            
        self.add_item(Button(label="Subscan", style=discord.ButtonStyle.url, url=f"https://{self.network_name}.subscan.io/referenda_v2/{self.index}"))
