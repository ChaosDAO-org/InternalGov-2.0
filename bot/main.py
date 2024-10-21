import time
import json
import discord
import asyncio
from utils.config import Config
from utils.logger import Logger
#from utils.proxy import ProxyVoter
from utils.gov2 import OpenGovernance2
from utils.subquery import SubstrateAPI
from datetime import datetime, timezone
from governance_monitor import GovernanceMonitor
from utils.embed_config import EmbedVoteScheme
from utils.data_processing import CacheManager, ProcessCallData, DiscordFormatting, Text
from utils.button_handler import ButtonHandler, ExternalLinkButton
from utils.task_handler import TaskHandler
from utils.argument_parser import ArgumentParser
from utils.permission_check import PermissionCheck
from discord import app_commands, Embed
from discord.ext import tasks


task_handler = TaskHandler()

@tasks.loop(hours=3)
async def check_governance():
    """
    Periodically checks for new governance proposals and creates Discord threads for them.

    This function runs every 3 hours to check for new referendums on OpenGov and creates corresponding threads
    in a configured Discord channel. It also manages archiving old proposals, locking their threads.

    Function workflow:
        - Waits until the Discord bot is fully ready.
        - Temporarily stops overlapping tasks (e.g., `sync_embeds`, `recheck_proposals`).
        - Backs up the current `vote_counts.json` file.
        - Checks for ongoing referendums on the blockchain and identifies new proposals.
        - Archives and locks threads for proposals that are no longer active.
        - If new proposals are found:
            - Retrieves the Discord channel and existing tags.
            - Creates new tags for the proposal's origin if necessary.
            - Creates a new Discord thread for each new proposal with the title, content, and appropriate tag.
            - Adds voting reactions (AYE, NAY, RECUSE) and relevant voting instructions to the thread.
            - Saves the new proposal data to `vote_counts.json`.
        - Sends notifications and embeds to the thread with updated proposal data, call information, and
          voting instructions.
        - Re-enables previously stopped tasks and closes the Substrate connection once check_governance is complete.
    """
    exception_occurred = False
    try:
        logging.info("Checking for new proposals")
        await client.wait_until_ready()
        await task_handler.evaluate_task_schedule(autonomous_voting)
        await task_handler.stop_tasks(coroutine_task=[sync_embeds, recheck_proposals])
        CacheManager.rotating_backup_file(source_path='../data/vote_counts.json', backup_dir='../data/backup/')

        opengov2 = OpenGovernance2(config, substrate)
        new_referendums, referendum_info_for = await opengov2.check_referendums()

        # Get the guild object where the role is located
        guild = client.get_guild(config.DISCORD_SERVER_ID)

        # Move votes from vote_counts.json -> archived_votes.json once they exceed X amount of days
        # lock threads once archived (prevents regular users from continuing to vote).
        logging.info(f"Checking active proposals from {config.NETWORK_NAME} against vote_counts.json to archive threads where the proposal is no longer active")
        active_proposals = await substrate.ongoing_referendums_idx()
        threads_to_lock = CacheManager.delete_executed_keys_and_archive(json_file_path='../data/vote_counts.json', active_proposals=active_proposals, archive_filename='../data/archived_votes.json')
        if threads_to_lock:
            try:
                await client.lock_threads(threads_to_lock, client.user)
            except Exception as e:
                logging.error(f"Failed to lock threads: {threads_to_lock}. Error: {e}")
        else:
            logging.info("No threads to lock")

        if not new_referendums:
            logging.info("No new proposals have been found since last checking")
            return None

        if new_referendums:
            logging.info(f"{len(new_referendums)} new proposal(s) found")
            channel = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID)
            current_price = client.get_asset_price_v2(asset_id=config.NETWORK_NAME)

            # go through each referendum if more than 1 was submitted in the given scheduled time
            for index, values in new_referendums.items():
                try:
                    available_channel_tags = []
                    if channel is not None:
                        available_channel_tags = [tag for tag in channel.available_tags]
                    else:
                        logging.error(f"Channel with ID {config.DISCORD_FORUM_CHANNEL_ID} not found")

                    title = values['title'][:config.DISCORD_TITLE_MAX_LENGTH].strip() if values['title'] is not None else None
                    logging.info(f"Creating thread on Discord: #{index} {title}")

                    if values['successful_url']:
                        logging.info(f"Getting on-chain data from: {values['successful_url']}")
                    else:
                        logging.error(f"No context has been set on this proposal: {values['successful_url']}")

                    governance_origin = [v for i, v in values['onchain']['origin'].items()]

                    # Creates forum tags if they don't already exist.
                    governance_tag = await client.get_or_create_governance_tag(available_channel_tags, governance_origin, channel)
                    new_proposal_thread = await client.manage_discord_thread(
                        channel=channel,
                        operation='create',
                        title=title,
                        index=index,
                        content=values['content'],
                        governance_tag=governance_tag,
                        message_id=None,
                        client=client
                    )

                    if not new_proposal_thread:
                        logging.error(f"Failed to create thread on Discord for: #{index} {title}")
                        continue

                    # Send an initial results message in the thread
                    initial_results_message = "👍 AYE: 0    |    👎 NAY: 0    |    ⛔️ RECUSE: 0"

                    channel_thread = await guild.fetch_channel(new_proposal_thread.message.id)
                    client.vote_counts[str(new_proposal_thread.message.id)] = {
                        "index": index,
                        "title": values['title'][:200].strip(),
                        "origin": governance_origin,
                        "aye": 0,
                        "nay": 0,
                        "recuse": 0,
                        "users": {},
                        "epoch": int(time.time())
                    }
                    await asyncio.sleep(0.5)
                    await client.save_vote_counts()
                    external_links = ExternalLinkButton(index, config.NETWORK_NAME)
                    results_message = await channel_thread.send(content=initial_results_message, view=external_links)

                    # results_message_id = results_message.id
                    await asyncio.sleep(0.5)
                    message_id = new_proposal_thread.message.id
                    voting_buttons = ButtonHandler(client, message_id)
                    await new_proposal_thread.message.edit(view=voting_buttons)

                    await asyncio.sleep(0.5)
                    await new_proposal_thread.message.pin()
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
                                instructions = await channel_thread.send(content=
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

                    try:
                        # Add fields to embed
                        await asyncio.sleep(0.5)
                        general_info = await discord_format.add_fields_to_embed(general_info_embed, referendum_info_for[index])
                        await new_proposal_thread.message.edit(embed=general_info)

                        # Add call data
                        await asyncio.sleep(0.5)
                        process_call_data = ProcessCallData(price=current_price)
                        call_data, preimagehash = await substrate.referendum_call_data(index=index, gov1=False, call_data=False)
                        call_data = await process_call_data.consolidate_call_args(call_data)
                        embedded_call_data = await process_call_data.find_and_collect_values(call_data, preimagehash)

                        await instructions.edit(embed=embedded_call_data, attachments=[discord.File(f'../assets/{config.NETWORK_NAME}/{config.NETWORK_NAME}.png', filename='symbol.png')])

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
    except Exception as error:
        exception_occurred = True
        logging.exception(f"An unexpected error occurred whilst running [check_governance]: {error}")
        await substrate.close()
        await asyncio.sleep(30)
        check_governance.restart()
    finally:
        if not exception_occurred:
            await substrate.close()
            if config.SOLO_MODE is False:
                await task_handler.start_tasks(coroutine_task=[autonomous_voting, sync_embeds, recheck_proposals])
            if config.SOLO_MODE is True:
                logging.info("Solo mode is enabled. To automatically vote using settings in /data/vote_periods, set SOLO_MODE=True in the .env config file")
                await task_handler.start_tasks(coroutine_task=[sync_embeds, recheck_proposals])


@tasks.loop(hours=12)
async def autonomous_voting():
    """
    Periodically casts on-chain votes based on when a proposal was submitted on-chain.

    This function runs every 12 hours to automatically vote on governance proposals
    using cached data and real-time information. It retrieves voting data, determines
    vote actions, and casts votes via a proxy account if necessary. It also handles
    updating on-chain voting records and notifying users on Discord.

    Function workflow:
        - Waits until the Discord bot is fully ready.
        - Temporarily stops other tasks (e.g., `sync_embeds`, `recheck_proposals`) to avoid conflicts.
        - Loads cached vote counts and on-chain voting data from local files.
        - Retrieves ongoing referendum and voting periods from the blockchain.
        - Iterates through each proposal in `vote_counts.json`:
            - Checks whether the proposal is still active on-chain.
            - Determines the appropriate vote action (aye, nay, abstain) based on internal result and proposal date.
            - Casts the first or second vote if needed, and updates the vote details in the `onchain-votes.json` file.
        - If votes are cast, the proxy account balance is checked, and a warning is logged and sent to Discord if the
          balance is too low.
        - After casting votes, updates the on-chain voting data with extrinsic hashes and timestamps.
        - Sends notifications to Discord, including vote details and extrinsic links, and pins the messages in
          the relevant threads.
        - Optionally, creates a summary thread for the vote results if a summarizer channel is configured.
        - Re-enables previously stopped tasks and closes the Substrate connection once autonomous_voting is complete.
    """
    exception_occurred = False
    try:
        logging.info("autonomous_voting task is running")
        await client.wait_until_ready()
        await task_handler.stop_tasks(coroutine_task=[sync_embeds, recheck_proposals])
        await client.disable_command(command_name='forcevote', guild_id=config.DISCORD_SERVER_ID)
        vote_counts = await client.load_vote_counts()
        onchain_votes = await client.load_onchain_votes()
        onchain_votes_length = len(str(onchain_votes))
        vote_periods = await client.load_vote_periods(network=config.NETWORK_NAME.lower())

        governance_cache = client.load_governance_cache()
        governance_cache_keys = governance_cache.keys()

        channel = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID)
        guild = client.get_guild(config.DISCORD_SERVER_ID)

        votes = []

        for thread_id, vote_data in vote_counts.items():
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

            proxy_balance = await substrate.proxy_balance()
            balance = await client.check_balance(proxy_balance=proxy_balance)
            if not balance:
                return

            logging.info("Casting on-chain votes")
            indexes, calls, extrinsic_hash = await substrate.execute_multiple_votes(votes)
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
                vote_scheme = EmbedVoteScheme(vote_type=vote_type)

                # Craft extrinsic receipt as Discord Embed
                extrinsic_embed = Embed(color=vote_scheme.color, title=f'An on-chain vote has been cast', description=f'{vote_scheme.emoji} {vote_type.upper()} on proposal **#{proposal_index}**',
                                        timestamp=datetime.now(timezone.utc))
                extrinsic_embed.add_field(name='Extrinsic hash', value=f'[{short_extrinsic_hash}](https://{config.NETWORK_NAME}.subscan.io/extrinsic/{extrinsic_hash})',
                                          inline=True)
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
                external_links = ExternalLinkButton(proposal_index, config.NETWORK_NAME)
                extrinsic_receipt_message = await discord_thread.send(content=f'<@&{role.id}>', embed=extrinsic_embed, view=external_links)
                await extrinsic_receipt_message.pin()

                # Delete pinned notification
                async for message in discord_thread.history(limit=5, oldest_first=False):
                    if message.type == discord.MessageType.pins_add:
                        await message.delete()

                if config.DISCORD_SUMMARIZER_CHANNEL_ID:
                    try:
                        logging.info(f"Creating thread for summarizing vote on {proposal_index}")
                        summary_notification_role = await client.create_or_get_role(guild, config.DISCORD_SUMMARY_ROLE)
                        internal_thread = vote_counts[data['thread_id']]
                        summary_channel = client.get_channel(config.DISCORD_SUMMARIZER_CHANNEL_ID)
                        external_links = ExternalLinkButton(proposal_index, config.NETWORK_NAME)
                        await summary_channel.create_thread(name=f"{proposal_index}: {internal_thread['title'][:config.DISCORD_TITLE_MAX_LENGTH].strip()}",
                                                            content=f"<@&{summary_notification_role.id}>\n<#{data['thread_id']}>",
                                                            embed=extrinsic_embed,
                                                            view=external_links,
                                                            reason='Vote has been cast onchain')
                        await asyncio.sleep(0.5)
                    except Exception as summary_error:
                        logging.exception(f"An error has occurred: {summary_error}")
            else:
                continue
    except Exception as error:
        exception_occurred = True
        logging.exception(f"An unexpected error occurred whilst running [automous_voting]: {error}")
        logging.info("Waiting 30 seconds before restarting task loop")
        await substrate.close()
        await asyncio.sleep(30)
        autonomous_voting.restart()
    finally:
        if not exception_occurred:
            await substrate.close()
            await task_handler.start_tasks(coroutine_task=[sync_embeds, recheck_proposals])
            await client.enable_command(command=forcevote, guild_id=config.DISCORD_SERVER_ID)


