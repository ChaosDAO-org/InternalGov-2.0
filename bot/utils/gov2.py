import asyncio
import aiohttp
import logging
from utils.data_processing import CacheManager


class OpenGovernance2:
    def __init__(self, config, substrate=None):
        self.config = config
        self.util = CacheManager
        self.substrate = substrate


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
            f"https://{network}-api.subsquare.io/gov2/referendums/{referendum_id}",
        ]

        headers = {"x-network": network}
        successful_response = None
        successful_url = None

        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    # Make the request separately and use async with for the response
                    response = await asyncio.wait_for(session.get(url, headers=headers), timeout=60)

                    async with response:
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

                except asyncio.TimeoutError:
                    logging.error(f"Request to {url} timed out.")
                except aiohttp.ClientResponseError as http_error:
                    logging.error(f"HTTP exception occurred while accessing {url}: {http_error}")
                    logging.error(f"Retrying on {urls[1]}")

        if successful_response is None:
            return {"title": "None",
                    "content": "Unable to retrieve details from both sources",
                    "successful_url": None}
        else:
            successful_response["successful_url"] = successful_url
            return successful_response

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
        new_referendums = {}
        total_found = 0

        try:
            referendum_info_for = await self.substrate.referendumInfoFor()

            results = self.util.get_cache_difference(filename='../data/governance.cache', data=referendum_info_for)

            if results:
                for key, value in results.items():
                    if 'added' in key:
                        for index in results['dictionary_item_added']:
                            total_found = total_found + 1
                            index = index.strip('root').replace("['", "").replace("']", "")
                            onchain_info = referendum_info_for[index]['Ongoing']
                            governance_platform = await self.fetch_referendum_data(referendum_id=index, network=self.config.NETWORK_NAME)

                            new_referendums.update({
                                f"{index}": governance_platform
                            })

                            new_referendums[index]['onchain'] = onchain_info

                if total_found > 0:
                    self.util.save_data_to_cache(filename='../data/governance.cache', data=referendum_info_for)

                return new_referendums, referendum_info_for
            return False, None
        except Exception as e:
            logging.error(f"Error checking referendums: {e}")
            return False, None
