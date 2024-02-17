import time
import json
import shutil
import discord
import asyncio
from utils.config import Config
from utils.logger import Logger
from utils.proxy import ProxyVoter
from utils.gov2 import OpenGovernance2
from utils.subquery import SubstrateAPI
from datetime import datetime, timezone
from governance_monitor import GovernanceMonitor
from utils.data_processing import CacheManager, DiscordFormatting, Text
from utils.button_handler import ButtonHandler, ExternalLinkButton
from utils.argument_parser import ArgumentParser
from utils.permission_check import PermissionCheck
from discord import app_commands, Embed
from discord.ext import tasks

discord_format = DiscordFormatting()


async def stop_tasks(coroutine_task):
    """
    Stops specified asynchronous tasks if they are currently running.

    This function iterates through a list of predefined tasks. For each task, it checks if the task is running and, if so, attempts to stop it.

    Tasks:
        - sync_embeds
        - recheck_proposals
        - autonomous_voting
    """
    await client.wait_until_ready()
    logging.info(f"Stopping tasks")
    for task in coroutine_task:
        try:
            if task.is_running():
                task.cancel()
                await asyncio.wait([task.get_task()])

            logging.info(f"Task successfully stopped")
        except Exception as e:
            logging.error(f"Error stopping {task.get_task().get_name()} task: {e}")


async def start_tasks(coroutine_task):
    """
    Restarts specified asynchronous tasks if they are not already running.

    This function iterates through a list of predefined tasks. For each task, it checks if the task is not running and, if so, attempts to start it. It logs the start of each task. If an exception occurs while starting a task, it logs the error.

    Tasks:
        - sync_embeds
        - recheck_proposals
        - autonomous_voting
    """
    await client.wait_until_ready()

    logging.info("Starting stopped tasks")
    for task in coroutine_task:
        try:
            if not task.is_running():
                task.start()
            logging.info(f"Task successfully started")
        except Exception as e:
            logging.error(f"Error starting {task.get_task().get_name()} task: {e}")