@tasks.loop(hours=1)
async def sync_embeds():
    """
    Periodically updates Discord thread embeds with the latest referendum data.

    This function runs every hour to ensure that Discord threads linked to referendums
    are updated with the latest information from the blockchain. It checks if new
    referendum details, like vote tallies or preimage data, are available and updates
    the embeds in the relevant Discord threads accordingly.

    Function workflow:
        - Waits until the Discord bot is fully ready.
        - Temporarily stops any conflicting tasks (e.g., `recheck_proposals`).
        - Fetches the latest referendum data using the OpenGovernance2 object.
        - Loads cached vote counts from a local JSON file.
        - Iterates through each proposal stored in `vote_counts.json`:
            - If a thread is archived, un-archives it to allow updates.
            - Updates the thread's embed with the latest referendum information,
              including vote tallies (ayes/nays) and preimage data if available.
            - Sets the embed color to green or red based on the current vote tally.
            - Adds missing components to the thread messages, like voting buttons or
              external links, if they are not already present.
        - Logs relevant information throughout the process, including synchronization
          status, errors, and successes.
        - Re-enables previously stopped tasks and closes the Substrate connection once sync_embeds is complete.
    """
    exception_occurred = False
    try:
        logging.info("Synchronizing embeds")
        await client.wait_until_ready()
        await task_handler.stop_tasks([recheck_proposals])
        referendum_info = await substrate.referendumInfoFor()
        json_data = CacheManager.load_data_from_cache('../data/vote_counts.json')
        current_price = client.get_asset_price_v2(asset_id=config.NETWORK_NAME)

        if json_data:
            index_msgid = await discord_format.find_msgid_by_index(referendum_info, json_data)
        else:
            logging.error("No data found in vote_counts.json")
            return None

        logging.info(f"{len(index_msgid)} threads to synchronize")

        # Synchronize in reverse from latest to oldest active proposals
        for index, message_id in sorted(index_msgid.items(), key=lambda item: int(item[0]), reverse=True):

            sync_thread = client.get_channel(int(message_id))

            # This will use fetch_channel() if the thread is marked as archived
            # It will edit the thread setting archived=False making the thread
            # visible for the bot to synchronise.
            if sync_thread is None:
                logging.info(f"Unable to see thread {message_id} using get_channel() - Attempting to fetch_channel and set archived=False")
                sync_thread = await client.fetch_channel(int(message_id))
                await sync_thread.edit(archived=False)

            if sync_thread is not None:
                logging.info(f"Synchronizing {sync_thread.name}")
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

                async for message in sync_thread.history(oldest_first=True, limit=5):
                    # This will update the embedded call data when the preimage wasn't available on-chain during the
                    # creation of the internal thread. If the preimage still isn't stored on-chain then it will leave
                    # the embed as :warning: Preimage not found on chain.
                    if message.author == client.user and message.content.startswith("||<@&"):
                        if not message.embeds:
                            await asyncio.sleep(0.5)
                            logging.info(f"Embedded call data not found, checking if preimage has been stored on-chain")
                            process_call_data = ProcessCallData(price=current_price)
                            call_data, preimagehash = await substrate.referendum_call_data(index=index, gov1=False, call_data=False)

                            if "Preimage not found" not in preimagehash:
                                call_data = await process_call_data.consolidate_call_args(call_data)
                                embedded_call_data = await process_call_data.find_and_collect_values(call_data, preimagehash)
                                await message.edit(embed=embedded_call_data, attachments=[discord.File(f'../assets/{config.NETWORK_NAME}/{config.NETWORK_NAME}.png', filename='symbol.png')])
                                logging.info("Embedded call data has now been added")
                                continue
                            else:
                                logging.warning("Preimage is missing")
                                continue

                        if message.embeds[0].description.startswith(":warning:"):
                            await asyncio.sleep(0.5)
                            logging.info(f"Checking if preimage has been stored on-chain")
                            process_call_data = ProcessCallData(price=current_price)
                            call_data, preimagehash = await substrate.referendum_call_data(index=index, gov1=False, call_data=False)

                            if "Preimage not found" not in preimagehash:
                                call_data = await process_call_data.consolidate_call_args(call_data)
                                embedded_call_data = await process_call_data.find_and_collect_values(call_data, preimagehash)
                                await message.edit(embed=embedded_call_data, attachments=[discord.File(f'../assets/{config.NETWORK_NAME}/{config.NETWORK_NAME}.png', filename='symbol.png')])
                                logging.info("Embedded call data has now been added")
                            else:
                                logging.warning("Preimage is still missing")

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
    except Exception as error:
        exception_occurred = True
        logging.exception(f"An unexpected error occurred whilst running [sync_embeds]: {error}")
        logging.info("Waiting 30 seconds before restarting task loop")
        await substrate.close()
        await asyncio.sleep(30)
        sync_embeds.restart()
    finally:
        if not exception_occurred:
            await substrate.close()
            await task_handler.start_tasks([recheck_proposals])


