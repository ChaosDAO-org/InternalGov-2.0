import json
import discord
import datetime
from scalecodec.base import ScaleBytes
from substrateinterface import SubstrateInterface
from websocket._exceptions import WebSocketException


intents = discord.Intents.default()
intents.messages = True         # Necessary to read messages
intents.message_content = True  # Necessary to access message content

# Create a new discord bot client with intents
client = discord.Client(intents=intents)


class MaterializedChainState:
    def __init__(self, url="wss://rpc.ibp.network/polkadot"):
        try:
            self.substrate = SubstrateInterface(url=url,
                                                auto_reconnect=True,
                                                ws_options={'close_timeout': 15, 'open_timeout': 15})

        except WebSocketException as error:
            print(f"Unable to connect: {error.args}")
            exit()

    def ref_caller(self, index: int, gov1: bool, call_data: bool):
        try:
            referendum = self.substrate.query(module="Democracy" if gov1 else "Referenda",
                                              storage_function="ReferendumInfoOf" if gov1 else "ReferendumInfoFor",
                                              params=[index]).serialize()

            if referendum is None or 'Ongoing' not in referendum:
                return False, f"Referendum #{index} not active"

            preimage = referendum['Ongoing']['proposal']

            if 'Inline' in preimage:
                call = preimage['Inline']
                if not call_data:
                    call_obj = self.substrate.create_scale_object('Call')
                    decoded_call = call_obj.decode(ScaleBytes(call))
                    return decoded_call
                else:
                    return call

            if 'Lookup' in preimage:
                preimage_hash = preimage['Lookup']['hash']
                preimage_length = preimage['Lookup']['len']
                call = self.substrate.query(module='Preimage', storage_function='PreimageFor',
                                            params=[(preimage_hash, preimage_length)]).value

                if call is None:
                    return "Preimage not found on chain"

                if not call.isprintable():
                    call = f"0x{''.join(f'{ord(c):02x}' for c in call)}"

                if not call_data:
                    call_obj = self.substrate.create_scale_object('Call')
                    decoded_call = call_obj.decode(ScaleBytes(call))
                    return decoded_call
                else:
                    return call
        except Exception as ref_caller_error:
            raise ref_caller_error


def format_key(key):
    """
    Formats a given key by splitting it on underscores, capitalizing each part except
    for those containing 'id' which are made uppercase, and then joining them back together
    with spaces in between.

    :param key: The key to be formatted.
    :type key: str
    :return: The formatted key.
    :rtype: str
    """
    parts = key.split('_')
    formatted_parts = []
    for part in parts:
        if "id" in part.lower():
            formatted_part = part.upper()
        else:
            formatted_part = part.capitalize()
        formatted_parts.append(formatted_part)
    return ' '.join(formatted_parts)


def find_and_collect_values(data, embeds, indent=0, path='', current_embed=None):
    """
    Recursively traverses through the given data (list, dictionary or other data types)
    and collects certain values to be added to a list of discord Embed objects.
    The function modifies the given `embeds` list in-place,
    appending new Embed objects when required.

    :param data: The data to traverse
    :type data: list, dict or other
    :param embeds: The list of Embed objects to extend
    :type embeds: list
    :param indent: The current indentation level for formatting Embed descriptions, default is 0
    :type indent: int
    :param path: The path to the current data element, default is ''
    :type path: str
    :param current_embed: The currently active Embed object, default is None
    :type current_embed: Embed or None
    :return: The extended list of Embed objects
    :rtype: list
    """
    if current_embed is None:
        description = ""  # Create a description variable
        current_embed = discord.Embed(title=":ballot_box: Call", description=description, color=0x00ff00)
        current_embed.set_thumbnail(url='https://i.imgur.com/n35LSWY.png')

        embeds.append(current_embed)

    max_description_length = 4000
    call_function = 0
    call_module = 0

    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{path}.{hash(key)}" if path else str(hash(key))

            if key == 'call_index':
                continue

            if isinstance(value, (dict, list)):
                find_and_collect_values(value, embeds, indent, new_path, current_embed)
            else:
                value_str = str(value)
                if len(current_embed.description) + len(value_str) > max_description_length:
                    description = ""  # Create a new description for a new embed
                    current_embed = discord.Embed(title="", description=f"{description}", color=0x00ff00)
                    embeds.append(current_embed)

                if key == 'call_function':
                    call_function = call_function + 1

                if key == 'call_module':
                    call_module = call_module + 1

                if key in ['X1', 'X2', 'X3', 'X4', 'X5']:
                    indent = indent + 1

                if call_function == 1 and call_module == 0:
                    indent = indent + 1

                print(f"{key:<20} {call_function:<15} {call_module:<15} {indent:<15} {key not in ['call_function', 'call_module']}")  # debugging

                if key not in ['call_function', 'call_module']:
                    if key == 'amount':
                        value_str = float(value_str) / 1e10
                        current_embed.description += f"\n{'* ' * (indent + 1)} **{format_key(key)[:256]}**: {value_str:,.1f}"
                    elif key in ['beneficiary', 'signed', 'curator']:
                        current_embed.description += f"\n{'* ' * (indent + 1)} **{format_key(key)[:256]}**: [{(value_str[:10] + '...' + value_str[-10:])}](https://polkadot.subscan.io/account/{value_str})"
                    else:
                        current_embed.description += f"\n{'* ' * (indent + 1)} **{format_key(key)[:256]}**: {(value_str[:253] + '...') if len(value_str) > 256 else value_str}"
                else:
                    current_embed.description += f"\n{'* ' * indent} **{format_key(key)[:256]}**: `{value_str[:253]}`"

                find_and_collect_values(value, embeds, indent, new_path, current_embed)

    elif isinstance(data, (list, tuple)):
        for index, item in enumerate(data):
            new_path = f"{path}[{index}]"
            find_and_collect_values(item, embeds, indent, new_path, current_embed)

    return embeds


def consolidate_call_args(data):
    """
    Modifies the given data in-place by consolidating 'call_args' entries
    from list of dictionaries into a single dictionary where the key is 'name'
    and the value is 'value'.

    :param data: The data to consolidate
    :type data: dict or list
    :return: The consolidated data
    :rtype: dict or list
    """
    if isinstance(data, dict):
        if "call_args" in data:
            new_args = {}
            for arg in data["call_args"]:
                if "name" in arg and "value" in arg:
                    new_args[arg["name"]] = arg["value"]
            data["call_args"] = new_args
        for key, value in data.items():
            data[key] = consolidate_call_args(value)  # Recursive call for nested dictionaries
    elif isinstance(data, list):
        for index, item in enumerate(data):
            data[index] = consolidate_call_args(item)  # Recursive call for lists
    return data


@client.event
async def on_ready():
    print(f'Logged in as {client.user}')


#@client.event
#async def on_error(event, *args, **kwargs):
#    with open('error.log', 'a') as f:
#        if event == 'on_message':
#            f.write(f'Unhandled message: {args[0]}\n')
#        else:
#            raise


@client.event
async def on_message(message):
    # Ignore messages sent by the bot itself
    if message.author == client.user:
        return

    if message.content.startswith('!ref_caller'):
        index = message.content.split()[1]

        chainstate = MaterializedChainState()
        data = chainstate.ref_caller(index=index, gov1=False, call_data=False)
        data = consolidate_call_args(data)

        embeds = []
        embed_data = find_and_collect_values(data, embeds)

        print(embed_data)

        for embed in embed_data:
            await message.channel.send(embed=embed)


client.run('')
