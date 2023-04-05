import yaml
import json
import time

import argparse
import logging
from logging.handlers import TimedRotatingFileHandler

import asyncio
import discord
from discord.ext import tasks
from discord import app_commands
from discord.ui import Button, View

from gov2 import OpenGovernance2

with open("config.yaml", "r") as file:
    config = yaml.safe_load(file)

discord_api_key = config['discord_api_key']
discord_server_id = int(config['discord_server_id'])
discord_forum_channel_id = int(config['discord_forum_channel_id'])
discord_role = config['discord_role']

guild = discord.Object(id=discord_server_id)
intents = discord.Intents.default()
intents.guilds = True
button_cooldowns = {}


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


class InternalGov(View):
    def __init__(self, bot_instance, message_id, results_message_id):
        super().__init__(timeout=60.0)
        self.bot_instance = bot_instance
        self.message_id = message_id
        self.results_message_id = results_message_id
        self.add_item(Button(label="AYE", custom_id="aye_button", style=discord.ButtonStyle.green))
        self.add_item(Button(label="ABSTAIN", custom_id="abstain_button", style=discord.ButtonStyle.grey))
        self.add_item(Button(label="NAY", custom_id="nay_button", style=discord.ButtonStyle.red))

    async def on_timeout(self):
        channel = await self.bot_instance.fetch_channel(discord_forum_channel_id)
        message = await channel.fetch_message(self.message_id)

        # Generate the voting results message and edit the original message with it
        results_message = self.generate_results_message()
        await message.edit(content=results_message)

    async def on_aye_button(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def on_abstain_button(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def on_nay_button(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def update_vote_count(self, interaction: discord.Interaction, vote_type: str):
        if self.message_id not in self.bot_instance.vote_counts:
            self.bot_instance.vote_counts[self.message_id] = {"👍": 0, "⚪": 0, "👎": 0}

        self.bot_instance.vote_counts[self.message_id][vote_type] += 1
        self.bot_instance.save_vote_counts()

        # Edit the initial results message with the updated vote counts
        channel = await self.bot_instance.fetch_channel(discord_forum_channel_id)
        results_message = await channel.fetch_message(self.results_message_id)
        new_results_message = self.generate_results_message()
        await results_message.edit(content=new_results_message)

    def generate_results_message(self):
        counts = self.bot_instance.vote_counts.get(self.message_id, {"👍": 0, "⚪": 0, "👎": 0})
        return f"AYE: {counts['👍']}\nABSTAIN: {counts['⚪']}\nNAY: {counts['👎']}"


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
        self.vote_counts = self.load_vote_counts()
        self.user_votes = {}

    @staticmethod
    def calculate_vote_result(aye_votes: int, nay_votes: int, abstain_votes: int, threshold: float = 0.66) -> str:
        total_votes = aye_votes + nay_votes + abstain_votes
        aye_percentage = aye_votes / total_votes
        nay_percentage = nay_votes / total_votes
        abstain_percentage = abstain_votes / total_votes

        if aye_percentage >= threshold:
            return "The vote is successful with {:.2%} **AYE**".format(aye_percentage)
        elif nay_percentage >= threshold:
            return "The vote is unsuccessful with {:.2%} **NAY**".format(nay_percentage)
        else:
            return "The vote is inconclusive with {:.2%} **AYE**, {:.2%} **NAY** & {:.2%} **ABSTAIN**".format(aye_percentage, nay_percentage, abstain_percentage)

    @staticmethod
    def load_vote_counts():
        try:
            with open("./data/vote_counts.json", "r") as file:
                return json.load(file)
        except FileNotFoundError:
            return {}

    def save_vote_counts(self):
        with open("./data/vote_counts.json", "w") as file:
            json.dump(self.vote_counts, file, indent=4)

    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.data and interaction.data.get("component_type") == 2:
            custom_id = interaction.data.get("custom_id")
            user_id = interaction.user.id
            member = await interaction.guild.fetch_member(user_id)
            roles = member.roles

            if discord_role and not any(role.name == discord_role for role in roles):
                await interaction.response.send_message(f"You don't have the appropriate role set to participate. Required role: {discord_role}", ephemeral=True)
                await asyncio.sleep(5)
                await interaction.delete_original_response()
                return

            message_id = str(interaction.message.id)

            current_time = time.time()
            cooldown_time = button_cooldowns.get(user_id, 0) + 30

            if custom_id in ["aye_button", "nay_button", "abstain_button"] and current_time >= cooldown_time:
                button_cooldowns[user_id] = current_time
                vote_type = "👍" if custom_id == "aye_button" else "⚪" if custom_id == "abstain_button" else "👎"

                if message_id not in self.vote_counts:
                    self.vote_counts[message_id] = {"👍": 0, "⚪": 0, "👎": 0, "users": {}, "epoch": int(time.time())}

                # Check if the user has already voted
                if str(user_id) in self.vote_counts[message_id]["users"]:
                    previous_vote = self.vote_counts[message_id]["users"][str(user_id)]

                    # If the user has voted for the same option, ignore the vote
                    if previous_vote == vote_type:
                        await interaction.response.send_message("You have already voted for this option.", ephemeral=True)
                        await asyncio.sleep(5)
                        await interaction.delete_original_response()
                        return
                    else:
                        # Remove the previous vote
                        self.vote_counts[message_id][previous_vote] -= 1

                # Update the vote count and save the user's vote
                self.vote_counts[message_id][vote_type] += 1
                self.vote_counts[message_id]["users"][str(user_id)] = vote_type
                self.save_vote_counts()

                # Update the results message
                thread = await self.fetch_channel(interaction.channel_id)
                async for message in thread.history(oldest_first=True):
                    if message.author == self.user and message.content.startswith("👍 AYE:"):
                        results_message = message
                        break
                else:
                    results_message = await thread.send("👍 AYE: 0    |    ⚪ ABSTAIN: 0    |    👎 NAY: 0")

                new_results_message = f"👍 AYE: {self.vote_counts[message_id]['👍']}    |    ⚪ ABSTAIN: {self.vote_counts[message_id]['⚪']}    |    👎 NAY: {self.vote_counts[message_id]['👎']}\n" \
                                      f"{self.calculate_vote_result(aye_votes=self.vote_counts[message_id]['👍'], abstain_votes=self.vote_counts[message_id]['⚪'], nay_votes=self.vote_counts[message_id]['👎'])}"
                await results_message.edit(content=new_results_message)

                # Acknowledge the vote and delete the message 10 seconds later
                # (this notification is only visible to the user that interacts with AYE, NAY & ABSTAIN
                await interaction.response.send_message("Vote casted!", ephemeral=True)
                await asyncio.sleep(10)
                await interaction.delete_original_response()
            else:
                # block the user from pressing the AYE, NAY & ABSTAIN to prevent unnecessary spam
                remaining_time = cooldown_time - current_time
                seconds = int(remaining_time)

                await interaction.response.send_message(f"You need to wait {seconds} seconds before casting your vote again!", ephemeral=True)
                await asyncio.sleep(5)
                await interaction.delete_original_response()

    # Synchronize the app commands to one guild.
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

    The loop is set to run every 6 hrs, so the bot will continuously check for new referendums
    and create threads for them on the Discord channel.
    """
    try:
        opengov2 = OpenGovernance2()
        new_referendums = opengov2.check_referendums()

        if new_referendums:
            channel = client.get_channel(discord_forum_channel_id)

            # go through each referendum if more than 1 was submitted in the given scheduled time
            for index, values in new_referendums.items():
                try:
                    proposal_ends = opengov2.time_until_block(target_block=values['onchain']['alarm'][0])

                    available_channel_tags = [tag for tag in channel.available_tags]
                    governance_origin = [v for i, v in values['onchain']['origin'].items()]

                    # Create forum tags if they don't already exist.
                    governance_tag = next((tag for tag in available_channel_tags if tag.name == governance_origin[0]), None)
                    if governance_tag is None:
                        governance_tag = await channel.create_tag(name=governance_origin[0])

                    # Create a new thread on Discord
                    thread = await channel.create_thread(
                        name=f"{index}# {values['title'][:200].strip()}",
                        content=f"{values['content'][:1700].strip()}{'...**Character limit exceeded. For further details, please refer to the links below.**' if len(values['content']) > 1700 else ''}\n\n"
                                f"**External links**"
                                f"\n<https://kusama.polkassembly.io/referenda/{index}>"
                                f"\n<https://kusama.subsquare.io/referenda/referendum/{index}>"
                                f"\n<https://kusama.subscan.io/referenda_v2/{index}>",
                        reason='Created by an incoming proposal on the Kusama network',
                        applied_tags=[governance_tag]
                    )

                    # Send an initial results message in the thread
                    initial_results_message = "👍 AYE: 0    |    ⚪ ABSTAIN: 0    |    👎 NAY: 0"

                    channel_thread = channel.get_thread(thread.message.id)
                    results_message = await channel_thread.send(content=initial_results_message)
                    results_message_id = results_message.id

                    message_id = thread.message.id
                    view = InternalGov(client, message_id, results_message_id)  # Pass the results_message_id
                    await thread.message.edit(view=view)                        # Update the thread message with the new view
#
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
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("Connected to the following servers:")
    for guild in client.guilds:
        print(f"- {guild.name} (ID: {guild.id})")

    check_governance.start()


if __name__ == '__main__':
    client.run(discord_api_key)
