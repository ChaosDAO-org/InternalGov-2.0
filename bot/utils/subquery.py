import os
import json
import time
import asyncio
from utils.logger import Logger
from scalecodec.base import ScaleBytes
from substrateinterface import SubstrateInterface
from websocket._exceptions import WebSocketBadStatusException
from substrateinterface.exceptions import SubstrateRequestException, ConfigurationError


class SubstrateAPI:
    def __init__(self, config):
        self.config = config
        self.logger = Logger()
        self.substrate = None

    async def _connect(self, wss):
        if not self.substrate:
            max_retries = 3
            wait_seconds = 10

            self.logger.info(f"Initializing RPC connection to {wss}")

            for attempt in range(1, max_retries + 1):
                try:
                    await asyncio.sleep(0.5)
                    self.substrate = SubstrateInterface(url=wss)

                    await asyncio.wait_for(
                        asyncio.to_thread(self.substrate.init_runtime),
                        timeout=15
                    )

                    self.logger.info(f"Runtime successfully initialized: {self.substrate.runtime_version}")
                    return self.substrate
                except (WebSocketBadStatusException, SubstrateRequestException, ConfigurationError) as e:
                    self.logger.error(f"Error during connection attempt {attempt}: {e}")
                    if attempt < max_retries:
                        self.logger.info(f"Retrying in {wait_seconds} seconds... (Attempt {attempt}/{max_retries})")
                        await asyncio.sleep(wait_seconds)
                    else:
                        self.logger.error("Max retries reached. Could not establish a connection.")
                        raise e
                except asyncio.TimeoutError:
                    self.logger.error("Timeout while initializing Substrate connection.")
                    raise
                except Exception as error:
                    self.logger.error(f"Unexpected error occurred during Substrate connection: {error}")
                    raise

    async def _disconnect(self):
        """Disconnects from the Substrate node."""
        if self.substrate:
            self.logger.info("Disconnecting from Substrate node...")
            self.substrate.close()
            self.substrate = None

    async def close(self):
        """Manually close the connection when done with queries."""
        await self._disconnect()

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

    async def ongoing_referendums_idx(self):
        try:
            await self._connect(self.config.SUBSTRATE_WSS)

            qmap = await asyncio.wait_for(
                asyncio.to_thread(
                    self.substrate.query_map,
                    module='Referenda',
                    storage_function='ReferendumInfoFor',
                    params=[]
                ),
                timeout=15
            )

            ongoing_referendums = [int(index.value) for index, info in qmap if 'Ongoing' in info]
            return ongoing_referendums

        except asyncio.TimeoutError:
            self.logger.error("Timeout while fetching ongoing referendums.")
            raise

        except Exception as e:
            self.logger.error(f"Error fetching ongoing referendum indexes: {e}")
            raise

    async def referendumInfoFor(self, index=None):
        """
        Get information regarding a specific referendum or all ongoing referendums.

        :param index: (optional) index of the specific referendum
        :return: dictionary containing the information of the specific referendum or a dictionary of all ongoing referendums
        :raises: ValueError if `index` is not None and not a valid index of any referendum
        """
        referendum = {}

        await self._connect(self.config.SUBSTRATE_WSS)
        try:
            if index is not None:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.substrate.query,
                        module='Referenda',
                        storage_function='ReferendumInfoFor',
                        params=[index]
                    ),
                    timeout=15
                )
                return result.serialize()
            else:
                qmap = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.substrate.query_map,
                        module='Referenda',
                        storage_function='ReferendumInfoFor',
                        params=[]
                    ),
                    timeout=15
                )
                for index, info in qmap:
                    if 'Ongoing' in info:
                        referendum.update({int(index.value): info.value})

                sort = json.dumps(referendum, sort_keys=True)
                data = json.loads(sort)
                return data

        except asyncio.TimeoutError:
            self.logger.error("Timeout while fetching referendum info.")
            raise

        except Exception as e:
            self.logger.error(f"Error fetching referendum info: {e}")
            raise e

    async def check_ss58_address(self, address) -> bool:
        try:
            await self._connect(wss=self.config.SUBSTRATE_WSS)
            if not isinstance(address, str):
                return False
            try:
                if self.substrate.is_valid_ss58_address(value=address):
                    return True
                else:
                    return False
            except (SubstrateRequestException, ValueError):
                return False

        except Exception as e:
            self.logger.error(f"Error checking ss58 address: {e}")
            raise e

    async def referendum_call_data(self, index: int, gov1: bool, call_data: bool):
        """
        Retrieves and decodes the referendum call data based on given parameters.

        Args:
            index (int): The index of the referendum to query.
            gov1 (bool): Determines which module to query ('Democracy' if True, 'Referenda' if False).
            call_data (bool): Determines the type of data to return (raw call data if True, decoded call data if False).

        Returns:
            tuple: A tuple containing a boolean indicating success or failure, and the decoded call data or error message.

        Raises:
            Exception: If an error occurs during the retrieval or decoding process.
        """

        try:
            await self._connect(wss=self.config.SUBSTRATE_WSS)
            referendum = await asyncio.wait_for(
                asyncio.to_thread(
                    self.substrate.query,
                    module="Democracy" if gov1 else "Referenda",
                    storage_function="ReferendumInfoOf" if gov1 else "ReferendumInfoFor",
                    params=[index]
                ),
                timeout=15
            )

            referendum = referendum.serialize()

            if referendum is None or 'Ongoing' not in referendum:
                return False, f":warning: Referendum **#{index}** is inactive"

            preimage = referendum['Ongoing']['proposal']

            if 'Inline' in preimage:
                call = preimage['Inline']
                if not call_data:
                    decoded_call = await asyncio.wait_for(
                        asyncio.to_thread(self.substrate.create_scale_object('Call').decode, ScaleBytes(call)),
                        timeout=15
                    )
                    return decoded_call, preimage
                else:
                    return call

            if 'Lookup' in preimage:
                preimage_hash = preimage['Lookup']['hash']
                preimage_length = preimage['Lookup']['len']
                call = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.substrate.query,
                        module='Preimage',
                        storage_function='PreimageFor',
                        params=[(preimage_hash, preimage_length)]
                    ),
                    timeout=15
                )

                call = call.value

                if call is None:
                    return False, ":warning: Preimage not found on chain"

                if not call.isprintable():
                    call = f"0x{''.join(f'{ord(c):02x}' for c in call)}"

                if not call_data:
                    decoded_call = await asyncio.wait_for(
                        asyncio.to_thread(self.substrate.create_scale_object('Call').decode, ScaleBytes(call)),
                        timeout=15
                    )
                    return decoded_call, preimage_hash
                else:
                    return call

        except asyncio.TimeoutError:
            self.logger.error(f"Timeout while fetching referendum call data for index: {index}")
            raise

        except Exception as e:
            self.logger.error(f"Error fetching referendum call data: {e}")
            raise e

    """
    Cache Super_of
    """

    async def cache_super_of(self, network):
        """
        :param network::
        :return: The super-identity of an alternative 'sub' identity together with its name, within that
        """
        try:
            if not self.config.PEOPLE_WSS:
                await self._connect(wss=self.config.SUBSTRATE_WSS)

            if self.config.PEOPLE_WSS:
                await self._disconnect()  # disconnect before connecting to switch from SUBSTRATE_WSS to PEOPLE_WSS
                await self._connect(wss=self.config.PEOPLE_WSS)

            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self.substrate.query_map,
                    module='Identity',
                    storage_function='SuperOf',
                    params=[]
                ),
                timeout=15
            )

            result_tmp = {}
            for key, values in result:
                result_tmp.update({key.value: values.value})

            with open(f'../data/off-chain-querying/{network}-superof.json', 'w') as superof:
                json.dump(result_tmp, indent=4, fp=superof)

        except asyncio.TimeoutError:
            self.logger.error("Timeout while fetching identities super_of.")
            raise

        except Exception as e:
            self.logger.error(f"Error fetching identities super_of: {e}")
            raise

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

        try:
            if not self.config.PEOPLE_WSS:
                await self._connect(wss=self.config.SUBSTRATE_WSS)

            if self.config.PEOPLE_WSS:
                await self._disconnect()  # Disconnect before connecting to switch from SUBSTRATE_WSS to PEOPLE_WSS
                await self._connect(wss=self.config.PEOPLE_WSS)

            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self.substrate.query_map,
                    module='Identity',
                    storage_function='IdentityOf',
                    params=[]
                ),
                timeout=15
            )

            result_tmp = {}
            for key, values in result:
                result_tmp.update({key.value: values.value})

            with open(f'../data/off-chain-querying/{network}-identity.json', 'w') as identityof:
                json.dump(result_tmp, indent=4, fp=identityof)

        except asyncio.TimeoutError:
            self.logger.error("Timeout while fetching identities.")
            raise

        except Exception as e:
            self.logger.error(f"Error fetching identities: {e}")
            raise

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
                return address

        display, twitter = None, None

        if isinstance(result, dict):
            display = result['info']['display']
            twitter = result['info']['twitter']
        elif isinstance(result, list):
            display = result[0]['info']['display']
            twitter = result[0]['info']['twitter']

        # Get the 'Raw' value from display, default to empty string if not present
        display_name = display.get('Raw', '')

        # Get the 'Raw' value from twitter, default to empty string if not present
        twitter_name = twitter.get('Raw', '').replace("https://", "").replace("http://", "").replace("www.", "").split('/')[-1]
        twitter_name = f"@{twitter_name}" if not twitter_name.startswith('@') else twitter_name

        if display_name and twitter_name:
            return f"{display_name} / {twitter_name}"
        elif display_name:
            return display_name
        elif twitter_name:
            return twitter_name
        else:
            return address

    async def get_average_block_time(self, num_blocks=255):
        try:
            await self._connect(wss=self.config.SUBSTRATE_WSS)

            latest_block_num = await asyncio.wait_for(
                asyncio.to_thread(self.substrate.get_block_number, block_hash=self.substrate.block_hash),
                timeout=15
            )

            first_block_num = latest_block_num - num_blocks

            first_timestamp = await asyncio.wait_for(
                asyncio.to_thread(
                    self.substrate.query,
                    module='Timestamp',
                    storage_function='Now',
                    block_hash=self.substrate.get_block_hash(first_block_num)
                ),
                timeout=15
            )

            last_timestamp = await asyncio.wait_for(
                asyncio.to_thread(
                    self.substrate.query,
                    module='Timestamp',
                    storage_function='Now',
                    block_hash=self.substrate.get_block_hash(latest_block_num)
                ),
                timeout=15
            )

            # Calculate average block time
            return (last_timestamp.value - first_timestamp.value) / (num_blocks * 1000)

        except asyncio.TimeoutError:
            self.logger.error("Timeout while fetching block data for average block time.")
            raise

        except Exception as e:
            self.logger.error(f"Error fetching average block time: {e}")
            raise

    async def time_until_block(self, target_block: int) -> int:
        """
        Calculate the estimated time in minutes until the specified target block is reached on the substrate network.

        Args:
            target_block (int): The target block number for which the remaining time needs to be calculated.

        Returns:
            int: The estimated time remaining in minutes until the target block is reached. If the target block has
            already been reached, the function will return None.

        Raises:
            Exception: If any error occurs while trying to calculate the time remaining until the target block.
        """
        try:
            await self._connect(wss=self.config.SUBSTRATE_WSS)

            # Get the current block number
            current_block = self.substrate.get_block_number(block_hash=self.substrate.block_hash)
            if target_block <= current_block:
                self.logger.info("The target block has already been reached.")
                return False

            # Calculate the difference in blocks
            block_difference = target_block - current_block

            # Get the average block time
            avg_block_time = self.get_average_block_time()

            # Calculate the remaining time in seconds
            remaining_time = block_difference * avg_block_time

            # Convert seconds to minutes
            minutes = remaining_time / 60

            return int(minutes)

        except Exception as e:
            self.logger.error(f"Error fetching time_until_block: {e}")
            raise e

    async def get_block_epoch(self, block_number: int) -> int:
        """
        Retrieves the timestamp (epoch) of a specific block.

        Args:
            block_number (int): The block number for which the epoch (timestamp) is to be retrieved.

        Returns:
            int: The timestamp (epoch) of the specified block in milliseconds.

        Raises:
            asyncio.TimeoutError: If the operation exceeds the specified timeout limit.
            Exception: If an error occurs while fetching the block hash or timestamp.
        """
        try:
            await self._connect(wss=self.config.SUBSTRATE_WSS)

            block_hash = await asyncio.wait_for(
                asyncio.to_thread(self.substrate.get_block_hash, block_id=block_number),
                timeout=15
            )

            epoch = await asyncio.wait_for(
                asyncio.to_thread(
                    self.substrate.query,
                    module='Timestamp',
                    storage_function='Now',
                    block_hash=block_hash
                ),
                timeout=15
            )

            return epoch.value

        except asyncio.TimeoutError:
            self.logger.error("Timeout while fetching block epoch.")
            raise

        except Exception as e:
            self.logger.error(f"Error fetching block epoch: {e}")
            raise