@tasks.loop(hours=3)
async def check_governance():
    """A function that checks for new referendums on OpenGovernance2, creates a thread for each new
    referendum on a Discord channel with a specified ID, and adds reactions to the thread.

    This function uses the Discord API to interact with the Discord platform. The Discord API provides
    methods for creating a thread and adding reactions to it, as well as accessing information about
    channels and tags.

    The `check_referendums` function from the `OpenGovernance2` class is called to get the new
    referendums. The code then iterates through each new referendum and performs the following actions:

    Behavior:
        - Gets the available tags for the Discord channel.
        - Creates a new tag for the origin of the referendum if it doesn't already exist.
        - Creates a new thread for the referendum on the Discord channel, with the title and content of the referendum, and the newly created or existing tag.
        - Adds reactions to the thread to allow users to vote on the referendum.

    The loop is set to run every 6 hrs, so the bot will continuously check for new referendums
    and create threads for them on the Discord channel.
    """
    try:
        await client.wait_until_ready()
        CacheManager.rotating_backup_file(source_path='../data/vote_counts.json', backup_dir='../data/backup/')

        logging.info("Checking for new proposals")
        opengov2 = OpenGovernance2(config)
        new_referendums = await opengov2.check_referendums()

        # Get the guild object where the role is located
        guild = client.get_guild(config.DISCORD_SERVER_ID)

        if not new_referendums:
            logging.info("No new proposals have been found since last checking")
            return None

        if new_referendums:
            logging.info(f"{len(new_referendums)} new proposal(s) found")
            channel = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID)
            current_price = client.get_asset_price(asset_id=config.NETWORK_NAME)

            referendum_info = await substrate.referendumInfoFor()
            # go through each referendum if more than 1 was submitted in the given scheduled time
            for index, values in new_referendums.items():
                requested_spend = ""
                try:
                    # proposal_ends = opengov2.time_until_block(target_block=values['onchain']['alarm'][0])
                    available_channel_tags = []
                    if channel is not None:
                        available_channel_tags = [tag for tag in channel.available_tags]
                    else:
                        logging.error(f"Channel with ID {config.DISCORD_FORUM_CHANNEL_ID} not found")
                        # Handle the error as appropriate for your application
                    governance_origin = [v for i, v in values['onchain']['origin'].items()]

                    # Create forum tags if they don't already exist.
                    governance_tag = await client.get_or_create_governance_tag(available_channel_tags, governance_origin, channel)

                    if values['successful_url']:
                        logging.info(f"Getting on-chain data from: {values['successful_url']}")
                        #  get_requested_spend handles the differences in returned JSON between Polkassembly & Subsquare
                        requested_spend = await client.get_requested_spend(values, current_price)
                    else:
                        logging.error(f"No value: {values['successful_url']}")
                        requested_spend = ""

                    title = values['title'][:config.DISCORD_TITLE_MAX_LENGTH].strip() if values['title'] is not None else None

                    logging.info(f"Creating thread on Discord: #{index} {title}")

                    try:
                        thread = await client.manage_discord_thread(
                            channel=channel,
                            operation='create',
                            title=title,
                            index=index,
                            requested_spend=requested_spend,
                            content=values['content'],
                            governance_tag=governance_tag,
                            message_id=None,
                            client=client
                        )
                        logging.info(f"Thread created: {thread.message.id}")
                    except Exception as e:
                        logging.error(f"Failed to create thread: {e}")
                        return None  # Make sure to return None if an exception occurs
                    # Send an initial results message in the thread
                    initial_results_message = "👍 AYE: 0    |    👎 NAY: 0    |    ⛔️ RECUSE: 0"

                    channel_thread = channel.get_thread(thread.message.id)
                    client.vote_counts[str(thread.message.id)] = {
                        "index": index,
                        "title": values['title'][:200].strip(),
                        "origin": governance_origin,
                        "aye": 0,
                        "nay": 0,
                        "recuse": 0,
                        "users": {},
                        "epoch": int(time.time())
                    }
                    await client.save_vote_counts()
                    external_links = ExternalLinkButton(index, config.NETWORK_NAME)
                    results_message = await channel_thread.send(content=initial_results_message, view=external_links)

                    # results_message_id = results_message.id
                    message_id = thread.message.id
                    voting_buttons = ButtonHandler(client, message_id)
                    await thread.message.edit(view=voting_buttons)

                    await thread.message.pin()
                    await results_message.pin()

                    # Searches the last 5 messages
                    async for message in channel_thread.history(limit=5):
                        if message.type == discord.MessageType.pins_add:
                            await message.delete()

                    if guild is None:
                        logging.error(f"Guild not found")
                    else:
                        try:
                            role = await client.create_or_get_role(guild, config.TAG_ROLE_NAME)
                            if role:
                                await channel_thread.send(content=
                                                          f"||<@&{role.id}>||"
                                                          f"\n**INSTRUCTIONS:**"
                                                          f"\n- Vote **AYE** if you want to see this proposal pass"
                                                          f"\n- Vote **NAY** if you want to see this proposal fail"
                                                          f"\n- Vote **RECUSE** if and **ONLY** if you have a conflict of interest with this proposal"
                                                          )
                                logging.info(f"Vote results message added instruction message added for {index}")
                        except Exception as error:
                            logging.error(f"An unexpected error occurred: {error}")

                    general_info_embed = Embed(color=0x00FF00)
                    polkasembly_info_embed = Embed(color=0xFFFFFF)

                    try:
                        # Add fields to embed
                        general_info = await discord_format.add_fields_to_embed(general_info_embed, referendum_info[index])
                        passembly_call_data = await discord_format.extract_and_embed(values, polkasembly_info_embed)
                        await asyncio.sleep(0.5)
                        await channel_thread.send(embed=passembly_call_data)
                        await asyncio.sleep(0.5)

                        # Edit the message
                        await thread.message.edit(embed=general_info)
                    except Exception as e:
                        # Log the exception
                        logging.error(f"An error occurred: {e}")

                except discord.errors.Forbidden as forbidden:
                    logging.exception(f"Forbidden error occurred:  {forbidden}")
                    raise forbidden
                except discord.errors.HTTPException as http:
                    logging.exception(f"HTTP exception occurred: {http}")
                    raise http
                except Exception as error:
                    logging.exception(f"An unexpected error occurred: {error}")
                    raise error

        # Move votes from vote_counts.json -> archived_votes.json once they exceed X amount of days
        # lock threads once archived (prevents regular users from continuing to vote).
        threads_to_lock = CacheManager.delete_old_keys_and_archive(json_file_path='../data/vote_counts.json', days=config.DISCORD_LOCK_THREAD, archive_filename='../data/archived_votes.json')
        if threads_to_lock:
            try:
                await client.lock_threads(threads_to_lock, client.user)
            except Exception as e:
                logging.error(f"Failed to lock threads: {threads_to_lock}. Error: {e}")
        else:
            logging.info("No threads to lock")
    except Exception as error:
        logging.exception(f"An unexpected error occurred: {error}")
        raise error
    finally:
        await start_tasks(coroutine_task=[autonomous_voting])


