from substrateinterface import SubstrateInterface, Keypair
from substrateinterface.exceptions import SubstrateRequestException


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
                url=url
            )
        except SubstrateRequestException as e:
            print(f"Failed to connect to Substrate node: {e}")
            return

        self.main_address = main_address
        self.proxy_keypair = Keypair.create_from_mnemonic(proxy_mnemonic)

    def balance(self):
        """
        Query the free balance of the main address.

        Returns:
            int: The free balance of the main address.
        """
        try:
            result = self.substrate.query('System', 'Account', [self.main_address])
            return result.value['data']['free']
        except SubstrateRequestException as e:
            print(f"Failed to query balance: {e}")
            return None

    def compose_democracy_vote_call(self, proposal_index, vote_type, conviction):
        """
        Compose a democracy vote call.

        Args:
            proposal_index (int): The index of the proposal to vote on.
            vote_type (str): The type of the vote ('Aye' or 'Nay').
            conviction (str): The conviction for the vote.

        Returns:
            dict: The composed call for democracy voting.
        """
        try:
            if vote_type != 'abstain':
                return self.substrate.compose_call(
                    call_module="ConvictionVoting",
                    call_function="vote",
                    call_params={
                        "poll_index": proposal_index,
                        "vote": {
                            "Standard": {
                                "balance": int(self.balance()),
                                "vote": {
                                    f"{vote_type}": True,
                                    "conviction": conviction
                                }
                            }
                        }
                    }
                )
            else:
                return self.substrate.compose_call(
                    call_module="ConvictionVoting",
                    call_function="vote",
                    call_params={
                        "poll_index": proposal_index,
                        "vote": {
                            "SplitAbstain": {
                                f"{vote_type}": int(self.balance()),
                                "aye": 0,
                                "nay": 0
                            }
                        }
                    }
                )

        except SubstrateRequestException as e:
            print(f"Failed to compose democracy vote call: {e}")
            return None

    def compose_utility_batch_call(self, calls):
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
            print(f"Failed to compose utility batch call: {e}")
            return None

    def compose_proxy_call(self, batch_call):
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
            print(f"Failed to compose proxy call: {e}")
            return None

    def execute_calls(self, calls):
        """
        Execute a batch of calls.

        Args:
            calls (list): A list of calls to execute.
        """
        batch_call = self.compose_utility_batch_call(calls)
        proxy_call = self.compose_proxy_call(batch_call)
        extrinsic = self.substrate.create_signed_extrinsic(call=proxy_call, keypair=self.proxy_keypair)

        try:
            result = self.substrate.submit_extrinsic(extrinsic, wait_for_inclusion=True)
            print(f"Extrinsic {result['extrinsic_hash']} sent and included in block {result['block_hash']}")
        except Exception as e:
            print(f"Failed to send extrinsic: {e}")

    def execute_multiple_votes(self, votes):
        """
        Execute multiple democracy votes.

        Args:
            votes (list): A list of tuples, each containing proposal index, vote type, and conviction.
        """
        try:
            vote_calls = [self.compose_democracy_vote_call(index, vote_type, conviction) for index, vote_type, conviction in votes]
            self.execute_calls(vote_calls)
        except SubstrateRequestException as e:
            print(f"Failed to execute multiple votes: {e}")