@tasks.loop(hours=1)
async def recheck_proposals():
    """
    Periodically checks and updates the titles of active proposals that have a Discord thread associated with them.

    This function runs every hour to check if the titles of active governance proposals
    have changed on Polkassembly or Subsquare, and updates the corresponding Discord
    threads with the new titles and content.

    Function workflow:
        - Waits until the Discord bot is fully ready.
        - Loads the existing vote counts from a JSON file.
        - Initializes the OpenGovernance2 object to fetch governance data.
        - Retrieves the specified Discord channel for proposal threads.
        - Iterates through each proposal stored in `vote_counts.json`:
            - Fetches the latest data for each proposal from Polkassembly or Subsquare.
            - Compares the current title with the stored title.
            - If the title has changed, updates the stored title in `vote_counts.json` and saves the file.
            - Updates the corresponding Discord thread with the new title and content.
            - Sends a message to the thread indicating the previous title before the change.
        - Logs relevant information during each step, including successes and any errors.
        - Closes the Substrate connection once recheck_proposals is complete
    """
    try:
        logging.info("recheck_proposals task is running")
        await client.wait_until_ready()
        vote_counts = await client.load_vote_counts()
        opengov2 = OpenGovernance2(config)
        channel = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID)

        for message_id, value in vote_counts.items():

            proposal_index = value['index']
            opengov = await opengov2.fetch_referendum_data(referendum_id=int(proposal_index), network=config.NETWORK_NAME)
            await asyncio.sleep(3)

            title_from_api = opengov['title'].strip()
            title_from_vote_counts = client.vote_counts[message_id]['title'].strip()

            if title_from_api == "None":
                continue

            if title_from_api != title_from_vote_counts:
                client.vote_counts[message_id]['title'] = title = title_from_api
                # set title on thread id contained in vote_counts.json
                await client.save_vote_counts()

                # Edit existing thread with new data found from Polkassembly or SubSquare
                logging.info(f"Editing discord thread with title + content: {proposal_index}# {title}")

                try:
                    await client.manage_discord_thread(
                        channel=channel,
                        operation='edit',
                        title=title_from_api,
                        index=proposal_index,
                        content=opengov['content'],
                        governance_tag="",
                        message_id=message_id,
                        client=client
                    )
                    thread_channel = channel.get_thread(int(message_id))
                    await thread_channel.send(content=f'Before the thread title was changed, it was:\n**{title_from_vote_counts}**')
                    logging.info(f"Title updated from {title_from_vote_counts} -> {title_from_api} in vote_counts.json")
                    logging.info(f"Discord thread successfully amended")
                except Exception as e:
                    logging.error(f"Failed to edit Discord thread: {e}")
            else:
                continue
        logging.info("recheck_proposals complete")
    except Exception as error:
        logging.exception(f"An unexpected error occurred whilst running [recheck_proposals]: {error}")
        raise error
    finally:
        await substrate.close()