@tasks.loop(hours=1)
async def sync_embeds():
    """
    This asynchronous function is designed to run every hour to synchronize embeds on discord threads.
    It interacts with OpenGovernance2 to retrieve referendum information and loads cached vote
    counts from a local JSON file.

    It then logs the synchronization process, finds message IDs by index from the
    referendum info, and updates the embeds in the relevant Discord threads with the
    new information.

    Behavior:
        - Updates Discord embeds in threads with new information and potentially new colors.
        - Logs information, errors, and completion status of the synchronization process.
        - Edits messages in Discord with new views and embeds.
    """
    await client.wait_until_ready()
    try:
        referendum_info = await substrate.referendumInfoFor()
        json_data = CacheManager.load_data_from_cache('../data/vote_counts.json')

        logging.info("Synchronizing embeds")
        if json_data:
            index_msgid = await discord_format.find_msgid_by_index(referendum_info, json_data)
        else:
            logging.error("No data found in vote_counts.json")
            return None

        logging.info(f"{len(index_msgid)} threads to synchronize")
        # Synchronize in reverse from latest to oldest active proposals
        for index, message_id in sorted(index_msgid.items(), reverse=True):
            sync_thread = client.get_channel(int(message_id))
            logging.info(f"Synchronizing {sync_thread.name}")
            if sync_thread is not None:
                async for message in sync_thread.history(oldest_first=True, limit=1):
                    if referendum_info[index]['Ongoing']['tally']['ayes'] >= referendum_info[index]['Ongoing']['tally']['nays']:
                        general_info_embed = Embed(color=0x00FF00)
                    else:
                        general_info_embed = Embed(color=0xFF0000)

                    # Update initial post
                    general_info = await discord_format.add_fields_to_embed(general_info_embed, referendum_info[index])
                    await message.edit(embed=general_info)

                    # Add voting buttons if no components found on message
                    if not message.components:
                        voting_buttons = ButtonHandler(client, message_id)
                        await message.edit(view=voting_buttons)

                async for message in sync_thread.history(oldest_first=True):
                    # Add hyperlinks to results if no components found on message
                    if message.author == client.user and message.content.startswith("👍 AYE:") and not message.components:
                        logging.info("Adding missing hyperlink buttons")
                        external_links = ExternalLinkButton(index, config.NETWORK_NAME)
                        await message.edit(view=external_links)
                        break

                logging.info(f"Successfully synchronized {sync_thread.name}")
                await asyncio.sleep(2.5)
            else:
                logging.error(f"Thread with index {index} - {message_id} not found.")
        logging.info("synchronization complete")
    except Exception as sync_embeds_error:
        logging.exception(f"An error occurred whilst synchronizing embeds: {sync_embeds_error}")
        logging.info("Waiting 3 seconds before restarting task loop")
        await asyncio.sleep(3)
        sync_embeds.restart()


