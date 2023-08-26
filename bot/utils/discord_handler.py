import discord
from discord.ext import commands

class DiscordHandler:
    def __init__(self, config):
        intents = discord.Intents.default()
        intents.guilds = True
        self.client = discord.Client(intents=intents)
        self.guild = discord.Object(id=config.DISCORD_SERVER_ID)
        self.discord_role = config.DISCORD_ROLE
        self.config = config
        
    def setup_events(self):
        @self.client.event
        async def on_ready():
            print(f"Logged in as {self.client.user} (ID: {self.client.user.id})")
            print("Connected to the following servers:")
            for server in self.client.guilds:
                print(f"- {server.name} (ID: {server.id})")

            if not check_governance.is_running():
                check_governance.start()

            if not recheck_proposals.is_running():
                recheck_proposals.start()
        
        @self.client.event
        async def on_interaction(interaction):
            await governance_monitor.on_interaction(interaction)

    def get_guild(self):
        return self.client.get_guild(self.config.DISCORD_SERVER_ID)

    def get_discord_role(self):
        return self.config.DISCORD_ROLE