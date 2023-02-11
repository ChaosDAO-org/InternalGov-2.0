import asyncio

from subalert.base import Utils, SubQuery
from subalert.config import Configuration
from subalert.subq import Queue

queue = Queue()


class Governance:
    def __init__(self):
        self.config = Configuration()
        self.utils = Utils()
        self.subquery = SubQuery()
        self.substrate = self.config.substrate
        self.hashtag = str(self.config.yaml_file['twitter']['hashtag'])
        self.loop = asyncio.get_event_loop()

    def check_referendum_changes(self):
        """
        :return: check if referenda data has changed since last running the command. Return False if no changes found.
        """
        referendum_info = self.subquery.referendum_info()
        result = self.utils.cache_difference(filename='data-cache/referenda.cache', data=referendum_info)
        if result:
            for key, value in result.items():

                if key == 'dictionary_item_added':
                    for index in result['dictionary_item_added']:
                        deepdiff_parsed_index = index.strip('root').replace("['", "").replace("']", "")
                        if not referendum_info[deepdiff_parsed_index].get('new_proposal'):
                            referendum_info[deepdiff_parsed_index].update({
                                'new_proposal': True
                            })

                if key == 'values_changed':
                    for obj, attributes in result['values_changed'].items():
                        deepdiff_parsed = obj.strip('root').replace("['", "").replace("']", "/").split('/')
                        updated_key = deepdiff_parsed[int(len(deepdiff_parsed)) - 2]
                        index = deepdiff_parsed[0]
                        if not referendum_info[index].get('values_changed'):
                            referendum_info[index][key] = {}

                        referendum_info[index][key].update({
                            updated_key: attributes
                        })

            return referendum_info
        return False

    def process(self):
        proposal_construct = {"proposals": []}
        referendum_info = self.subquery.referendum_info()
        referendum_change = self.check_referendum_changes()

        if referendum_change:
            for index, items in referendum_change.items():
                if 'values_changed' in items:
                    change = 'Change(s) since last tweet\n'
                    for changed_key in items['values_changed'].keys():
                        end = items['Ongoing']['end']
                        hash = items['Ongoing']['proposal_hash']
                        threshold = items['Ongoing']['threshold']
                        turnout = items['Ongoing']['tally'][changed_key] / 10 ** self.substrate.token_decimals
                        ayes = items['Ongoing']['tally']['ayes'] / 10 ** self.substrate.token_decimals
                        nays = items['Ongoing']['tally']['nays'] / 10 ** self.substrate.token_decimals

                        old_value = items['values_changed'][changed_key]['old_value'] / 10 ** self.substrate.token_decimals
                        new_value = items['values_changed'][changed_key]['new_value'] / 10 ** self.substrate.token_decimals

                        if new_value > old_value:
                            change_difference = f"{new_value - old_value:,.2f}"
                            change += f"⬆️{changed_key}: {change_difference}\n"

                        if new_value < old_value:
                            change_difference = int(old_value - new_value)
                            if float(change_difference) <= 0:
                                change += f"➡️{changed_key}: {change_difference}\n"
                            else:
                                change += f"⬇️{changed_key}: {change_difference:,.2f}\n"


                    tweet = (f"📜Referendum #{index} is ongoing on #{self.hashtag}.\n\n"
                             f"{change}\n"
                             f"⏲️Ends: {end}\n"
                             f"ℹ️Threshold: {threshold}\n"
                             f"🗳️Turnout: {turnout:,.2f}\n"
                             f"✅AYE: {ayes:,.2f} - ❌NAY: {nays:,.2f}\n\n"
                             f"https://{self.hashtag.lower()}.polkassembly.io/referendum/{index}")
                    proposal_construct['proposals'].append(tweet)

                if 'new_proposal' in items:
                    end = items['Ongoing']['end']
                    hash = items['Ongoing']['proposal_hash']
                    threshold = items['Ongoing']['threshold']
                    turnout = items['Ongoing']['tally']['turnout'] / 10 ** self.substrate.token_decimals
                    ayes = items['Ongoing']['tally']['ayes'] / 10 ** self.substrate.token_decimals
                    nays = items['Ongoing']['tally']['nays'] / 10 ** self.substrate.token_decimals

                    tweet = (f"📜New referendum #{index} found on #{self.hashtag}.\n\n"
                             f"⏲️Ends: {end}\n"
                             f"ℹ️Threshold: {threshold}\n"
                             f"🗳️Turnout: {turnout:,.2f}\n"
                             f"✅AYE: {ayes:,.2f} - ❌NAY: {nays:,.2f}\n\n"
                             f"https://{self.hashtag.lower()}.polkassembly.io/referendum/{index}")
                    proposal_construct['proposals'].append(tweet)

                queue.enqueue(proposal_construct)

            if queue.size() >= 1:
                task = self.loop.create_task(queue.process_queue())
                self.loop.run_until_complete(task)

            self.utils.cache_data(filename='data-cache/referenda.cache', data=referendum_info)
