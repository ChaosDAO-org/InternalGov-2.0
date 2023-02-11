import yaml
import discord
from typing import Optional
from discord.ext import tasks
from discord import app_commands

with open("config.yaml", "r") as file:
    config = yaml.safe_load(file)

discord_api_key = config['discord_api_key']
discord_server_id = int(config['discord_server_id'])
discord_forum_channel_id = int(config['discord_forum_channel_id'])

guild = discord.Object(id=discord_server_id)  # replace with your guild id


class GovernanceMonitor(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        # A CommandTree is a special type that holds all the application command
        # state required to make it work. This is a separate class because it
        # allows all the extra state to be opt-in.
        # Whenever you want to work with application commands, your tree is used
        # to store and work with them.
        # Note: When using commands.Bot instead of discord.Client, the bot will
        # maintain its own tree instead.
        self.tree = app_commands.CommandTree(self)

    # In this basic example, we just synchronize the app commands to one guild.
    # Instead of specifying a guild to every command, we copy over our global commands instead.
    # By doing so, we don't have to wait up to an hour until they are shown to the end-user.
    async def setup_hook(self):
        # This copies the global commands over to your guild.
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)


intents = discord.Intents.default()
client = GovernanceMonitor(intents=intents)


@tasks.loop(seconds=20.0)
async def check_governance():
    # https://discordpy.readthedocs.io/en/stable/api.html?highlight=textchannel#discord.Thread

    # Logic for checking new referendas

    # Only run create_thread if a new referenda is found
    channel = client.get_channel(discord_forum_channel_id)
    thread = await channel.create_thread(
        name="<referenda-title>",
        content="<referenda-content>"
    )

    await thread.message.add_reaction('👍')
    await thread.message.add_reaction('⚪')
    await thread.message.add_reaction('👎')


@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    check_governance.start()
    print('------')


client.run(discord_api_key)