@tasks.loop(hours=12)
async def autonomous_voting():
    try:
        await client.wait_until_ready()
        await stop_tasks(coroutine_task=[sync_embeds, recheck_proposals])
        vote_counts = await client.load_vote_counts()
        onchain_votes = await client.load_onchain_votes()
        onchain_votes_length = len(str(onchain_votes))
        vote_periods = await client.load_vote_periods(network=config.NETWORK_NAME.lower())

        governance_cache = client.load_governance_cache()
        governance_cache_keys = governance_cache.keys()

        channel = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID)
        alert_channel = client.get_channel(config.DISCORD_PROXY_BALANCE_ALERT)
        guild = client.get_guild(config.DISCORD_SERVER_ID)

        voter = ProxyVoter(main_address=config.PROXIED_ADDRESS, proxy_mnemonic=config.MNEMONIC, url=config.SUBSTRATE_WSS)
        votes = []

        logging.info("autonomous_voting task is running")
        proxy_balance = await voter.proxy_balance()

        for thread_id, vote_data in vote_counts.items():
            if proxy_balance <= config.PROXY_BALANCE_ALERT:
                logging.warning(f"Balance is too low: {proxy_balance}")
                # Post on discord with balance and public address to make it easier to top up
                proxy_address_qr = Text.generate_qr_code(publickey=config.PROXY_ADDRESS)

                balance_embed = Embed(color=0xFF0000, title=f'Low balance detected', description=f'Balance is {proxy_balance:.4f}, which is below the minimum required for voting with the proxy. Please add funds to continue without interruption.', timestamp=datetime.utcnow())
                balance_embed.add_field(name='Address', value=f'{config.PROXY_ADDRESS}', inline=True)
                balance_embed.set_thumbnail(url="attachment://proxy_address_qr.png")
                await alert_channel.send(embed=balance_embed, file=discord.File(proxy_address_qr, "proxy_address_qr.png"))
                break

            await asyncio.sleep(2)
            # Only vote on proposals where "origin" is present in vote_counts.json
            # This is only required for versions of the bot that didn't capture
            # the origin in vote_counts.json. To be deprecated in the future.
            if "origin" in vote_data:
                # Pass over any referendums that may be held in vote_counts.json that are not Ongoing.
                # If the index is held in onchain-votes.json but not Ongoing, set decision_period_passed to True
                if vote_data['index'] not in governance_cache_keys:
                    if vote_data['index'] in onchain_votes.keys():
                        onchain_votes[vote_data['index']]["decision_period_passed"] = True
                    continue

                proposal_index = vote_data['index']
                proposal_origin = vote_data["origin"][0]
                internal_vote_periods = vote_periods.get(proposal_origin, {})

                proposal_block_submitted = governance_cache[proposal_index]['Ongoing']['submitted']
                proposal_block_epoch = await substrate.get_block_epoch(block_number=proposal_block_submitted)
                logging.info(f"Checking Discord vote results for: {proposal_index}")
                cast, vote_type = await client.determine_vote_action(vote_data=vote_data, origin=internal_vote_periods, proposal_epoch=proposal_block_epoch)
                logging.info(f"Result: {vote_type}")

                # If the proposal already exists in the results, use the existing 1st_vote data
                if proposal_index in onchain_votes:
                    _1st_vote_type = onchain_votes[proposal_index]['1st_vote']['vote_type']
                    _2nd_vote_type = onchain_votes[proposal_index]['2nd_vote']['vote_type']
                    has_previous_vote_changed = _1st_vote_type == vote_type

                    # Only update 1st_vote if it's not already set
                    if not onchain_votes[proposal_index]["1st_vote"]["extrinsic"] and cast == 1:
                        logging.info("Preparing to cast the first vote")
                        onchain_votes[proposal_index]["1st_vote"]["vote_type"] = vote_type
                        onchain_votes[proposal_index]["1st_vote"]["aye"] = vote_data['aye']
                        onchain_votes[proposal_index]["1st_vote"]["nay"] = vote_data['nay']
                        onchain_votes[proposal_index]["1st_vote"]["recuse"] = vote_data['recuse']

                        votes.append((int(proposal_index), vote_type, config.CONVICTION))

                    # Only update 2nd_vote if it's not already set
                    if not onchain_votes[proposal_index]["2nd_vote"]["extrinsic"] and cast == 2:
                        if not has_previous_vote_changed:
                            logging.info("Preparing to cast the second vote")
                            onchain_votes[proposal_index]["2nd_vote"]["vote_type"] = vote_type
                            onchain_votes[proposal_index]["2nd_vote"]["aye"] = vote_data['aye']
                            onchain_votes[proposal_index]["2nd_vote"]["nay"] = vote_data['nay']
                            onchain_votes[proposal_index]["2nd_vote"]["recuse"] = vote_data['recuse']
                            votes.append((int(proposal_index), vote_type, config.CONVICTION))
                        else:
                            logging.info(f"The second vote hasn't changed from the first vote. No vote shall be cast on {proposal_index}")
                            onchain_votes[proposal_index]["2nd_vote"]["vote_type"] = vote_type
                            onchain_votes[proposal_index]["2nd_vote"]["extrinsic"] = "The vote has not changed since the 1st vote"
                            onchain_votes[proposal_index]["2nd_vote"]["timestamp"] = str(datetime.now(timezone.utc))
                else:
                    onchain_votes[proposal_index] = {
                        "thread_id": thread_id,
                        "origin": vote_data["origin"][0],
                        "decision_period_passed": True if cast == 0 else False,
                        "1st_vote": {
                            "aye": "",
                            "nay": "",
                            "recuse": "",
                            "vote_type": "",
                            "extrinsic": "",
                            "timestamp": ""
                        },
                        "2nd_vote": {
                            "aye": "",
                            "nay": "",
                            "recuse": "",
                            "vote_type": "",
                            "extrinsic": "",
                            "timestamp": ""
                        }
                    }

                onchain_votes[proposal_index]["decision_period_passed"] = True if cast == 0 else False
            await asyncio.sleep(2.5)

        if len(str(onchain_votes)) != onchain_votes_length:
            with open("../data/onchain-votes.json", "w") as outfile:
                json.dump(onchain_votes, outfile, indent=4)

        # Only cast a vote if we have any to cast
        if len(votes) > 0:
            logging.info("Casting on-chain votes")
            #  voter = ProxyVoter(main_address=config.PROXIED_ADDRESS, proxy_mnemonic=config.MNEMONIC, url=config.SUBSTRATE_WSS)
            indexes, calls, extrinsic_hash = await voter.execute_multiple_votes(votes)
        else:
            return

        # Loop through all successful indexes from execute_multiple_votes and update
        # the onchain-votes.json file with the extrinsic hash + timestamp
        for index in indexes:
            logging.info(f"saving extrinsic hash in onchain-votes.json for {index}")
            if onchain_votes[index]["1st_vote"]["vote_type"] in ['aye', 'nay', 'abstain'] and not onchain_votes[index]["1st_vote"]["extrinsic"]:
                onchain_votes[index]["1st_vote"]["extrinsic"] = extrinsic_hash
                onchain_votes[index]["1st_vote"]["timestamp"] = str(datetime.now(timezone.utc))

            if onchain_votes[index]["2nd_vote"]["vote_type"] in ['aye', 'nay', 'abstain'] and not onchain_votes[index]["2nd_vote"]["extrinsic"]:
                onchain_votes[index]["2nd_vote"]["extrinsic"] = extrinsic_hash
                onchain_votes[index]["2nd_vote"]["timestamp"] = str(datetime.now(timezone.utc))
            await asyncio.sleep(0.5)

        if len(str(onchain_votes)) != onchain_votes_length:
            with open("../data/onchain-votes.json", "w") as outfile:
                json.dump(onchain_votes, outfile, indent=4)

        vote_type_emojis = {
            "aye": "👍",
            "nay": "👎",
            "abstain": "⛔"
        }

        vote_type_color = {
            "aye": 0x00FF00,
            "nay": 0xFF0000,
            "abstain": 0xFFFFFF
        }

        # Extracting first 6 and last 6 characters of the extrinsic hash
        # and shorten it for Discord Embed.
        first_six = extrinsic_hash[:8]
        last_six = extrinsic_hash[-8:]
        short_extrinsic_hash = f"{first_six}...{last_six}"

        role = await client.create_or_get_role(guild, config.EXTRINSIC_ALERT)

        for proposal_index, data in onchain_votes.items():
            if data['decision_period_passed']:
                continue

            vote_count = 2 if data['2nd_vote']['extrinsic'] else 1 if data['1st_vote']['extrinsic'] else 0
            vote_type = next((vote[1] for vote in votes if vote[0] == int(proposal_index)), None)
            vote_data = data['2nd_vote'] if vote_count == 2 else data['1st_vote'] if vote_count == 1 else None

            if vote_type:
                aye = vote_data.get('aye', 'ERR')  # Returns 0 if 'aye' key is not found
                nay = vote_data.get('nay', 'ERR')  # Returns 0 if 'nay' key is not found
                recuse = vote_data.get('recuse', 'ERR')  # Returns 0 if 'recuse' key is not found

                logging.info(f"Posting extrinsic URL on discord as a Proof-of-Vote on {proposal_index}")
                discord_thread = channel.get_thread(int(data['thread_id']))
                internal_vote_periods = vote_periods.get(data['origin'], {})

                # Craft extrinsic receipt as Discord Embed
                extrinsic_embed = Embed(color=vote_type_color[vote_type], title=f'An on-chain vote has been cast', description=f'{vote_type_emojis[vote_type]} {vote_type.upper()} on proposal **#{proposal_index}**', timestamp=datetime.utcnow())
                extrinsic_embed.add_field(name='Extrinsic hash', value=f'[{short_extrinsic_hash}](https://{config.NETWORK_NAME}.subscan.io/extrinsic/{extrinsic_hash})', inline=True)
                extrinsic_embed.add_field(name=f'Origin', value=f"{data['origin']}", inline=True)
                extrinsic_embed.add_field(name=f'Vote count', value=f'{vote_count} out of 2', inline=True)
                extrinsic_embed.add_field(name='\u200b', value='\u200b', inline=False)
                extrinsic_embed.add_field(name='Aye', value=f"{aye}", inline=True)
                extrinsic_embed.add_field(name='Nay', value=f"{nay}", inline=True)
                extrinsic_embed.add_field(name='Recuse', value=f"{recuse}", inline=True)
                extrinsic_embed.add_field(name='\u200b', value='\u200b', inline=False)
                extrinsic_embed.add_field(name='Decision Period', value=f"{internal_vote_periods['decision_period']} days", inline=True)
                extrinsic_embed.add_field(name=f'First vote', value=f"{internal_vote_periods['internal_vote_period']} day(s) after being on-chain", inline=True)
                extrinsic_embed.add_field(name=f'Second vote', value=f"{internal_vote_periods['revote_period']} days after being on-chain", inline=True)
                extrinsic_embed.set_footer(text="A second vote is initiated only if the first vote's result is disputed or missed")

                # Send Embed
                extrinsic_receipt_message = await discord_thread.send(content=f'<@&{role.id}>', embed=extrinsic_embed)
                await extrinsic_receipt_message.pin()

                # Delete pinned notification
                async for message in discord_thread.history(limit=5, oldest_first=False):
                    if message.type == discord.MessageType.pins_add:
                        await message.delete()
            else:
                continue

    except Exception as error:
        logging.exception(f"An unexpected error occurred: {error}")
        raise error
    finally:
        await start_tasks(coroutine_task=[sync_embeds, recheck_proposals])


