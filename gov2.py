from substrateinterface import SubstrateInterface
import requests
import deepdiff
import yaml
import json
import os

with open("config.yaml", "r") as file:
    config = yaml.safe_load(file)


class Utils:
    @staticmethod
    def cache_data(filename, data):
        with open(f"{filename}", 'w') as cache:
            cache.write(json.dumps(data, indent=4))
        cache.close()

    @staticmethod
    def open_cache(filename):
        with open(f"./data/{filename}", 'r') as cache:
            cached_file = json.loads(cache.read())
            cache.close()
        return cached_file

    def cache_difference(self, filename, data):
        if not os.path.isfile(f"./data/{filename}"):
            self.cache_data(f"./data/{filename}", data)
            return {}

        cached_data = self.open_cache(f"{filename}")

        # use DeepDiff to check if any values have changed since we ran has_commission_updated().
        difference = deepdiff.DeepDiff(cached_data, data, ignore_order=True).to_json()
        result = json.loads(difference)

        if len(result) == 0:
            return {}
        else:
            return result


class OpenGovernance2:
    def __init__(self):
        self.util = Utils()
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
    def polkassembly(referendum_id: int):
        """
        Retrieve information about a specific referendum from the Polkassembly API.

        Args:
        - referendum_id (int): The ID of the referendum.

        Returns:
        - dict: A dictionary containing the information about the post with the specified `referendum_id`.
          The dictionary has the following keys:
            - title (str): The title of the post.
            - content (str): The content of the post.
            - onchain_link (dict): A dictionary containing the onchain link information.
                - proposer_address (str): The address of the proposer.
            - comments (list): A list of dictionaries, each containing information about a comment.
                - content (str): The content of the comment.
                - created_at (str): The creation time of the comment.
                - author (dict): A dictionary containing information about the author of the comment.
                    - username (str): The username of the author.
                - replies (list): A list of dictionaries, each containing information about a reply.
                    - content (str): The content of the reply.
                    - author (dict): A dictionary containing information about the author of the reply.
                        - username (str): The username of the reply author.

        Raises:
        - HTTPError: If an HTTP error occurs.
        - ConnectionError: If there's an error connecting to the API.
        - Timeout: If the connection times out.
        - RequestException: If there's a general error when making the request.
        """
        try:
            headers = {"Content-Type": "application/json"}

            # Define the GraphQL query
            query = f"""
            query {{
              posts(where: {{onchain_link: {{onchain_proposal_id: {{_eq: {referendum_id}}} }}}}) {{
                title
                content
                onchain_link {{
                    proposer_address
                }}
                comments {{
                    content
                    created_at
                    author {{
                       username
                    }}
                    replies {{
                       content
                       author {{
                         username
                      }}
                    }}
                 }}
              }}
            }}
            """

            # Make the request
            response = requests.post(config['polkassembly_graphql'], json={'query': query}, headers=headers)
            response.raise_for_status()

            # Print the response
            return response.json()
        except requests.exceptions.HTTPError as http_error:
            return f"HTTP Error: {http_error}"
        except requests.exceptions.ConnectionError as connection_error:
            return f"Error Connecting: {connection_error}"
        except requests.exceptions.Timeout as timeout_error:
            return f"Timeout Error: {timeout_error}"
        except requests.exceptions.RequestException as request_error:
            return f"Something went wrong: {request_error}"

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
        results = self.util.cache_difference(filename='governance.cache', data=referendum_info)

        if results:
            for key, value in results.items():
                if 'added' in key:
                    for index in results['dictionary_item_added']:
                        index = index.strip('root').replace("['", "").replace("']", "")
                        onchain_info = referendum_info[index]['Ongoing']
                        polkassembly_info = self.polkassembly(index)['data']['posts'][0]

                        new_referenda.update({
                            f"{index}": polkassembly_info
                        })

                        new_referenda[index]['onchain'] = onchain_info

            self.util.cache_data(filename='./data/governance.cache', data=referendum_info)
            return json.dumps(new_referenda)
        return False

