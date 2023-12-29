# InternalGov-2.0
A dedicated discussion forum within your Discord server, specifically designed to facilitate thoughtful and constructive conversations around ongoing proposals. This interactive platform empowers members to openly share their insights, perspectives, and opinions on each referendum prior to the submission of an official vote by the designated proxy account on behalf of the collective or DAO.

The primary objective of this forum is to foster an environment of collaboration and informed decision-making, ensuring that every voice within the community is acknowledged and taken into consideration. By harnessing the collective wisdom of your community, you can make well-informed decisions that truly represent the best interests of the entire group.

We encourage everyone to actively participate in these discussions, as your input and feedback are invaluable in shaping the direction and outcomes of your collectives endeavors. Together, we can forge a stronger, more unified community that thrives on the principles of transparency, cooperation, and shared vision.

![alt text](https://i.imgur.com/Ogg29qC.png)

---

## Initial setup
### Discord API key
1. First, you'll need to create a new application on the [Discord Developer Portal](https://discord.com/developers/applications). If you don't already have an account, you'll need to sign up for one.
2. Once you're logged in to the [Discord Developer Portal](https://discord.com/developers/applications), click on the "New Application" button in the top right corner. Give your application a name and click "Create".  
![alt text](https://i.imgur.com/bHTgBIX.png)
3. Next, click on the "Bot" section in the left-hand menu and then click "Add Bot". Give your bot a username and profile picture, and click "Save Changes".  
![alt text](https://i.imgur.com/kxHZxsV.png)
4. The bot does not need require any Privileged Gateway Intents.
5. Under the "Token" section, click the "Copy" button to copy the API key. This key is what you'll use to authenticate your bot and allow it to interact with the Discord API.  
![alt text](https://i.imgur.com/2zhE3qT.png)
6. Under Oauth2 -> URL Generator select `bot` and then select:
   - Manage Roles
   - Create Public Threads
   - Send Messages in Threads
   - Manage Messages
   - Manage Threads
   - Mention Everyone (This is required so that it can mention the notification role)

![](bot_permissions.png)

NOTE: `Manage Roles` is only needed initially to create the [SYMBOL]-GOV role to notify members to vote. You can either create the role yourself or remove `Manage Roles` permission once the role is created to limit any attack surface. The created role has no inherent permission and is only used for tagging.
7. Be sure to keep your API key secret! Don't share it with anyone or include it in any public code repositories.

###### server / forum id
1. Open Discord and click on the gear icon next to your username in the bottom left corner of your screen.
2. Under App Settings, click Advanced and enable Developer Mode
3. Right-click on your server and copy id. The same step is repeated for the forum channel.


```dotenv
# Discord Settings
DISCORD_API_KEY=<api-key>
DISCORD_SERVER_ID=<server-id>
DISCORD_FORUM_CHANNEL_ID=<forum-id>
DISCORD_LOCK_THREAD=28
DISCORD_VOTER_ROLE=<role that is allowed to vote>
DISCORD_ADMIN_ROLE=<role for administrative commands>
DISCORD_TITLE_MAX_LENGTH=95
DISCORD_BODY_MAX_LENGTH=2000
DISCORD_NOTIFY_ROLE='KSM-GOV'

# Network Settings
NETWORK_NAME=kusama
SYMBOL=KSM
TOKEN_DECIMAL=1e12 (set to 1e10 for Polkadot)
SUBSTRATE_WSS=wss://rpc.ibp.network/kusama

# Wallet Settings
PROXIED_ADDRESS=<Address of the account the proxy controls>
MNEMONIC='<Mnemonic of proxy account>'
CONVICTION='Locked4x'

```
note: `discord_role` is optional. If left as `null` it will allow anyone to cast a vote.

---

## Installing prerequisite libraries / tooling
`pip3 install -r requirements`
##### Installing PM2 (Process Manager)
###### PM2 is a daemon process manager that will help you manage and keep your application/bot online 24/7 
`npm install pm2 -g`

###### Daemonize the bot to run 24/7 with PM2
```shell
pm2 start main.py --name ksmgov2 --interpreter python3
pm2 save
```

---
## Autonomous voting
![alt text](https://i.imgur.com/5d0HJsY.png)
### vote settings
###### Kusama vote periods
| Role               | Decision Period (days) | Internal Vote Period (days) | Revote Period (days) |
|--------------------|------------------------|-----------------------------|----------------------|
| Root               | 14                     | 5                           | 10                   |
| WhitelistedCaller  | 14                     | 3                           | 10                   |
| StakingAdmin       | 14                     | 5                           | 10                   |
| Treasurer          | 14                     | 5                           | 10                   |
| LeaseAdmin         | 14                     | 5                           | 10                   |
| FellowshipAdmin    | 14                     | 5                           | 10                   |
| GeneralAdmin       | 14                     | 5                           | 10                   |
| AuctionAdmin       | 14                     | 5                           | 10                   |
| ReferendumCanceller| 7                      | 2                           | 4                    |
| ReferendumKiller   | 14                     | 2                           | 10                   |
| SmallTipper        | 7                      | 1                           | 4                    |
| BigTipper          | 7                      | 1                           | 4                    |
| SmallSpender       | 14                     | 5                           | 10                   |
| MediumSpender      | 14                     | 5                           | 10                   |
| BigSpender         | 14                     | 5                           | 10                   |
> Example:
> > A proposal is submitted with its origin designated as 'Treasurer'. Following a period of five days after its on-chain introduction, a vote is conducted in accordance with the predetermined internal outcome. Should there be a shift in the voting stance from 'AYE' to 'NAY', a subsequent vote will be executed on the tenth day of the proposal's on-chain presence. In instances where the initial decision remains unaltered and the proposal has aged ten days or more, no further on-chain voting action will be undertaken.

###### Polkadot vote periods
| Role               | Decision Period (days) | Internal Vote Period (days) | Revote Period (days) |
|--------------------|------------------------|-----------------------------|----------------------|
| Root               | 28                     | 7                           | 20                   |
| WhitelistedCaller  | 28                     | 2                           | 20                   |
| StakingAdmin       | 28                     | 7                           | 20                   |
| Treasurer          | 28                     | 7                           | 20                   |
| LeaseAdmin         | 28                     | 7                           | 20                   |
| FellowshipAdmin    | 28                     | 7                           | 20                   |
| GeneralAdmin       | 28                     | 7                           | 20                   |
| AuctionAdmin       | 28                     | 7                           | 20                   |
| ReferendumCanceller| 7                      | 2                           | 4                    |
| ReferendumKiller   | 28                     | 4                           | 20                   |
| SmallTipper        | 7                      | 2                           | 4                    |
| BigTipper          | 7                      | 2                           | 4                    |
| SmallSpender       | 28                     | 7                           | 20                   |
| MediumSpender      | 28                     | 7                           | 20                   |
| BigSpender         | 28                     | 7                           | 20                   |
> Example:
> > A proposal is submitted with its origin designated as 'AuctionAdmin'. Following a period of seven days after its on-chain introduction, a vote is conducted in accordance with the predetermined internal outcome. Should there be a shift in the voting stance from 'AYE' to 'NAY', a subsequent vote will be executed on the twentieth day of the proposal's on-chain presence. In instances where the initial decision remains unaltered and the proposal has aged ten days or more, no further on-chain voting action will be undertaken.