@tasks.loop(hours=3)
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
    await client.wait_until_ready()
    logging.info("recheck_proposals task is running")
    proposals_without_context = client.proposals_with_no_context('../data/vote_counts.json')
    opengov2 = OpenGovernance2(config)
    channel = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID)
    current_price = client.get_asset_price(asset_id=config.NETWORK_NAME)

    for message_id, value in proposals_without_context.items():

        proposal_index = value['index']
        opengov = await opengov2.fetch_referendum_data(referendum_id=int(proposal_index), network=config.NETWORK_NAME)
        await asyncio.sleep(1)
        if opengov['title'] != 'None':
            requested_spend = await client.get_requested_spend(opengov, current_price)
            client.vote_counts[message_id]['title'] = title = opengov['title'][:config.DISCORD_TITLE_MAX_LENGTH].strip()
            # set title on thread id contained in vote_counts.json
            await client.save_vote_counts()

            # Edit existing thread with new data found from Polkassembly or SubSquare
            logging.info(f"Editing discord thread with title + content: {proposal_index}# {title}")

            try:
                await client.manage_discord_thread(
                    channel=channel,
                    operation='edit',
                    title=title,
                    index=proposal_index,
                    requested_spend=requested_spend,
                    content=opengov['content'],
                    governance_tag="",
                    message_id=message_id,
                    client=client
                )
                logging.info(f"Title updated from None -> {title} in vote_counts.json")
                logging.info(f"Discord thread successfully amended")
            except Exception as e:
                logging.error(f"Failed to edit Discord thread: {e}")
        else:
            continue
    logging.info("recheck_proposals complete")


