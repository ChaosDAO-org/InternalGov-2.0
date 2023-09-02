import yaml
import json
import requests
import aiohttp
import logging
from typing import Union, Any
from utils.data_processing import CacheManager
from logging.handlers import TimedRotatingFileHandler
from substrateinterface import SubstrateInterface

class OpenGovernance2:
    def __init__(self, config):
        self.config = config
        self.util = CacheManager
        self.substrate = SubstrateInterface(
            url=self.config.SUBSTRATE_WSS,
            type_registry_preset=self.config.NETWORK_NAME
        )

    def referendumInfoFor(self, index=None):
        """
        Get information regarding a specific referendum or all ongoing referendums.

        :param index: (optional) index of the specific referendum
        :return: dictionary containing the information of the specific referendum or a dictionary of all ongoing referendums
        :raises: ValueError if `index` is not None and not a valid index of any referendum
        """
        referendum = {}
        if index is not None:
            return self.substrate.query(
                module='Referenda',
                storage_function='ReferendumInfoFor',
                params=[index]).serialize()
        else:
            qmap = self.substrate.query_map(
                module='Referenda',
                storage_function='ReferendumInfoFor',
                params=[])
            for index, info in qmap:
                if 'Ongoing' in info:
                    referendum.update({int(index.value): info.value})

            sort = json.dumps(referendum, sort_keys=True)
            data = json.loads(sort)
            return data
        
    def get_display_name(self, address: str) -> str:
        # Fetch the identity info associated with the given address.
        identity_info = self.substrate.query(
            module='Identity',
            storage_function='IdentityOf',
            params=[address]
        )

        # Check if identity info exists.
        if identity_info is None or identity_info.value is None or 'info' not in identity_info.value:
            return None

        # Get the display name.
        display_name_data = identity_info.value['info']['display']
        if 'Raw' in display_name_data:
            display_name = display_name_data['Raw']
        else:
            # Handle other types of Data encoding if needed
            display_name = None

        return display_name



        
    def format_key(self, key, parent_key):
        FIELD_NAME_MAP = {
            "Ongoing.alarm": "Ending Block",
            "Ongoing.deciding.confirming": "Confirming",
            "Ongoing.deciding.since": "Confirming Since",
            "Ongoing.decision_deposit.amount": "Decision Deposit Amount",
            "Ongoing.decision_deposit.who": "Decision Deposit Who",
            "Ongoing.enactment.After": "Enactment After",
            "Ongoing.in_queue": "In Queue",
            "Ongoing.origin.Origins": "Origin",
            "Ongoing.proposal.Lookup.hash": "Proposal Hash",
            "Ongoing.proposal.Lookup.len": "Proposal Length",
            "Ongoing.submission_deposit.amount": "Submission Deposit Amount",
            "Ongoing.submission_deposit.who": "Submission Deposit Who",
            "Ongoing.submitted": "Submitted",
            "Ongoing.tally.ayes": "Ayes",
            "Ongoing.tally.nays": "Nays",
            "Ongoing.tally.support": "Support",
            "Ongoing.track": "Track"
        }
        full_key = f"{parent_key}.{key}" if parent_key else key
        formatted_key = FIELD_NAME_MAP.get(full_key, full_key)
        
        # Handle special case for 'Ongoing.alarm'
        
            
        return formatted_key

    def add_fields_to_embed(self, embed, data, parent_key=""):
        char_count = 0
        field_data = {} 
        field_order = [
            'Origin',         
            'Decision Deposit Amount', 
            'Submission Deposit Amount', 
            'Ending Block', 
            'Confirming', 
            'Confirming Since',
            'Decision Deposit Who', 
            'Submission Deposit Who',         
            'Since', 
            'Enactment After',
            'Ayes', 
            'Nays', 
            'Support',
            'Submitted'
        ]

        for key, value in data.items():
            if parent_key == "comments" or key in ["Proposal Length" "Proposal Hash"]:
                continue
            formatted_key = self.format_key(key, parent_key)
                
            # Look up and add display name for specific keys
            if formatted_key in ['Decision Deposit Who', 'Submission Deposit Who']:
                display_name = self.get_display_name(address=value)
                if display_name:
                    value = f"[{display_name}](https://polkadot.subscan.io/account/{value})"
                else:
                    value = f"[{value}](https://polkadot.subscan.io/account/{value})"
            if formatted_key == "Ending Block":
                value = f"[{value[0]}](https://polkadot.subscan.io/block/{value[0]})"
                
            if formatted_key in ["Confirming Since", "Submitted"]:
                value = f"[{value}](https://polkadot.subscan.io/block/{value})"

            if formatted_key == "Confirming":
                value = "True" if isinstance(value, int) or (isinstance(value, str) and value.isdigit()) else "False"
                
            if any(keyword in formatted_key for keyword in ["Ayes", "Nays", "Support"]):
                value = "{:,.2f}".format(int(value) / self.config.TOKEN_DECIMAL)  # Add a dollar sign before the value
                
            if "Amount" in formatted_key:
                value = "{:,.2f}".format(int(value) / self.config.TOKEN_DECIMAL)
                value = f"{value} {self.config.SYMBOL}"# Add a dollar sign before the value
        
            
            #print(f"Char count: {char_count}, Key: {formatted_key}, Value: {value}")  # Debug line

            next_count = char_count + len(str(formatted_key)) + len(str(value))

            if next_count > 6000:
                logging.info("Stopping due to char limit")
                break

            if isinstance(value, dict):
                embed = self.add_fields_to_embed(embed, value, formatted_key)
            else:
                field_data[formatted_key] = value

            char_count = next_count

        # Moved outside data loop
        for key in field_order:
            if key in field_data:
                embed.add_field(name=key, value=field_data[key], inline=True)

        return embed

    @staticmethod
    async def fetch_referendum_data(referendum_id: int, network: str):
        """
        Fetches referendum data from a set of URLs using a given referendum ID and network name.

        The function makes HTTP GET requests to each URL in the list. If a response is successful
        and the JSON response contains a non-empty 'title', the function will immediately return
        that response without checking the remaining URLs. If none of the responses are successful,
        the function returns a default response indicating that the referendum details could not
        be retrieved.

        Parameters:
        referendum_id (int): The ID of the referendum to fetch data for.
        network (str): The name of the network where the referendum is held. This is used to
                       construct the URLs and to set the 'x-network' header in the HTTP requests.

        Returns:
        dict: A dictionary containing the referendum data. This dictionary includes a 'title' key,
              a 'content' key, and a 'successful_url' key. If no successful response is received
              from any of the URLs, the 'title' will be 'None', the 'content' will be a message
              indicating that the details could not be retrieved, and the 'successful_url' will be
              None. Otherwise, the returned dictionary will be the successful JSON response from
              one of the URLs, with a 'successful_url' key added to indicate which URL the
              response came from.
        """
        urls = [
            f"https://api.polkassembly.io/api/v1/posts/on-chain-post?postId={referendum_id}&proposalType=referendums_v2",
            f"https://{network}.subsquare.io/api/gov2/referendums/{referendum_id}",
        ]

        headers = {"x-network": network}
        successful_response = None
        successful_url = None

        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    async with session.get(url, headers=headers) as response:
                        response.raise_for_status()
                        json_response = await response.json()

                        # Add 'title' key if it doesn't exist
                        if "title" not in json_response.keys():
                            json_response["title"] = "None"

                        # Check if 'title' is not None or empty string
                        if json_response["title"] not in {None, "None", ""}:
                            successful_response = json_response
                            successful_url = url
                            # Once a successful response is found, no need to continue checking other URLs
                            break

                except aiohttp.ClientResponseError as http_error:
                    logging.error(f"HTTP exception occurred while accessing {url}: {http_error}")

        if successful_response is None:
            return {"title": "None",
                    "content": "Unable to retrieve details from both sources",
                    "successful_url": None}
        else:
            successful_response["successful_url"] = successful_url
            return successful_response
        
    def get_average_block_time(self, num_blocks=255):
        latest_block_num = self.substrate.get_block_number(block_hash=self.substrate.block_hash)
        first_block_num = latest_block_num - num_blocks

        first_timestamp = self.substrate.query(
            module='Timestamp', 
            storage_function='Now', 
            block_hash=self.substrate.get_block_hash(first_block_num)
        ).value

        last_timestamp = self.substrate.query(
            module='Timestamp', 
            storage_function='Now', 
            block_hash=self.substrate.get_block_hash(latest_block_num)
        ).value

        return (last_timestamp - first_timestamp) / (num_blocks * 1000)

    def time_until_block(self, target_block: int) -> int:
        """
        Calculate the estimated time in minutes until the specified target block is reached on the Kusama network.

        Args:
            target_block (int): The target block number for which the remaining time needs to be calculated.

        Returns:
            int: The estimated time remaining in minutes until the target block is reached. If the target block has
            already been reached, the function will return None.

        Raises:
            Exception: If any error occurs while trying to calculate the time remaining until the target block.
        """
        try:
            # Get the current block number
            current_block = self.substrate.get_block_number(block_hash=self.substrate.block_hash)
            if target_block <= current_block:
                logging.info("The target block has already been reached.")
                return False

            # Calculate the difference in blocks
            block_difference = target_block - current_block

            # Get the average block time (6 seconds for Kusama)
            avg_block_time = self.get_average_block_time()

            # Calculate the remaining time in seconds
            remaining_time = block_difference * avg_block_time

            # Convert seconds to minutes
            minutes = remaining_time / 60

            return int(minutes)

        except Exception as error:
            logging.error( f"An error occurred while trying to calculate minute remaining until {target_block} is met... {error}")

    async def check_referendums(self):
        """
        Check the referendums and return any new referendums as a JSON string.

        The method retrieves the information about referendums using the `referendumInfoFor` method and
        caches the result using the `cache_difference` method from the `util` attribute of the `self` object.

        If there are any new referendums, the method retrieves the on-chain and polkassembly information about
        each new referendum and adds it to a dictionary. The dictionary is then returned as a JSON string.

        Returns:
            str: The new referendums as a JSON string or False if there are no new referendums.
        """
        new_referenda = {}

        referendum_info = self.referendumInfoFor()
        #self.db_handler.sync_ref_data(self.referendumInfoFor())
        results = self.util.get_cache_difference(filename='../data/governance.cache', data=referendum_info)
        self.util.save_data_to_cache(filename='../data/governance.cache', data=referendum_info)

        if results:
            for key, value in results.items():
                if 'added' in key:
                    for index in results['dictionary_item_added']:
                        index = index.strip('root').replace("['", "").replace("']", "")
                        onchain_info = referendum_info[index]['Ongoing']
                        polkassembly_info = await self.fetch_referendum_data(referendum_id=index, network=self.config.NETWORK_NAME)

                        new_referenda.update({
                            f"{index}": polkassembly_info
                        })

                        new_referenda[index]['onchain'] = onchain_info

            return new_referenda
        return False