@check_governance.before_loop
async def before_governance():
    check_governance.get_task().set_name('check_governance')


@autonomous_voting.before_loop
async def before_voting():
    autonomous_voting.get_task().set_name('autonomous_governance')


@sync_embeds.before_loop
async def before_sync_embeds():
    sync_embeds.get_task().set_name('sync_embeds')


@recheck_proposals.before_loop
async def before_recheck_proposals():
    recheck_proposals.get_task().set_name('recheck_proposals')


if __name__ == '__main__':
    config = Config()
    substrate = SubstrateAPI(config)
    discord_format = DiscordFormatting(substrate)

    guild = discord.Object(id=config.DISCORD_SERVER_ID)
    arguments = ArgumentParser()
    logging = Logger()
    logging.configure(log_level=3, filename_prefix='governance_bot', output_dir="../data/logs", days_to_keep=10)
    permission_checker = PermissionCheck()

    # Required to count members of a specific role
    # This is used to check participation % of an
    # internal vote before casting a vote.
    intents = discord.Intents.default()
    intents.members = True

    client = GovernanceMonitor(
        guild=guild,
        discord_role=config.DISCORD_VOTER_ROLE,
        permission_checker=permission_checker,
        intents=intents
    )


    @client.event
    async def on_ready():
        try:
            for server in client.guilds:
                await permission_checker.check_permissions(server, config.DISCORD_FORUM_CHANNEL_ID)

            await task_handler.start_tasks([check_governance])

        except KeyboardInterrupt:
            logging.warning("KeyboardInterrupt caught, cleaning up...")
            await task_handler.stop_tasks([check_governance, sync_embeds, autonomous_voting, recheck_proposals])

        except Exception as error:
            logging.error(f"An error occurred on on_ready(): {error}")
            await task_handler.stop_tasks([check_governance, sync_embeds, autonomous_voting, recheck_proposals])
            await task_handler.start_tasks([check_governance])

    # Slash command(s) available when solo mode is NOT enabled in the .env config
    # Commands:
    #   + /forcevote
    if config.SOLO_MODE is False:
        @client.tree.command(name='forcevote',
                             description='This command works only in threads with an active vote and when SOLO_MODE '
                                         'is disabled.',
                             guild=discord.Object(id=config.DISCORD_SERVER_ID))
        async def forcevote(interaction: discord.Interaction):

            channel = interaction.channel
            user_id = interaction.user.id

            vote_counts = await client.load_vote_counts()
            vote_count_channels = vote_counts.keys()

            member = await interaction.guild.fetch_member(user_id)
            roles = member.roles

            sufficient_permissions = await client.check_permissions(interaction=interaction, required_role=config.DISCORD_ADMIN_ROLE, user_id=user_id, user_roles=roles)
            if not sufficient_permissions:
                return

            try:
                proxy_balance = await substrate.proxy_balance()
                balance = await client.check_balance(interaction=interaction, proxy_balance=proxy_balance)
                if not balance:
                    return

                await asyncio.sleep(0.5)

                # Make sure the channel the command is running in is a channel with ongoing votes
                if str(channel.id) in vote_count_channels:
                    proposal_index = vote_counts.get(str(channel.id), {}).get('index', {})
                    aye = vote_counts.get(str(channel.id), {}).get('aye', {})
                    nay = vote_counts.get(str(channel.id), {}).get('nay', {})
                    recuse = vote_counts.get(str(channel.id), {}).get('recuse', {})
                    origin = vote_counts.get(str(channel.id), {}).get('origin', {})

                    vote = await client.calculate_proxy_vote(aye_votes=aye, nay_votes=nay)
                    role = await client.create_or_get_role(interaction.guild, config.EXTRINSIC_ALERT)
                    await asyncio.sleep(0.5)

                    await interaction.followup.send("Initializing extrinsic, please wait...", ephemeral=True)
                    votes = [(int(proposal_index), vote, config.CONVICTION)]

                    await asyncio.sleep(0.5)
                    indexes, calls, extrinsic_hash = await substrate.execute_multiple_votes(votes)
                    vote_scheme = EmbedVoteScheme(vote_type=vote)

                    if extrinsic_hash is False:
                        await interaction.followup.send(content="Unable to execute vote, please make sure the referendum is live!", ephemeral=True)
                        return

                    first_six = extrinsic_hash[:8]
                    last_six = extrinsic_hash[-8:]
                    short_extrinsic_hash = f"{first_six}...{last_six}"

                    extrinsic_embed = Embed(color=vote_scheme.color, title=f'An on-chain vote has been cast',
                                            description=f'{vote_scheme.emoji} {vote.upper()} on proposal **#{proposal_index}**', timestamp=datetime.now(timezone.utc))
                    extrinsic_embed.add_field(name='Extrinsic hash',value=f'[{short_extrinsic_hash}](https://{config.NETWORK_NAME}.subscan.io/extrinsic/{extrinsic_hash})', inline=True)
                    extrinsic_embed.add_field(name=f'Origin', value=f"{origin[0]}", inline=True)
                    extrinsic_embed.add_field(name=f'Executed by', value=f'<@{interaction.user.id}>', inline=True)
                    extrinsic_embed.add_field(name='\u200b', value='\u200b', inline=False)
                    extrinsic_embed.add_field(name='Aye', value=f"{aye}", inline=True)
                    extrinsic_embed.add_field(name='Nay', value=f"{nay}", inline=True)
                    extrinsic_embed.add_field(name='Recuse', value=f"{recuse}", inline=True)
                    extrinsic_embed.set_footer(text="This vote was forced using /forcevote")

                    channel = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID)
                    channel_thread = channel.get_thread(interaction.channel.id)

                    await asyncio.sleep(0.5)
                    extrinsic_receipt = await channel_thread.send(content=f'<@&{role.id}>', embed=extrinsic_embed)
                    await extrinsic_receipt.pin()

                    # Delete pinned notification
                    async for message in interaction.channel.history(limit=15, oldest_first=False):
                        if message.type == discord.MessageType.pins_add:
                            await message.delete()

                    await interaction.delete_original_response()
                else:
                    await interaction.followup.send(f"You are trying to force a vote on a channel that doesn't have an active internal vote ongoing", ephemeral=True)
            except Exception as error:
                await interaction.delete_original_response()
                await interaction.followup.send(content="An unexpected error occurred whilst running `/forcevote`", ephemeral=True)
                logging.exception(f"An unexpected error occurred whilst running /forcevote: {error}")
            finally:
                await substrate.close()

    # Slash command(s) available when solo mode IS enabled in the .env config
    # Commands:
    #   + /vote <referendum> <conviction> <decision>
    if config.SOLO_MODE is True:
        @client.tree.command(name='vote',
                             description='This command works in or out of threads with an active vote and only when '
                                         'SOLO_MODE is enabled.',
                             guild=discord.Object(id=config.DISCORD_SERVER_ID))
        @app_commands.choices(conviction=[app_commands.Choice(name='x0.1', value='None'),
                                          app_commands.Choice(name='x1', value='Locked1x'),
                                          app_commands.Choice(name='x2', value='Locked2x'),
                                          app_commands.Choice(name='x3', value='Locked3x'),
                                          app_commands.Choice(name='x4', value='Locked4x'),
                                          app_commands.Choice(name='x5', value='Locked5x'),
                                          app_commands.Choice(name='x6', value='Locked6x')],
                              decision=[app_commands.Choice(name='AYE', value='aye'),
                                        app_commands.Choice(name='NAY', value='nay'),
                                        app_commands.Choice(name='ABSTAIN', value='abstain')])
        async def vote(interaction: discord.Interaction, referendum: int, conviction: app_commands.Choice[str], decision: app_commands.Choice[str]):

            user_id = interaction.user.id

            member = await interaction.guild.fetch_member(user_id)
            roles = member.roles

            sufficient_permissions = await client.check_permissions(interaction=interaction, required_role=config.DISCORD_ADMIN_ROLE, user_id=user_id, user_roles=roles)
            if not sufficient_permissions:
                return

            try:
                proxy_balance = await substrate.proxy_balance()
                balance = await client.check_balance(interaction=interaction, proxy_balance=proxy_balance)
                if not balance:
                    return

                role = await client.create_or_get_role(interaction.guild, config.EXTRINSIC_ALERT)
                await asyncio.sleep(0.5)

                await interaction.followup.send("Initializing extrinsic, please wait...", ephemeral=True)
                votes = [(int(referendum), decision.value, conviction.value)]

                await asyncio.sleep(0.5)
                indexes, calls, extrinsic_hash = await substrate.execute_multiple_votes(votes)
                vote_scheme = EmbedVoteScheme(vote_type=decision.value)

                if extrinsic_hash is False:
                    await interaction.followup.send(content="Unable to execute vote, please make sure the referendum is live!", ephemeral=True)
                    return

                first_six = extrinsic_hash[:8]
                last_six = extrinsic_hash[-8:]
                short_extrinsic_hash = f"{first_six}...{last_six}"

                extrinsic_embed = Embed(color=vote_scheme.color, title=f'An on-chain vote has been cast',
                                        description=f'{vote_scheme.emoji} {decision.value.upper()} on proposal **#{referendum}**', timestamp=datetime.now(timezone.utc))
                extrinsic_embed.add_field(name='Extrinsic hash', value=f'[{short_extrinsic_hash}](https://{config.NETWORK_NAME}.subscan.io/extrinsic/{extrinsic_hash})', inline=True)
                extrinsic_embed.add_field(name=f'Executed by', value=f'<@{interaction.user.id}>', inline=True)
                extrinsic_embed.add_field(name='\u200b', value='\u200b', inline=False)
                extrinsic_embed.add_field(name=f'Decision', value=f"{decision.value.upper()}", inline=True)
                extrinsic_embed.add_field(name=f'Conviction', value=f"{conviction.value.upper()}", inline=True)
                extrinsic_embed.set_footer(text="This vote was made using /vote")

                channel = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID)
                channel_thread = channel.get_thread(interaction.channel.id)

                await asyncio.sleep(0.5)
                extrinsic_receipt = await channel_thread.send(content=f'<@&{role.id}>', embed=extrinsic_embed)
                await extrinsic_receipt.pin()

                # Delete pinned notification
                async for message in interaction.channel.history(limit=15, oldest_first=False):
                    if message.type == discord.MessageType.pins_add:
                        await message.delete()
                await interaction.delete_original_response()
            except Exception as error:
                await interaction.delete_original_response()
                await interaction.followup.send(content="An unexpected error occurred whilst running `/vote`", ephemeral=True)
                logging.exception(f"An unexpected error occurred whilst running /vote: {error}")
            finally:
                await substrate.close()

    @client.tree.command(name='thread',
                         description='Disable the voting buttons to a thread',
                         guild=discord.Object(id=config.DISCORD_SERVER_ID))
    @app_commands.choices(action=[app_commands.Choice(name='enable', value='enable'),
                                  app_commands.Choice(name='disable', value='disable')])
    async def thread(interaction: discord.Interaction, action: app_commands.Choice[str], thread_ids: str):

        user_id = interaction.user.id

        # Fetch the Member object for the user
        member = await interaction.guild.fetch_member(user_id)
        roles = member.roles

        sufficient_permissions = await client.check_permissions(interaction=interaction, required_role=config.DISCORD_ADMIN_ROLE, user_id=user_id, user_roles=roles)
        if not sufficient_permissions:
            return

        thread_ids_list = [int(x.strip()) for x in thread_ids.split(',')]
        lock_status = True if action.value == 'disable' else False
        await client.set_voting_button_lock_status(thread_ids_list, lock_status)
        await interaction.followup.send(f'The following thread(s) have been {action.name}d: {thread_ids_list}', ephemeral=False)


    try:
        config.initialize_environment_files()
        client.run(token=config.DISCORD_API_KEY, reconnect=True)
    except discord.ConnectionClosed:
        logging.error("Failed to connect to Discord")
    except discord.LoginFailure:
        logging.error("Invalid token provided")
    except Exception as err:
        logging.error(f"An unknown error occurred: {err}")