if __name__ == '__main__':
    config = Config()

    substrate = SubstrateAPI(config)
    guild = discord.Object(id=config.DISCORD_SERVER_ID)
    arguments = ArgumentParser()
    logging = Logger(arguments.args.verbose)
    permission_checker = PermissionCheck()

    client = GovernanceMonitor(
        guild=guild,
        discord_role=config.DISCORD_VOTER_ROLE,
        permission_checker=permission_checker,
    )


    @client.event
    async def on_ready():
        try:
            for server in client.guilds:
                await permission_checker.check_permissions(server, config.DISCORD_FORUM_CHANNEL_ID)
            if not check_governance.is_running():
                check_governance.start()
        except KeyboardInterrupt:
            logging.warning("KeyboardInterrupt caught, cleaning up...")
            await stop_tasks()


    @client.tree.command()
    @app_commands.choices(action=[app_commands.Choice(name='enable', value='enable'), app_commands.Choice(name='disable', value='disable')])
    async def thread(interaction: discord.Interaction, action: app_commands.Choice[str], thread_ids: str):
        user = interaction.user
        guild = interaction.guild
        thread_ids_list = None  # Initialize to avoid UnboundLocalError

        # Fetch the Member object for the user
        member = await guild.fetch_member(user.id)

        role = discord.utils.get(guild.roles, name=config.DISCORD_ADMIN_ROLE)
        if role not in member.roles:
            msg = await interaction.response.send_message("You're not cool enough to do this.", ephemeral=True)
            await asyncio.sleep(10)
            await interaction.delete_original_response()

            return

        thread_ids_list = [int(x.strip()) for x in thread_ids.split(',')]
        lock_status = True if action.value == 'disable' else False
        await client.set_voting_button_lock_status(thread_ids_list, lock_status)
        await interaction.response.send_message(f'The following thread(s) have been {action.name}d: {thread_ids_list}', ephemeral=True)


    try:
        client.run(token=config.DISCORD_API_KEY, reconnect=True)
    except discord.ConnectionClosed:
        logging.error("Failed to connect to Discord")
    except discord.LoginFailure:
        logging.error("Invalid token provided")
    except Exception as err:
        logging.error(f"An unknown error occurred: {err}")
