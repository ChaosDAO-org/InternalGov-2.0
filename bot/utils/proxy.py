from substrateinterface import SubstrateInterface, Keypair
from substrateinterface.exceptions import SubstrateRequestException
from utils.config import Config
from utils.logger import Logger
import asyncio


class ProxyVoter:
    """
    ProxyVoter Class to interact with a Substrate-based blockchain.

    Attributes:
        substrate (SubstrateInterface): The interface to the Substrate node.
        main_address (str): The main address for which the proxy is authorized.
        proxy_keypair (Keypair): Keypair object for the proxy.

    Usage:
        >>> voter = ProxyVoter(main_address="GqPcF8dFg8qYxccJt3FsZzg6tmq6iHgWK3v8gJdG7Se1QoY",
        >>>                       proxy_mnemonic="put your proxy account mnemonic here",
        >>>                       url="wss://kusama-rpc.polkadot.io")
        >>>
        >>> votes = [(259, "aye", "Locked1x"),
        >>>          (260, "aye", "Locked1x")]
        >>>
        >>> voter.execute_multiple_votes(votes)

    """

    def __init__(self, main_address, proxy_mnemonic, url):
        """
        Initialize the ProxyVoter instance.

        Args:
            main_address (str): The main address for which the proxy is authorized.
            proxy_mnemonic (str): The mnemonic phrase for generating the proxy's keypair.
            url (str): The URL of the Substrate node to connect to.
        """
        try:
            self.substrate = SubstrateInterface(
                url=url,
                auto_reconnect=True
            )

        except SubstrateRequestException as e:
            print(f"Failed to connect to Substrate node: {e}")
            return

        self.main_address = main_address
        self.proxy_keypair = Keypair.create_from_mnemonic(proxy_mnemonic)
        self.logger = Logger()
        self.config = Config()

    async def balance(self, ss58_address=None):
        """
        Query the free balance of the main address that the proxy controls if a ss58_address isn't provided.

        Returns:
            int: The free balance of the main address.
        """
        try:
            # When no ss58 address is provided, use self.main_address which is the account
            # that the governance proxy controls
            if not ss58_address:
                # When VOTE_WITH_BALANCE is set to 0, the bot will vote with the entire balance that the
                # governance proxy controls.
                if self.config.VOTE_WITH_BALANCE != 0:
                    return self.config.VOTE_WITH_BALANCE * (10 ** self.substrate.token_decimals)

                result = self.substrate.query('System', 'Account', [self.main_address])
                return result.value['data']['free']
            else:
                result = self.substrate.query('System', 'Account', [ss58_address])
                return result.value['data']['free']
        except SubstrateRequestException as e:
            print(f"Failed to query balance: {e}")
            return None

    async def proxy_balance(self):
        try:
            public_address = self.proxy_keypair.ss58_address
            proxy_balance = await self.balance(ss58_address=public_address) / float(self.config.TOKEN_DECIMAL)
            if isinstance(proxy_balance, float):
                return proxy_balance
            else:
                raise ValueError("Balance is not a float")
        except Exception as error:
            return None

    async def compose_democracy_vote_call(self, proposal_index, vote_type, conviction, ongoing_referendas):
        """
        Compose a democracy vote call.

        NOTE: This will check if the index being passed is an Ongoing referendum.
        If it's not; the call will not be composed.

        Args:
            proposal_index (int): The index of the proposal to vote on.
            vote_type (str): The type of the vote ('Aye' or 'Nay').
            conviction (str): The conviction for the vote.

        Returns:
            dict: The composed call for democracy voting.
        """
        try:

            # Prevent Failed（NotOngoing）- caused when voing on a referenda that is not ongoing.
            # ongoing ref
            if proposal_index not in ongoing_referendas:
                self.logger.info(f"{proposal_index}# is not an ongoing referenda, skipping...")
                return False

            main_account_balance = await self.balance(ss58_address=self.main_address) / self.substrate.token_decimals

            if self.config.VOTE_WITH_BALANCE != 0 and main_account_balance < self.config.VOTE_WITH_BALANCE:
                self.logger.info(f"The balance of {self.main_address} is too low")
                return False

            if vote_type == 'aye':
                return self.substrate.compose_call(
                    call_module="ConvictionVoting",
                    call_function="vote",
                    call_params={
                        "poll_index": proposal_index,
                        "vote": {
                            "Standard": {
                                "balance": int(await self.balance()),
                                "vote": {
                                    f"aye": True,
                                    "conviction": conviction
                                }
                            }
                        }
                    }
                )

            if vote_type == 'nay':
                return self.substrate.compose_call(
                    call_module="ConvictionVoting",
                    call_function="vote",
                    call_params={
                        "poll_index": proposal_index,
                        "vote": {
                            "Standard": {
                                "balance": int(await self.balance()),
                                "vote": {
                                    f"aye": False,
                                    "conviction": conviction
                                }
                            }
                        }
                    }
                )

            if vote_type == 'abstain':
                return self.substrate.compose_call(
                    call_module="ConvictionVoting",
                    call_function="vote",
                    call_params={
                        "poll_index": proposal_index,
                        "vote": {
                            "SplitAbstain": {
                                f"{vote_type}": int(await self.balance()),
                                "aye": 0,
                                "nay": 0
                            }
                        }
                    }
                )

        except SubstrateRequestException as e:
            print(f"Failed to compose democracy vote call: {e}")
            return None

    async def compose_utility_batch_call(self, calls):
        """
        Compose a utility batch call.

        Args:
            calls (list): A list of calls to batch together.

        Returns:
            dict: The composed batch call.
        """
        try:
            return self.substrate.compose_call(
                call_module="Utility",
                call_function="batch",
                call_params={"calls": calls}
            )
        except SubstrateRequestException as e:
            self.logger.exception(f"Failed to compose utility batch call: {e}")
            return None

    async def compose_proxy_call(self, batch_call):
        """
        Compose a proxy call.

        Args:
            batch_call (dict): The batch call to proxy.

        Returns:
            GenericCall: The composed proxy call.
        """
        try:
            return self.substrate.compose_call(
                call_module='Proxy',
                call_function='proxy',
                call_params={
                    'real': f'0x{self.substrate.ss58_decode(self.main_address)}',
                    'force_proxy_type': 'Governance',
                    'call': batch_call
                }
            )
        except SubstrateRequestException as e:
            self.logger.exception(f"Failed to compose proxy call: {e}")
            return None

    async def execute_calls(self, calls):
        """
        Execute a batch of calls.

        Args:
            calls (list): A list of calls to execute.
        """
        batch_call = await self.compose_utility_batch_call(calls)
        proxy_call = await self.compose_proxy_call(batch_call)
        extrinsic = self.substrate.create_signed_extrinsic(call=proxy_call, keypair=self.proxy_keypair)

        try:
            result = self.substrate.submit_extrinsic(extrinsic, wait_for_inclusion=True)
            if result.is_success:
                return result['extrinsic_hash']
            else:
                return False
        except Exception as e:
            self.logger.exception(f"Failed to send extrinsic: {e}")

    async def execute_multiple_votes(self, votes):
        """
        Execute multiple democracy votes.

        Args:
            votes (list): A list of tuples, each containing proposal index, vote type, and conviction.
        """
        try:
            vote_calls = []
            indexes = []

            ongoing_referendas = [int(index.value) for index, info in self.substrate.query_map(module='Referenda', storage_function='ReferendumInfoFor', params=[]) if 'Ongoing' in info]

            for i, (index, vote_type, conviction) in enumerate(votes):
                if vote_type not in ['aye', 'nay', 'abstain']:
                    self.logger.error(f"Incorrect vote_type at index {index}: {vote_type}")
                    continue

                democracy_call = await self.compose_democracy_vote_call(index, vote_type, conviction, ongoing_referendas)
                if democracy_call:
                    vote_calls.append(democracy_call)
                    indexes.append(str(index))
                    await asyncio.sleep(0.5)
                else:
                    continue

            if len(vote_calls) > 0:
                extrinsic = await self.execute_calls(vote_calls)

                if extrinsic:
                    self.logger.info(f"An on-chain vote has been cast: {extrinsic}")
                    return indexes, vote_calls, extrinsic
                else:
                    self.logger.error("vote(s) were not successful")
            else:
                self.logger.warning("vote_calls variable was empty, no vote(s) casted.")
                return False, False, False
        except SubstrateRequestException as e:
            self.logger.exception(f"Failed to execute multiple votes: {e}")
        finally:
            self.substrate.close()
