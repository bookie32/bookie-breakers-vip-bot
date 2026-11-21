# BOOKIE BREAKERS Discord bot

This repository contains the BOOKIE BREAKERS Discord bot and its Python package.

## Run locally

Install dependencies and start the bot from the repository root:

```bash
pip install -r requirements.txt
python -m bookie_breakers
```

The bot loads its configuration from environment variables. Never put the Discord token or other credentials in source files or commit them to GitHub.

### Required environment variables

- `DISCORD_TOKEN`
- `HEAD_ADMIN_ID`
- `VIP_ADMIN_ID`
- `TALLY_FORM_URL`
- `MAIN_GUILD_ID`
- `MAIN_VIP_WINGS_CLIENT_ID`
- `CONTACT_OWNER_CHANNEL_ID`
- `MAIN_VIP_APPLICATION_CHANNEL_ID`
- `VIP_GUILD_ID`
- `VIP_CLIENT_ID`
- `VIP_APPLICATION_CHANNEL_ID`

Optional:

- `VIP_WINS_CHANNEL_ID`
- `LOG_LEVEL`

## Deploy on Render

1. In Render, create a **Background Worker** and connect this GitHub repository.
2. Set the build command to:

   ```bash
   pip install -r requirements.txt
   ```

3. Set the start command to:

   ```bash
   python -m bookie_breakers
   ```

4. Add all required environment variables listed above in the Render service's **Environment** settings. Add optional values if needed. Store `DISCORD_TOKEN` as a secret environment variable; do not add it to this repository.
5. Deploy the worker and check its logs for startup/configuration errors.

Use Render's free plan if it is available for your account and service type. Free-plan availability and behavior may change, and it does **not** guarantee 24/7 uptime. Choose a paid plan if continuous availability is required.
