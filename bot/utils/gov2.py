import yaml
import json
import requests
from typing import Union, Any
from utils.data_processing import CacheManager
from substrateinterface import SubstrateInterface

with open("../config.yaml", "r") as file:
    config = yaml.safe_load(file)


class OpenGovernance2:
    def __init__(self):
        self.util = CacheManager
        self.substrate = SubstrateInterface(
            url=config['substrate_wss'],
            ss58_format=2,
            type_registry_preset='kusama'
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

    @staticmethod
    def fetch_referendum_data(referendum_id: int, network: str) -> Union[str, Any]:
        """
        Fetches referendum data from multiple sources and returns the JSON response containing
        a non-empty title if found. If no response with a non-empty title is found, it returns
        the first successful response or a default response with a title of "None" if neither
        URL is successful.

        Args:
            referendum_id (int): The ID of the referendum to fetch data for.
            network (str): The network to use for the request (e.g. "polkadot" or "kusama").

        Returns:
            Union[str, Any]: A JSON response containing referendum data with a non-empty title,
                             the first successful response, or a default response with a title
                             of "None" if neither URL is successful.
        """
        urls = [
            f"https://api.polkassembly.io/api/v1/posts/on-chain-post?postId={referendum_id}&proposalType=referendums_v2",
            f"https://kusama.subsquare.io/api/gov2/referendums/{referendum_id}",
        ]

        headers = {"x-network": network}
        successful_response = None

        for url in urls:
            try:
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                json_response = response.json()

                if "title" not in json_response.keys():
                    json_response["title"] = "None"

                if json_response["title"] is None:
                    return {"title": "None",
                            "content": "Unable to retrieve details from both sources"}

                if successful_response is None:
                    successful_response = json_response

            except requests.exceptions.HTTPError as e:
                print(f"HTTPError for {url}: {e}")

        if successful_response is not None and successful_response["title"] == "None":
            return {"title": "None",
                    "content": "Unable to retrieve details from both sources"}
        else:
            return successful_response

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
                print("The target block has already been reached.")
                return False

            # Calculate the difference in blocks
            block_difference = target_block - current_block

            # Get the average block time (6 seconds for Kusama)
            avg_block_time = 6

            # Calculate the remaining time in seconds
            remaining_time = block_difference * avg_block_time

            # Convert seconds to minutes
            minutes = remaining_time / 60

            return int(minutes)

        except Exception as error:
            print( f"An error occurred while trying to calculate minute remaining until {target_block} is met... {error}")

    def check_referendums(self):
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
        results = self.util.get_cache_difference(filename='../data/governance.cache', data=referendum_info)
        self.util.save_data_to_cache(filename='../data/governance.cache', data=referendum_info)

        if results:
            for key, value in results.items():
                if 'added' in key:
                    for index in results['dictionary_item_added']:
                        index = index.strip('root').replace("['", "").replace("']", "")
                        onchain_info = referendum_info[index]['Ongoing']
                        polkassembly_info = self.fetch_referendum_data(referendum_id=index, network=config['network'])

                        new_referenda.update({
                            f"{index}": polkassembly_info
                        })

                        new_referenda[index]['onchain'] = onchain_info

            return new_referenda
        return False
