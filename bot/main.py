import yaml
import json
import time
import requests
import argparse
import logging
from logging.handlers import TimedRotatingFileHandler

import asyncio
import discord
from discord.ext import tasks
from discord import app_commands
from discord.ui import Button, View

from utils.gov2 import OpenGovernance2
from utils.data_processing import CacheManager, Text

with open("../config.yaml", "r") as file:
    config = yaml.safe_load(file)

discord_api_key = config['discord_api_key']
discord_server_id = int(config['discord_server_id'])
discord_forum_channel_id = int(config['discord_forum_channel_id'])
discord_lock_thread = int(config['discord_lock_thread'])
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
    """
    Sets up logging configuration for the application.

    This function configures logging with a timed rotating file handler. The log file is rotated
    daily, and up to 12 backup log files are kept. Log messages are formatted to include a
    timestamp, the log level, and the log message.

    Parameters:
    verbose (bool, optional): If True, the log level is set to DEBUG, which means more detailed
                              log messages will be recorded. If False (the default), the log level
                              is set to INFO, meaning only higher-level log messages, like
                              informational messages, warnings, and errors, will be recorded.

    Example Usage:

    >>> setup_logging(verbose=True)  # Enable verbose logging
    >>> setup_logging()              # Enable standard logging

    """
    log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    log_handler = TimedRotatingFileHandler('../data/logs/governance_bot.log', when='D', interval=1, backupCount=12)
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
        self.add_item(Button(label="NAY", custom_id="nay_button", style=discord.ButtonStyle.red))
        self.add_item(Button(label="RECUSE", custom_id="recuse_button", style=discord.ButtonStyle.primary))

    async def on_aye_button(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def on_nay_button(self, interaction: discord.Interaction):
        await interaction.response.defer()

    async def on_recuse_button(self, interaction: discord.Interaction):
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
    def proposals_with_no_context(filename):
        """
        Extracts and returns items from a JSON file whose 'title' attribute is set to 'None'.

        This function reads a JSON file, iterates through its items, and filters out those items
        where the 'title' attribute is equal to the string 'None'. It stores these items in a dictionary
        with the same structure as the original data and returns this dictionary.

        Parameters:
        filename (str): The path to the input JSON file. The file is expected to contain a dictionary
                        where each value is another dictionary having at least a 'title' key.

        Returns:
        dict: A dictionary containing items from the input JSON file where the 'title' attribute is 'None'.
              The keys in the returned dictionary are the same as in the original data.

        Example:
        Consider the input file ('data.json') has the following content:
        {
            "proposal1": {"title": "None", "description": "This is a test"},
            "proposal2": {"title": "Example", "description": "This is another test"},
            "proposal3": {"title": "None", "description": "This is a final test"}
        }

        Calling the function as `proposals_with_no_context('data.json')` will return:
        {
            "proposal1": {"title": "None", "description": "This is a test"},
            "proposal3": {"title": "None", "description": "This is a final test"}
        }
        """
        with open(filename, 'r') as f:
            data = json.load(f)

        items_with_title_none = {}

        for key, value in data.items():
            if value['title'] == 'None':
                items_with_title_none[key] = value

        return items_with_title_none

    @staticmethod
    def calculate_vote_result(aye_votes: int, nay_votes: int, threshold: float = 0.66) -> str:
        """
        Calculate and return the result of a vote based on the numbers of 'aye', 'nay' votes,
        and a specified threshold.

        This function takes in the number of 'aye', 'nay' votes, and calculates the percentages
        of each. It then compares the percentage of 'aye' votes to a specified threshold to determine if the
        vote is successful. If the 'aye' percentage is below the threshold, it checks if the 'nay' percentage
        meets the threshold to determine if the vote is unsuccessful. If neither 'aye' nor 'nay' meets the threshold,
        the function returns that the vote is inconclusive.

        Parameters:
        aye_votes (int): The number of 'aye' votes. Must be non-negative.
        nay_votes (int): The number of 'nay' votes. Must be non-negative.
        threshold (float, optional): The percentage threshold required for the vote to be successful. Defaults to 0.66.
                                    Must be between 0 and 1.

        Returns:
        str: A string describing the result of the vote. The string contains the status of the vote (successful,
             unsuccessful, or inconclusive) and the percentages of 'aye', 'nay' votes.

        Example:

        >>> calculate_vote_result(70, 30)
        >>>'The vote is currently successful with 70.00% **AYE**'

        """
        total_votes = aye_votes + nay_votes

        # Handle the edge case where total_votes is zero
        if total_votes == 0:
            return "No on-chain votes have been casted."

        aye_percentage = aye_votes / total_votes
        nay_percentage = nay_votes / total_votes

        if aye_percentage >= threshold:
            return "The vote is currently successful with {:.2%} **AYE**".format(aye_percentage)
        elif nay_percentage >= threshold:
            return "The vote is currently unsuccessful with {:.2%} **NAY**".format(nay_percentage)
        else:
            return "The vote is currently inconclusive with {:.2%} **AYE**, {:.2%} **NAY**".format(
                aye_percentage, nay_percentage)

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

    @staticmethod
    async def lock_threads_by_message_ids(guild_id, message_ids):
        """
        Locks Discord threads by their associated message IDs in a given guild (server).

        This asynchronous function locks specified threads in a Discord guild. The threads are identified
        by their associated message IDs. The function checks if the bot has the necessary permissions to lock
        threads and logs error messages if it lacks permissions or if an invalid thread ID is provided.

        Parameters:
        guild_id (int or str): The ID of the Discord guild (server) where the threads are located.
        message_ids (list or int or str): A single message ID or a list of message IDs corresponding to
                                          the threads to be locked. Each message ID should be an integer
                                          or a string that can be cast to an integer.

        Returns:
        None

        Note:

        - This function requires that a Discord client object named 'client' exists and is logged in.
        - The bot needs the 'Manage Threads' permission in the guild to be able to lock threads.
        - The function is asynchronous and must be called from within an async function or an event loop.
        - If the bot does not have the required permissions, or if an invalid message ID is passed,
          error messages are logged but the function does not raise an exception.

        Example usage:

        >>> await lock_threads_by_message_ids(123456789012345678, [111111111111111111, 222222222222222222])

        or

        >>> await lock_threads_by_message_ids(123456789012345678, 111111111111111111)
        """
        if not isinstance(message_ids, list):
            message_ids = [message_ids]

        server = client.get_guild(guild_id)

        # Check if the bot has the required permissions
        bot_member = server.get_member(client.user.id)
        if not bot_member.guild_permissions.manage_threads:
            logging.error("The bot lacks the necessary permissions to lock threads. Please update the permissions.")
            return

        for message_id in message_ids:
            # Get the thread from the forum by the message ID
            thread = client.get_channel(int(message_id))

            if not thread:
                logging.error(f"Invalid Discord forum thread ID: {message_id}")
                continue

            # Lock the thread
            logging.info(f"Discord forum thread '{thread.name}' is >= {discord_lock_thread} days old, locking thread from future interactions.")
            await thread.edit(locked=True)

    async def edit_thread(self, forum_channel: int, message_id: int, name: str, content: str) -> bool:
        """
        Edits the title and the first post of a specific thread in a given forum channel on Discord.

        Parameters:
        forum_channel (int): The ID of the forum channel where the thread is located.
        message_id (int): The ID of the thread to be edited.
        name (str): The new title to assign to the thread.
        content (str): The new content to assign to the first post of the thread.

        Returns:
        bool: Returns True if the function executes successfully.
        """

        # Retrieve the specific thread within the forum channel
        thread = self.get_channel(forum_channel).get_thread(int(message_id))

        # Use asynchronous iteration to retrieve the first post of the thread (the bots post)
        async for message in thread.history(oldest_first=True, limit=1):
            # Update thread title
            await thread.edit(name=name, reason="Edited by hourly recheck job - (Rechecks proposals with no context to add context to existing posts)")

            # Update the content of the first post in the thread
            await message.edit(content=content)

        return True

    async def on_interaction(self, interaction: discord.Interaction):
        """
        Asynchronously handles interactions within a Discord guild.

        This method handles interactions from users and updates vote counts for a poll.
        It logs the interaction, checks for the user's roles, and ensures the user
        doesn't spam the voting buttons.

        Parameters:
        - interaction (discord.Interaction): The interaction object containing data
          about the user interaction in the Discord guild.

        Behavior:

        - Logs user interaction.
        - Fetches member and their roles from the guild.
        - Checks if the user has the necessary role to participate.
        - If the user doesn’t have the required role, sends a message informing them.
        - Handles vote counting for "aye", "nay" buttons.
        - Throttles the user's ability to vote within a 15-second interval to prevent spam.
        - Updates the vote counts and informs the user of a successful vote.

        Note:

        - Ensure that 'discord_role', 'button_cooldowns', and 'vote_counts' are
          defined globally or are accessible within the scope of this function.
        - Ensure that 'self.fetch_channel' and 'self.save_vote_counts' methods are
          defined in the class where this function is.
        - Ensure that 'self.calculate_vote_result' method is defined, it should take
          aye_votes, and nay_votes as parameters and return a string.
        """
        if interaction.data and interaction.data.get("component_type") == 2:
            custom_id = interaction.data.get("custom_id")

            if custom_id == 'abstain_button':
                await interaction.response.send_message(f"Choose Aye, Nay, or Recuse if there's a conflict of interest. Abstain has been removed", ephemeral=True)
                await asyncio.sleep(10)
                await interaction.delete_original_response()
                return

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

            if custom_id in ["aye_button", "nay_button", "recuse_button"] and current_time >= cooldown_time:
                self.vote_counts = self.load_vote_counts()  # tmp-workaround for reloading vote_counts to avoid memory caching
                button_cooldowns[user_id] = current_time
                vote_type = "aye" if custom_id == "aye_button" else "recuse" if custom_id == "recuse_button" else "nay"

                if message_id not in list(self.vote_counts.keys()):
                    self.vote_counts[message_id] = {
                        "index": 'Proposal detected; corresponding vote_count.json entry absent, now added using first vote interaction.',
                        "title": discord_thread.name,
                        "aye": 0,
                        "nay": 0,
                        "recuse": 0,
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
                        # await interaction.delete_original_response()
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
                    results_message = await thread.send("👍 AYE: 0    |    👎 NAY: 0    |    ☯ RECUSE: 0")

                new_results_message = f"👍 AYE: {self.vote_counts[message_id]['aye']}    |    👎 NAY: {self.vote_counts[message_id]['nay']}    |    ☯ RECUSE: {self.vote_counts[message_id]['recuse']}\n" \
                                      f"{self.calculate_vote_result(aye_votes=self.vote_counts[message_id]['aye'], nay_votes=self.vote_counts[message_id]['nay'])}"
                await results_message.edit(content=new_results_message)

                # Acknowledge the vote and delete the message 10 seconds later
                # (this notification is only visible to the user that interacts with AYE, NAY
                await interaction.response.send_message(
                    f"Your vote of **{vote_type}** has been successfully registered. We appreciate your valuable input in this decision-making process.",
                    ephemeral=True)
                await asyncio.sleep(60*60*24*14)
                # await interaction.delete_original_response()
            else:
                # block the user from pressing the AYE, NAY to prevent unnecessary spam
                remaining_time = cooldown_time - current_time
                seconds = int(remaining_time)

                await interaction.response.send_message(f"{seconds} second waiting period remaining before you may cast your vote again. We appreciate your patience and understanding.",
                                                        ephemeral=True)
                await asyncio.sleep(5)
                await interaction.delete_original_response()

    # Synchronize the app commands to one guild.
    async def setup_hook(self):
        # This copies the global commands over to your guild.
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)


client = GovernanceMonitor(intents=intents)


async def create_or_get_role(guild, role_name, client):
    # Check if the role already exists
    existing_role = discord.utils.get(guild.roles, name=role_name)

    if existing_role:
        return existing_role

    # If the role doesn't exist, try to create it
    try:
        # Create the role with the specified name
        new_role = await guild.create_role(name=role_name)
        return new_role
    except discord.Forbidden:
        logging.error(f"Permission error: Unable to create role {role_name} in guild {guild.id}")
        raise  # You can raise the exception or return None based on your use case
    except discord.HTTPException as e:
        logging.error(f"HTTP error while creating role {role_name} in guild {guild.id}: {e}")
        raise  # You can raise the exception or return None based on your use case

@tasks.loop(hours=6)
async def check_governance():
    """A function that checks for new referendums on OpenGovernance2, creates a thread for each new
    referendum on a Discord channel with a specified ID, and adds reactions to the thread.

    This function uses the Discord API to interact with the Discord platform. The Discord API provides
    methods for creating a thread and adding reactions to it, as well as accessing information about
    channels and tags.

    The `check_referendums` function from the `OpenGovernance2` class is called to get the new
    referendums. The code then iterates through each new referendum and performs the following actions:

        - Gets the available tags for the Discord channel.
        - Creates a new tag for the origin of the referendum if it doesn't already exist.
        - Creates a new thread for the referendum on the Discord channel, with the title and content
        of the referendum, and the newly created or existing tag.
        - Adds reactions to the thread to allow users to vote on the referendum.

    The loop is set to run every 6 hrs, so the bot will continuously check for new referendums
    and create threads for them on the Discord channel.
    """
    try:
        logging.info("Checking for new proposals")
        opengov2 = OpenGovernance2()
        new_referendums = await opengov2.check_referendums()

        # Move votes from vote_counts.json -> archived_votes.json once they exceed X amount of days
        # lock threads once archived (prevents regular users from continuing to vote).
        threads_to_lock = CacheManager().delete_old_keys_and_archive(json_file_path='../data/vote_counts.json', days=discord_lock_thread, archive_filename='../data/archived_votes.json')
        if threads_to_lock:
            logging.info(f"{len(threads_to_lock)} threads have been archived")
            await client.lock_threads_by_message_ids(guild_id=discord_server_id, message_ids=threads_to_lock)
            logging.info(f"The following threads have been locked: {threads_to_lock}")

        if new_referendums:
            logging.info(f"{len(new_referendums)} new proposal(s) found")
            channel = client.get_channel(discord_forum_channel_id)
            current_price = client.get_asset_price(asset_id=config['network'])
                    
            # Get the guild object where the role is located
            guild = client.get_guild(discord_server_id)  # Replace discord_guild_id with the actual guild ID

            # Construct the role name based on the symbol in config
            role_name = f"{config['symbol']}-GOV"

            # Find the role by its name
            role = discord.utils.get(guild.roles, name=role_name)

            # go through each referendum if more than 1 was submitted in the given scheduled time
            for index, values in new_referendums.items():
                requested_spend = ""
                try:
                    #proposal_ends = opengov2.time_until_block(target_block=values['onchain']['alarm'][0])
                    available_channel_tags = []
                    if channel is not None:
                        available_channel_tags = [tag for tag in channel.available_tags]
                    else:
                        logging.error(f"Channel with ID {discord_forum_channel_id} not found")
                        # Handle the error as appropriate for your application
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
                                amount = int(values['proposed_call']['args']['amount']) / float(config['token_decimal'])
                                requested_spend = f"```yaml\n" \
                                                  f"{config['symbol']}: {amount}\n" \
                                                  f"USD: ${format(amount * current_price['usd'], ',.2f')}```\n"

                        elif 'subsquare' in values['successful_url'] and 'proposal' in list(values['onchainData'].keys()):
                            if values['onchainData']['proposal'] is not None and values['onchainData']['proposal']['call']['method'] == 'spend':
                                amount = int(values['onchainData']['proposal']['call']['args'][0]['value']) / float(config['token_decimal'])
                                requested_spend = f"```yaml\n" \
                                                  f"{config['symbol']}: {amount}\n" \
                                                  f"USD: ${format(amount * current_price['usd'], ',.2f')}```\n"
                        else:
                            logging.error(f"Unable to pull information from data sources")
                            requested_spend = ""
                    else:
                        logging.error(f"Unable to pull information from data sources")
                        requested_spend = ""

                    title = values['title'][:95].strip() if values['title'] is not None else None
                    content = values['content'][:1451].strip() if values['content'] is not None else None

                    char_exceed_msg = "\n```Character count exceeded. For more insights, kindly visit the provided links```"
                    logging.info(f"Creating thread on Discord: {index}# {title}")

                    # Create Discord thread
                    #   content starts with `requested_spend`,
                    #   followed by `content` (or an empty string if `content` is None).
                    #   If `content` is long enough (1450 characters or more), it appends '...' and `char_exceed_msg`.
                    #   The string ends with two newline characters.
                    thread = await channel.create_thread(
                        name=f"{index}# {title}",
                        content=f"""{requested_spend}{Text.convert_markdown_to_discord(content) if content is not None else ''}{'...' + char_exceed_msg if content is not None and len(content) >= 1450 else ''}\n\n"""
                                f"**External links**"
                                f"\n<https://{config['network']}.polkassembly.io/referenda/{index}>"
                                f"\n<https://{config['network']}.subsquare.io/referenda/referendum/{index}>"
                                f"\n<https://{config['network']}.subscan.io/referenda_v2/{index}>",
                        reason=f"Created by an incoming proposal on the {config['network']} network",
                        applied_tags=[governance_tag]
                    )

                    logging.info(f"Thread created: {thread.message.id}")
                    # Send an initial results message in the thread
                    initial_results_message = "👍 AYE: 0    |    👎 NAY: 0    |    ☯ RECUSE: 0"

                    channel_thread = channel.get_thread(thread.message.id)
                    client.vote_counts[str(thread.message.id)] = {"index": index,
                                                                  "title": values['title'][:200].strip(),
                                                                  "aye": 0,
                                                                  "nay": 0,
                                                                  "recuse": 0,
                                                                  "users": {},
                                                                  "epoch": int(time.time())}
                    client.save_vote_counts()

                    results_message = await channel_thread.send(content=initial_results_message)
                    await thread.message.pin()
                    await results_message.pin()
                    await asyncio.sleep(1)
                    async for message in channel_thread.history(limit=5):
                        if message.type == discord.MessageType.pins_add:
                            await message.delete()

                    if guild is None:
                        logging.error(f"Guild with ID {guild_id} not found")
                    else:
                        role = await create_or_get_role(guild, role_name, client)
                        if role:
                            await channel_thread.send(content=
                            f"<@&{role.id}>"
                            f"\n**INSTRUCTIONS:**"
                            f"\n- Vote **AYE** if you want to see this proposal pass"
                            f"\n- Vote **NAY** if you want to see this proposal fail"
                            f"\n- Vote **RECUSE** if and **ONLY** if you have a conflict of interest with this proposal"
                            )
                    
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


@tasks.loop(hours=1)
async def recheck_proposals():
    """
    Asynchronously rechecks past proposals to populate missing titles and content.

    This function is a periodic task that runs every hour. It checks for past proposals where
    the title or content is missing and attempts to populate them with relevant data.


    Behavior:

    - Logs the start of the checking process for past proposals.
    - Retrieves proposals without context from a JSON file.
    - Initializes an OpenGovernance2 object.
    - Fetches the current price of a specified asset.
    - Iterates through each proposal, fetching and updating the missing data.
    - Updates the titles on the Discord threads for the proposals.
    - Saves the updated proposal data to the JSON file.
    - Logs the successful update of the proposals' data.
    """
    logging.info("Checking past proposals where title/content is None to populate them with relevant data")
    proposals_without_context = client.proposals_with_no_context('../data/vote_counts.json')
    opengov2 = OpenGovernance2()

    current_price = client.get_asset_price(asset_id=config['network'])

    for key, value in proposals_without_context.items():
        requested_spend = ""
        proposal_index = value['index']
        opengov = await opengov2.fetch_referendum_data(referendum_id=int(proposal_index), network=config['network'])

        if opengov['title'] != 'None':
            logging.info(f"Proposals have been found in the past where no title was set. Rechecking for title + content")
            if 'polkassembly' in opengov['successful_url'] and 'proposed_call' in list(opengov.keys()):
                if opengov['proposed_call']['method'] == 'spend':
                    amount = int(opengov['proposed_call']['args']['amount']) / float(config['token_decimal'])
                    requested_spend = f"```yaml\n" \
                                      f"{config['symbol']}: {amount}\n" \
                                      f"USD: ${format(amount * current_price['usd'], ',.2f')}```\n"

            elif 'subsquare' in opengov['successful_url'] and 'proposal' in list(opengov['onchainData'].keys()):
                if opengov['onchainData']['proposal'] is not None and opengov['onchainData']['proposal']['call']['method'] == 'spend':
                    amount = int(opengov['onchainData']['proposal']['call']['args'][0]['value']) / float(config['token_decimal'])
                    requested_spend = f"```yaml\n" \
                                      f"{config['symbol']}: {amount}\n" \
                                      f"USD: ${format(amount * current_price['usd'], ',.2f')}```\n"
            else:
                logging.error(f"Unable to pull information from data sources")
                requested_spend = ""

            title = opengov['title'][:95].strip()
            content = opengov['content'][:1451].strip()

            # governance_tag = next((tag for tag in available_channel_tags if tag.name == opengov['origin']), None)
            char_exceed_msg = "\n```Character count exceeded. For more insights, kindly visit the provided links```"

            # set title on thread id contained in vote_counts.json
            client.vote_counts[key]['title'] = title
            client.save_vote_counts()

            # Edit existing thread with new data found from Polkassembly or SubSquare
            logging.info(f"Editing discord thread with title + content: {proposal_index}# {title}")
            await client.edit_thread(forum_channel=discord_forum_channel_id,
                                     message_id=key,
                                     name=f"{proposal_index}# {opengov['title']}",
                                     content=f"""{requested_spend}{Text.convert_markdown_to_discord(content) if content is not None else ''}{'...' + char_exceed_msg if content is not None and len(content) >= 1450 else ''}\n\n"""
                                             f"**External links**"
                                             f"\n<https://{config['network']}.polkassembly.io/referenda/{proposal_index}>"
                                             f"\n<https://{config['network']}.subsquare.io/referenda/referendum/{proposal_index}>"
                                             f"\n<https://{config['network']}.subscan.io/referenda_v2/{proposal_index}>")
            logging.info(f"Title updated from None -> {title} in vote_counts.json")
            logging.info(f"Discord thread successfully amended")
        else:
            continue


@client.event
async def on_ready():
    print(f"Logged in as {client.user} (ID: {client.user.id})")
    print("Connected to the following servers:")
    for server in client.guilds:
        print(f"- {server.name} (ID: {server.id})")

    if not check_governance.is_running():
        check_governance.start()

    if not recheck_proposals.is_running():
        recheck_proposals.start()


if __name__ == '__main__':
    client.run(discord_api_key)
