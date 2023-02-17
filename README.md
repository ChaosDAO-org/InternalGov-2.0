# InternalGov-2.0
Create a discussion forum for your discord server to discuss each upcoming referendums. The purpose of this forum is to allow members to share their thoughts and opinions on the referendum before a designated proxy account casts the official vote on behalf of the people/DAO.

![alt text](https://i.imgur.com/c1c7mMs.png)

## Prereq(s)
#### Installing discord.py
###### Install the latest version of discord.py to interface with threads.
`pip3 install -U git+https://github.com/Rapptz/discord.py`


#### Installing PM2
###### PM2 is a daemon process manager that will help you manage and keep your application online 24/7 
`npm install pm2 -g`


## Initial setup
###### Discord API key
1. First, you'll need to create a new application on the [Discord Developer Portal](https://discord.com/developers/applications). If you don't already have an account, you'll need to sign up for one.


2. Once you're logged in to the [Discord Developer Portal](https://discord.com/developers/applications), click on the "New Application" button in the top right corner. Give your application a name and click "Create".


3. Next, click on the "Bot" section in the left-hand menu and then click "Add Bot". Give your bot a username and profile picture, and click "Save Changes".


4. Under the "Token" section, click the "Copy" button to copy the API key. This key is what you'll use to authenticate your bot and allow it to interact with the Discord API.


5. Be sure to keep your API key secret! Don't share it with anyone or include it in any public code repositories.

###### server / forum id
1. Open Discord and click on the gear icon next to your username in the bottom left corner of your screen.


2. Under App Settings, click Advanced and enable Developer Mode


3. Right-click on your server and copy id. The same step is repeated for the forum channel.


```yaml
discord_api_key: <api-secret>
discord_server_id: <server-id>
discord_forum_channel_id: <channel-id>
substrate_wss: wss://kusama-rpc.polkadot.io
polkassembly_graphql: https://kusama.polkassembly.io/v1/graphql
```

###### Daemonize the bot to run 24/7 with PM2
```shell
pm2 start discord-bot.py --name opengov2 --interpreter python3
pm2 save
```


---

### Objectives
- [X] Initial creation
- [X] Automatically create tags for threads based on Origin of referendum. `[SmallTipper, Root, MediumSpender, BigSpender,  WhitelistedCaller, AuctionAdmin, Treasurer]`
- [ ] Run for 1 - 2 weeks (starting 13/02/2023), resolve any issues. Push to git.
- [ ] Auto archive a thread using onchain data
- [ ] Only allow a specific role to vote
- [ ] A setting to anonymize votes by recording who votes what locally and using onchain data of when a referendum ends to show the results at the end of the thread
- [ ] Requests