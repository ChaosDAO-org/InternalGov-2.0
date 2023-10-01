from substrateinterface import SubstrateInterface
from substrateinterface.exceptions import SubstrateRequestException, ConfigurationError
from websocket._exceptions import WebSocketBadStatusException
from utils.logger import Logger
import asyncio
import json
import time
import os


class SubstrateAPI:
    def __init__(self, config):
        self.config = config
        self.logger = Logger()

    async def _connect(self):
        max_retries = 3
        wait_seconds = 30

        for attempt in range(1, max_retries + 1):
            try:
                self.logger.info("Creating a new Substrate connection")
                await asyncio.sleep(0.5)
                return SubstrateInterface(
                    url=self.config.SUBSTRATE_WSS,
                    type_registry_preset=self.config.NETWORK_NAME
                )

            except WebSocketBadStatusException as ws_error:
                self.logger.exception(f"WebSocket error occurred while making a request to Substrate: {ws_error.args}")
                print(f"WebSocket error occurred while making a request to Substrate: {ws_error.args}")

                if attempt < max_retries:  # If the current attempt is less than max_retries.
                    self.logger.info(f"Retrying in {wait_seconds} seconds... (Attempt {attempt}/{max_retries})")
                    print(f"Retrying in {wait_seconds} seconds... (Attempt {attempt}/{max_retries})")
                    await asyncio.sleep(wait_seconds)
                else:  # If we reached max_retries and couldn't establish a connection.
                    self.logger.error("Max retries reached. Could not establish a connection.")
                    print("Max retries reached. Could not establish a connection.")
                    raise

            except SubstrateRequestException as req_error:
                self.logger.exception(f"An error occurred while making a request to Substrate: {req_error.args}")
                print(f"An error occurred while making a request to Substrate: {req_error.args}")
                raise

            except ConfigurationError as config_error:
                self.logger.exception(f"Config error: {config_error.args}")
                print(f"Config error: {config_error.args}")
                raise

            except Exception as error:
                self.logger.exception(f"An error occurred while initializing the Substrate connection: {error.args}")
                print(f"An error occurred while initializing the Substrate connection: {error.args}")
                raise

    @staticmethod
    def cache_older_than_24hrs(file_path):
        """Check if a file is older than 24 hours."""
        try:
            # Get the time the file was last modified
            file_modification_time = os.path.getmtime(file_path)
            current_time = time.time()
            # Compare the file's modification time to the current time
            return current_time - file_modification_time > 24 * 3600
        except FileNotFoundError:
            return True

    async def _run_in_executor(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    async def referendumInfoFor(self, index=None):
        """
        Get information regarding a specific referendum or all ongoing referendums.

        :param index: (optional) index of the specific referendum
        :return: dictionary containing the information of the specific referendum or a dictionary of all ongoing referendums
        :raises: ValueError if `index` is not None and not a valid index of any referendum
        """
        substrate = await self._connect()
        referendum = {}

        try:
            if index is not None:
                data = await self._run_in_executor(substrate.query, module='Referenda', storage_function='ReferendumInfoFor', params=[index])
                return data.serialize()  # Make sure this is not a blocking call, if it is, run it in the executor.
            else:
                qmap_generator = await self._run_in_executor(substrate.query_map, module='Referenda', storage_function='ReferendumInfoFor', params=[])

                for index, info in qmap_generator:
                    if 'Ongoing' in info:
                        referendum.update({int(index.value): info.value})

                sorted_json = json.dumps(referendum, sort_keys=True)
                data = json.loads(sorted_json)
                return data

        finally:
            substrate.close()  # Consider if this needs to be awaited or run in the executor, and modify accordingly.

    async def is_valid_ss58_address(self, address) -> bool:
        substrate = await self._connect()

        try:
            if not isinstance(address, str):
                return False

            try:
                await self._run_in_executor(substrate.ss58_decode, address)
                return True
            except (SubstrateRequestException, ValueError):
                return False

        finally:
            substrate.close()

    """
    Cache Super_of
    """

    async def cache_super_of(self, network):
        """
        :param network::
        :return: The super-identity of an alternative 'sub' identity together with its name, within that
        """
        substrate = await self._connect()
        result_tmp = {}
        result = substrate.query_map(
            module='Identity',
            storage_function='SuperOf',
            params=[])
        substrate.close()

        for key, values in result:
            result_tmp.update({key.value: values.value})

        with open(f'../data/off-chain-querying/{network}-superof.json', 'w') as superof:
            json.dump(result_tmp, indent=4, fp=superof)

    @staticmethod
    async def check_cached_super_of(address, network):
        with open(f'../data/off-chain-querying/{network}-superof.json', 'r') as superof:
            data = json.load(superof)
            return data.get(address, None)

    async def check_super_of(self, address, network):
        """
        :param address:
        :param network:
        :return: The super-identity of an alternative 'sub' identity together with its name, within that
        """

        if self.cache_older_than_24hrs(f'../data/off-chain-querying/{network}-superof.json'):
            await self.cache_super_of(network=network)

        result = await self.check_cached_super_of(address=address, network=network)

        if result is not None:
            return result[0]
        else:
            return 0

    """
    Cache identityOf
    """

    async def cache_identities(self, network):
        """
        Fetches identities from the 'Identity' module using the 'IdentityOf' storage function,
        and stores the results in a JSON file.

        This function queries the 'Identity' module for identities, and then iterates over the results,
        storing each identity in a temporary dictionary. The dictionary keys are the identity keys,
        and the values are the corresponding identity values.

        After all identities have been stored in the dictionary, the function writes the dictionary
        to a JSON file named 'identity.json'. The JSON file is formatted with an indentation of 4 spaces.

        Raises:
            IOError: If the function cannot write to 'identity.json'.
            JSONDecodeError: If the function cannot serialize the dictionary to JSON.
        """

        substrate = await self._connect()
        result_tmp = {}
        result = substrate.query_map(
            module='Identity',
            storage_function='IdentityOf',
            params=[]
        )
        substrate.close()

        for key, values in result:
            result_tmp.update({key.value: values.value})

        with open(f'../data/off-chain-querying/{network}-identity.json', 'w') as identityof:
            json.dump(result_tmp, indent=4, fp=identityof)

    @staticmethod
    async def check_cached_identity(address, network):
        with open(f'../data/off-chain-querying/{network}-identity.json', 'r') as identityof:
            data = json.load(identityof)
            return data.get(address, None)

    async def check_identity(self, address: str, network: str) -> str:
        """
        :param address:
        :param network:
        :return: Information that is pertinent to identify the entity behind an account.
        """
        if self.cache_older_than_24hrs(f'../data/off-chain-querying/{network}-identity.json'):
            await self.cache_identities(network=network)

        result = await self.check_cached_identity(address=address, network=network)
        if result is None:
            super_of = await self.check_super_of(address=address, network=network)

            if super_of:
                result = await self.check_cached_identity(address=super_of, network=network)
            else:
                return 'N/A'

        display = result['info']['display']
        twitter = result['info']['twitter']

        display_name = display.get('Raw', '')  # Get the 'Raw' value from display, default to empty string if not present
        twitter_name = twitter.get('Raw', '')  # Get the 'Raw' value from twitter, default to empty string if not present

        if display_name and twitter_name:
            return f"{display_name} / {twitter_name}"
        elif display_name:
            return display_name
        elif twitter_name:
            return twitter_name
        else:
            return address
