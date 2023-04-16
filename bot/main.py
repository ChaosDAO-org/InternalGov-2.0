import yaml
import json
import time

import argparse
import logging
from logging.handlers import TimedRotatingFileHandler

import asyncio
import discord
import requests
from discord.ext import tasks
from discord import app_commands
from discord.ui import Button, View

from utils.gov2 import OpenGovernance2

with open("../config.yaml", "r") as file:
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

    log_handler = TimedRotatingFileHandler('../data/logs/governance_bot.log', when='D', interval=30, backupCount=12)
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
        super().__init__(timeout=10.0)
        self.bot_instance = bot_instance
        self.message_id = message_id
        self.results_message_id = results_message_id
        self.add_item(Button(label="AYE", custom_id="aye_button", style=discord.ButtonStyle.green))
        self.add_item(Button(label="ABSTAIN", custom_id="abstain_button", style=discord.ButtonStyle.grey))
        self.add_item(Button(label="NAY", custom_id="nay_button", style=discord.ButtonStyle.red))

    async def on_aye_button(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def on_abstain_button(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def on_nay_button(self, interaction: discord.Interaction):
        await interaction.response.defer()


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

    @staticmethod
    def calculate_vote_result(aye_votes: int, nay_votes: int, abstain_votes: int, threshold: float = 0.66) -> str:
        total_votes = aye_votes + nay_votes + abstain_votes
        aye_percentage = aye_votes / total_votes
        nay_percentage = nay_votes / total_votes
        abstain_percentage = abstain_votes / total_votes

        if aye_percentage >= threshold:
            return "The vote is currently successful with {:.2%} **AYE**".format(aye_percentage)
        elif nay_percentage >= threshold:
            return "The vote is currently unsuccessful with {:.2%} **NAY**".format(nay_percentage)
        else:
            return "The vote is currently inconclusive with {:.2%} **AYE**, {:.2%} **NAY** & {:.2%} **ABSTAIN**".format(
                aye_percentage, nay_percentage, abstain_percentage)

    @staticmethod
    def get_asset_price(asset_id, currencies='usd,gbp,eur'):
        """
        Fetches the price of an asset in the specified currencies from the CoinGecko API.

        Args:
            asset_id (str): The ID of the asset for which to fetch the price (e.g., "bitcoin").
            currencies (str, optional): A comma-separated string of currency symbols
                                         (default is 'usd,gbp,eur').

        Returns:
            dict: A dictionary containing the prices in the specified currencies, or None
                  if an error occurred or the asset ID was not found.
        """
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={asset_id}&vs_currencies={currencies}"

        try:
            response = requests.get(url)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            print(f"An HTTP error occurred: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"A request error occurred: {e}")
            return None

        data = response.json()

        if asset_id not in data:
            print(f"Asset ID '{asset_id}' not found in CoinGecko.")
            return None

        return data[asset_id]

    @staticmethod
    def load_vote_counts():
        try:
            with open("../data/vote_counts.json", "r") as file:
                return json.load(file)
        except FileNotFoundError:
            return {}

    def save_vote_counts(self):
        with open("../data/vote_counts.json", "w") as file:
            json.dump(self.vote_counts, file, indent=4)

    async def on_interaction(self, interaction: discord.Interaction):

        if interaction.data and interaction.data.get("component_type") == 2:
            custom_id = interaction.data.get("custom_id")

            user_id = interaction.user.id
            username = interaction.user.name + '#' + interaction.user.discriminator

            logging.info(f"User interaction from {username}")

            member = await interaction.guild.fetch_member(user_id)
            roles = member.roles

            if discord_role and not any(role.name == discord_role for role in roles):
                logging.warning(f"{username} doesn't have the necessary role assigned to participate:: {discord_role}")
                await interaction.response.send_message(
                    f"To participate, please ensure that you have the necessary role assigned: {discord_role}. This is a prerequisite for engaging in this activity.",
                    ephemeral=True)
                await asyncio.sleep(5)
                await interaction.delete_original_response()
                return

            message_id = str(interaction.message.id)
            discord_thread = interaction.message.channel

            current_time = time.time()
            cooldown_time = button_cooldowns.get(user_id, 0) + 15

            if custom_id in ["aye_button", "nay_button", "abstain_button"] and current_time >= cooldown_time:
                button_cooldowns[user_id] = current_time
                vote_type = "aye" if custom_id == "aye_button" else "abstain" if custom_id == "abstain_button" else "nay"

                if message_id not in list(self.vote_counts.keys()):
                    self.vote_counts[message_id] = {
                        "index": 'Proposal detected; corresponding vote_count.json entry absent, now added using first vote interaction.',
                        "title": discord_thread.name,
                        "aye": 0,
                        "abstain": 0,
                        "nay": 0,
                        "users": {},
                        "epoch": int(time.time())}

                # Check if the user has already voted
                if str(user_id) in self.vote_counts[message_id]["users"]:
                    previous_vote = self.vote_counts[message_id]["users"][str(user_id)]["vote_type"]

                    # If the user has voted for the same option, ignore the vote
                    if previous_vote == vote_type:
                        await interaction.response.send_message(
                            "Your vote for this option has already been recorded. If you wish to change your decision, please feel free to choose an alternative option.",
                            ephemeral=True)
                        await asyncio.sleep(5)
                        await interaction.delete_original_response()
                        return
                    else:
                        # Remove the previous vote
                        self.vote_counts[message_id][previous_vote] -= 1

                # Update the vote count and save the user's vote
                self.vote_counts[message_id][vote_type] += 1
                self.vote_counts[message_id]["users"][str(user_id)] = {"username": username,
                                                                       "vote_type": vote_type}
                self.save_vote_counts()

                # Update the results message
                thread = await self.fetch_channel(interaction.channel_id)
                async for message in thread.history(oldest_first=True):
                    if message.author == self.user and message.content.startswith("👍 AYE:"):
                        results_message = message
                        break
                else:
                    results_message = await thread.send("👍 AYE: 0    |    ⚪ ABSTAIN: 0    |    👎 NAY: 0")

                new_results_message = f"👍 AYE: {self.vote_counts[message_id]['aye']}    |    ⚪ ABSTAIN: {self.vote_counts[message_id]['abstain']}    |    👎 NAY: {self.vote_counts[message_id]['nay']}\n" \
                                      f"{self.calculate_vote_result(aye_votes=self.vote_counts[message_id]['aye'], abstain_votes=self.vote_counts[message_id]['abstain'], nay_votes=self.vote_counts[message_id]['nay'])}"
                await results_message.edit(content=new_results_message)

                # Acknowledge the vote and delete the message 10 seconds later
                # (this notification is only visible to the user that interacts with AYE, NAY & ABSTAIN
                await interaction.response.send_message(
                    f"Your vote of **{vote_type}** has been successfully registered. We appreciate your valuable input in this decision-making process.",
                    ephemeral=True)
                await asyncio.sleep(10)
                await interaction.delete_original_response()
            else:
                # block the user from pressing the AYE, NAY & ABSTAIN to prevent unnecessary spam
                remaining_time = cooldown_time - current_time
                seconds = int(remaining_time)

                await interaction.response.send_message(f"A {seconds}-second waiting period is required before you may cast your vote again. We appreciate your patience and understanding.", ephemeral=True)
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
        logging.info("Checking for new proposals")
        opengov2 = OpenGovernance2()
        new_referendums = opengov2.check_referendums()

        if new_referendums:
            logging.info(f"{len(new_referendums)} new proposal(s) found")
            channel = client.get_channel(discord_forum_channel_id)
            current_price = client.get_asset_price(asset_id=config['network'])

            # go through each referendum if more than 1 was submitted in the given scheduled time
            for index, values in new_referendums.items():
                requested_spend = ""
                try:
                    proposal_ends = opengov2.time_until_block(target_block=values['onchain']['alarm'][0])

                    available_channel_tags = [tag for tag in channel.available_tags]
                    governance_origin = [v for i, v in values['onchain']['origin'].items()]

                    # Create forum tags if they don't already exist.
                    governance_tag = next((tag for tag in available_channel_tags if tag.name == governance_origin[0]), None)
                    if governance_tag is None:
                        governance_tag = await channel.create_tag(name=governance_origin[0])

                    #  Written to accommodate differences in returned JSON between Polkassembly & Subsquare
                    if values['successful_url']:
                        logging.info(f"Getting on-chain data from: {values['successful_url']}")

                        if 'polkassembly' in values['successful_url'] and 'proposed_call' in list(values.keys()):
                            if values['proposed_call']['method'] == 'spend':
                                amount = int(values['proposed_call']['args']['amount']) / 1e12
                                requested_spend = f"```yaml\n" \
                                                  f"This proposal seeks approval for the allocation of {amount} KSM\n\n" \
                                                  f"USD: ${format(amount * current_price['usd'], ',.2f')}```\n"

                        elif 'subsquare' in values['successful_url'] and 'proposal' in list(values['onchainData'].keys()):
                            if values['onchainData']['proposal'] is not None and values['onchainData']['proposal']['call']['method'] == 'spend':
                                amount = int(values['onchainData']['proposal']['call']['args'][0]['value']) / 1e12
                                requested_spend = f"```yaml\n" \
                                                  f"This proposal seeks approval for the allocation of {amount} KSM\n\n" \
                                                  f"USD: ${format(amount * current_price['usd'], ',.2f')}```\n"
                        else:
                            logging.error(f"Unable to pull information from data sources")
                            requested_spend = ""
                    else:
                        logging.error(f"Unable to pull information from data sources")
                        requested_spend = ""

                    title = values['title'][:95].strip()
                    content = values['content'][:1700].strip()
                    logging.info(f"Creating thread on Discord: {title}")

                    # Create a new thread on Discord
                    thread = await channel.create_thread(
                        name=f"{index}# {title}",
                        content=f"{requested_spend}{content}{'...**Character limit exceeded. For further details, please refer to the links below.**' if len(content) > 1700 else ''}\n\n"
                                f"**External links**"
                                f"\n<https://kusama.polkassembly.io/referenda/{index}>"
                                f"\n<https://kusama.subsquare.io/referenda/referendum/{index}>"
                                f"\n<https://kusama.subscan.io/referenda_v2/{index}>",
                        reason='Created by an incoming proposal on the Kusama network',
                        applied_tags=[governance_tag]
                    )

                    logging.info(f"Thread created: {thread.message.id}")

                    # Send an initial results message in the thread
                    initial_results_message = "👍 AYE: 0    |    ⚪ ABSTAIN: 0    |    👎 NAY: 0"

                    channel_thread = channel.get_thread(thread.message.id)
                    client.vote_counts[str(thread.message.id)] = {"index": index,
                                                                  "title": values['title'][:200].strip(),
                                                                  "aye": 0,
                                                                  "abstain": 0,
                                                                  "nay": 0,
                                                                  "users": {},
                                                                  "epoch": int(time.time())}
                    client.save_vote_counts()

                    results_message = await channel_thread.send(content=initial_results_message)
                    results_message_id = results_message.id

                    message_id = thread.message.id
                    view = InternalGov(client, message_id, results_message_id)  # Pass the results_message_id
                    logging.info(f"Vote results message added: {message_id}")
                    await thread.message.edit(view=view)  # Update the thread message with the new view
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
        else:
            logging.info("0 proposals found since last checking")
    except Exception as error:
        logging.exception(f"An unexpected error occurred: {error}")
        raise error


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("Connected to the following servers:")
    for server in client.guilds:
        print(f"- {server.name} (ID: {server.id})")

    check_governance.start()


if __name__ == '__main__':
    client.run(discord_api_key)
