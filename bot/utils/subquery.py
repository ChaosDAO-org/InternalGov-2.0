from substrateinterface import SubstrateInterface
from substrateinterface.exceptions import SubstrateRequestException, ConfigurationError
from websocket._exceptions import WebSocketBadStatusException
from utils.config import Config
from utils.logger import Logger
import asyncio
import json


class SubstrateAPI:
    def __init__(self):
        self.config = Config()
        self.logger = Logger()

    async def _connect(self):
        max_retries = 3
        wait_seconds = 10

        for attempt in range(1, max_retries + 1):
            try:
                self.logger.info("Creating a new Substrate connection")
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

    async def get_display_name(self, address: str) -> str:
        # Fetch the identity info associated with the given address.
        substrate = await self._connect()

        try:
            identity_info = await self._run_in_executor(
                substrate.query,
                module='Identity',
                storage_function='IdentityOf',
                params=[address]
            )

            if identity_info is None or identity_info.value is None or 'info' not in identity_info.value:
                return None

            display_name_data = identity_info.value['info']['display']
            if 'Raw' in display_name_data:
                return display_name_data['Raw']  # if retrieving Raw is non-blocking
            else:
                # Handle other types of Data encoding if needed
                return None

        finally:
            substrate.close()  # Consider if this needs to be awaited or run in the executor, and modify accordingly

    async def get_identity_or_super_identity(self, address: str) -> dict:
        substrate = await self._connect()

        try:
            identity_info = await self._run_in_executor(
                substrate.query,
                module='Identity',
                storage_function='IdentityOf',
                params=[address]
            )

            if identity_info and identity_info.value and 'info' in identity_info.value:
                return identity_info.value['info']

            super_info = await self._run_in_executor(
                substrate.query,
                module='Identity',
                storage_function='SuperOf',
                params=[address]
            )

            if super_info and super_info.value:
                super_address = super_info.value[0]
                super_identity_info = await self._run_in_executor(
                    substrate.query,
                    module='Identity',
                    storage_function='IdentityOf',
                    params=[super_address]
                )

                if super_identity_info and super_identity_info.value and 'info' in super_identity_info.value:
                    return super_identity_info.value['info']

            return None

        finally:
            substrate.close()  # Consider

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
