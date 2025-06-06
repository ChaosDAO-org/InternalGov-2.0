"""
This enables permissionless cleanup of expired votes in the Polkadot/Kusama governance system

When storage limits have been met, calls will fail with the following message: Maximum number of votes reached.
"""

from substrateinterface import SubstrateInterface, Keypair
from substrateinterface.exceptions import SubstrateRequestException
import json

WS_ENDPOINT = 'wss://polkadot.dotters.network'
YOUR_ADDRESS = '12pXignPnq8sZvPtEsC3RdhDLAscqzFQz97pX2tpiNp3xLqo'
MAX_REFERENDUM_INDEX = 1500  # only process referendums with index < 1500

# https://wiki.polkadot.network/learn/learn-polkadot-opengov-origins/
TRACK_IDS = [
    0,  # root
    1,  # whitelisted caller
    2,  # wish for change
    10, # staking admin
    11, # treasurer
    12, # lease admin
    13, # fellowship admin
    14, # general admin
    15, # auction admin
    20, # referendum canceller
    21, # referendum killer
    30, # small tipper
    31, # big tipper
    32, # small spender
    33, # medium spender
    34  # big spender
]

def find_all_votes(substrate, address):
    print(f"\nFinding all votes for address: {address}")
    print(f"Filter: Only processing referendums with index < {MAX_REFERENDUM_INDEX}")
    all_votes = []

    for track_id in TRACK_IDS:
        try:
            voting_for = substrate.query(
                module='ConvictionVoting',
                storage_function='VotingFor',
                params=[address, track_id]
            )

            if voting_for.value is None:
                continue

            if isinstance(voting_for.value, dict) and 'Casting' in voting_for.value:
                casting = voting_for.value['Casting']
                votes = casting.get('votes', [])

                if votes:
                    filtered_votes = [
                        vote for vote in votes
                        if vote[0] < MAX_REFERENDUM_INDEX
                    ]

                    if filtered_votes:
                        print(f"Track {track_id}: Found {len(filtered_votes)} vote(s) (filtered from {len(votes)} total)")

                        for ref_index, vote_data in filtered_votes:
                            vote_info = {
                                'track': track_id,
                                'referendum': ref_index,
                                'vote': vote_data
                            }

                            #print(f"  - Referendum #{vote_info['referendum']}: {json.dumps(vote_info['vote'])}")
                            all_votes.append(vote_info)
                    elif votes:
                        print(f"Track {track_id}: {len(votes)} vote(s) found but all filtered out (>= {MAX_REFERENDUM_INDEX})")

            elif isinstance(voting_for.value, dict) and 'Delegating' in voting_for.value:
                print(f"Track {track_id}: Currently delegating")

        except SubstrateRequestException as e:
            if "Invalid index" not in str(e):
                print(f"Error checking track {track_id}: {e}")
        except Exception as e:
            print(f"Unexpected error checking track {track_id}: {e}")

    return all_votes


def check_referendum_status(substrate, ref_index):
    try:
        ref_info = substrate.query(
            module='Referenda',
            storage_function='ReferendumInfoFor',
            params=[ref_index]
        )

        if ref_info.value is None:
            return {'exists': False, 'status': 'not_found'}

        info = ref_info.value

        if isinstance(info, dict):
            if 'Ongoing' in info:
                return {
                    'exists': True,
                    'status': 'ongoing',
                    'track': info['Ongoing'].get('track', 0)
                }
            elif 'Approved' in info:
                return {'exists': True, 'status': 'approved'}
            elif 'Rejected' in info:
                return {'exists': True, 'status': 'rejected'}
            elif 'Cancelled' in info:
                return {'exists': True, 'status': 'cancelled'}
            elif 'TimedOut' in info:
                return {'exists': True, 'status': 'timed_out'}
            elif 'Killed' in info:
                return {'exists': True, 'status': 'killed'}

        return {'exists': True, 'status': 'unknown'}

    except Exception as e:
        print(f"Error checking referendum {ref_index}: {e}")
        return {'exists': False, 'status': 'error'}


def main():
    try:
        print('Connecting to Polkadot network...')
        substrate = SubstrateInterface(url=WS_ENDPOINT)

        chain_name = substrate.rpc_request("system_chain", [])
        print(f"Connected to {chain_name['result']}")

        all_votes = find_all_votes(substrate, YOUR_ADDRESS)

        if not all_votes:
            print(f"\n✅ No active votes found for referendums < {MAX_REFERENDUM_INDEX}.")
            return

        print(f"\n📊 Total votes found (< {MAX_REFERENDUM_INDEX}): {len(all_votes)}")

        print('\nChecking each referendum status...')
        removable_votes = []

        for vote in all_votes:
            status = check_referendum_status(substrate, vote['referendum'])

            #print(f"Referendum #{vote['referendum']} (Track {vote['track']}): {status['status']}")

            if status['exists'] and status['status'] != 'ongoing':
                removable_votes.append(vote)

        if not removable_votes:
            print('\n✅ No votes eligible for removal at this time.')
            print('   (Votes can only be removed after referenda have ended)')
            return

        print(f"🗑️  {len(removable_votes)} vote(s) can be removed")

        # Create removeOtherVote calls
        calls = []
        for vote in removable_votes:
            call = substrate.compose_call(
                call_module='ConvictionVoting',
                call_function='remove_other_vote',
                call_params={
                    'target': YOUR_ADDRESS,
                    'class': vote['track'],
                    'index': vote['referendum']
                }
            )
            calls.append(call)

        print('\nCreating batch transaction...')

        if len(calls) == 1:
            batch_call = calls[0]
        else:
            # Use batch for multiple calls (continues even if some fail)
            # Note: Use batch_all if you want all-or-nothing behavior
            batch_call = substrate.compose_call(
                call_module='Utility',
                call_function='batch',
                call_params={
                    'calls': calls
                }
            )

        call_data = batch_call.data.to_hex()

        print('✅ Batch transaction created successfully!')
        print('📋 Call data for polkadot.js:\n')
        print('#' * 80)
        print(f"{call_data}")
        print('#' * 80)

        print('\n📝 Instructions:')
        print('1. Copy the call data above')
        print('2. Go to Polkadot.js Apps > Developer > Extrinsics')
        print('3. Toggle "Submission" to "Decode"')
        print('4. Paste the call data')
        print('5. Sign and submit the transaction')

        # keypair = Keypair.create_from_mnemonic('your mnemonic here')
        # extrinsic = substrate.create_signed_extrinsic(call=batch_call, keypair=keypair)
        # receipt = substrate.submit_extrinsic(extrinsic, wait_for_inclusion=True)
        # print(f"Extrinsic '{receipt.extrinsic_hash}' sent and included in block '{receipt.block_hash}'")

    except Exception as e:
        print(f'Error: {e}')
        raise


if __name__ == '__main__':
    main()