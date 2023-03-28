import yaml
import discord
import asyncio
import logging
import argparse
from logging.handlers import TimedRotatingFileHandler
from discord.ext import tasks
from discord import app_commands
from gov2 import OpenGovernance2

with open("config.yaml", "r") as file:
    config = yaml.safe_load(file)

discord_api_key = config['discord_api_key']
discord_server_id = int(config['discord_server_id'])
discord_forum_channel_id = int(config['discord_forum_channel_id'])

guild = discord.Object(id=discord_server_id)  # replace with your guild id
intents = discord.Intents.default()
intents.guilds = True


def parse_arguments():
    parser = argparse.ArgumentParser(description='Governance Monitor Bot')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
    args = parser.parse_args()
    return args


args = parse_arguments()


def setup_logging(verbose=False):
    log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    log_handler = TimedRotatingFileHandler('governance_bot.log', when='D', interval=30, backupCount=12)
    log_handler.setFormatter(log_formatter)

    logger = logging.getLogger()
    if verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    logger.addHandler(log_handler)


setup_logging(args.verbose)


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


client = GovernanceMonitor(intents=intents)


@tasks.loop(hours=6)
async def check_governance():
    """A function that checks for new referendums on OpenGovernance2, creates a thread for each new
    referendum on a Discord channel with a specified ID, and adds reactions to the thread.

    This function uses the Discord API to interact with the Discord platform. The Discord API provides
    methods for creating a thread and adding reactions to it, as well as accessing information about
    channels and tags.

    The `check_referendums` function from the `OpenGovernance2` class is called to get the new
    referendums. The code then iterates through each new referendum and performs the following actions:

        1. Gets the available tags for the Discord channel.

        2. Creates a new tag for the origin of the referendum if it doesn't already exist.

        3. Creates a new thread for the referendum on the Discord channel, with the title and content
        of the referendum, and the newly created or existing tag.

        4. Adds reactions to the thread to allow users to vote on the referendum.

    The loop is set to run every 30 minutes, so the bot will continuously check for new referendums
    and create threads for them on the Discord channel.
    """
    try:
        new_referendums = OpenGovernance2().check_referendums()

        if new_referendums:
            channel = client.get_channel(discord_forum_channel_id)

            # go through each referendum if more than 1 was submitted in the given scheduled time
            for index, values in new_referendums.items():
                try:
                    available_channel_tags = [tag for tag in channel.available_tags]
                    governance_origin = [v for i, v in values['onchain']['origin'].items()]

                    # Create forum tags if they don't already exist.
                    governance_tag = next((tag for tag in available_channel_tags if tag.name == governance_origin[0]), None)
                    if governance_tag is None:
                        governance_tag = await channel.create_tag(name=governance_origin[0])

                    # Create a new thread on Discord
                    thread = await channel.create_thread(
                        name=f"{index}# {values['title'][:200].strip()}",
                        content=f"{values['content'][:1900].strip()}...\n\n<https://kusama.polkassembly.io/referenda/{index}>",
                        applied_tags=[governance_tag]
                    )

                    await thread.message.add_reaction('👍')
                    await thread.message.add_reaction('⚪')
                    await thread.message.add_reaction('👎')
                    await asyncio.sleep(5)

                except discord.errors.Forbidden as forbidden:
                    logging.exception(f"Forbidden error occurred:  {forbidden}")
                    raise forbidden
                except discord.errors.HTTPException as http:
                    logging.exception(f"HTTP exception occurred: {http}")
                    raise http
                except Exception as error:
                    logging.exception(f"An unexpected error occurred: {error}")
                    raise error
    except Exception as error:
        logging.exception(f"An unexpected error occurred: {error}")
        raise error


@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    check_governance.start()
    print('------')


client.run(discord_api_key)
