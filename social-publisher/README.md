# Instagram scheduled publisher

This GitHub Actions workflow is configured to run at 9:00 AM and 3:00 PM Asia/Kolkata time. It publishes one queued item to every Instagram professional account listed in the GitHub secret. The queues are empty initially, so scheduled runs publish nothing until you configure them.

## Setup still required

1. In the repository, open **Settings → Secrets and variables → Actions → New repository secret**. Create a secret named **IG_ACCOUNTS_JSON**. Its value must be a JSON array with each account's Instagram user ID and access token, for example:

   [
     {"name":"account-1","id":"INSTAGRAM_USER_ID","token":"LONG_LIVED_ACCESS_TOKEN"}
   ]

   Keep access tokens private. Do not put them in a file or commit. Each account must have Instagram Graph API publishing access approved and a valid token.

2. Edit posts.json and add items under morning and afternoon. Each item needs a public HTTPS media URL that Meta can fetch, a caption, and media_type set to image or reel. Example:

   {
     "morning": {"items": [{"media_type":"reel","media_url":"https://example.com/morning.mp4","caption":"Morning caption"}]},
     "afternoon": {"items": [{"media_type":"image","media_url":"https://example.com/afternoon.jpg","caption":"Afternoon caption"}]}
   }

   Private Drive links usually are not direct media URLs. Check Meta's current media requirements before using a file.

3. Confirm the workflow is enabled under **Actions**. Use **Run workflow** only for a deliberate test after adding the secret and queues; it will publish immediately to every configured account.

The workflow records which accounts succeeded so a rerun after a partial failure skips those accounts for that slot. GitHub scheduled runs can be delayed during platform load. Tokens may expire and need to be rotated in the repository secret.

This automation is separate from Postiz and does not reuse Postiz's connected-account tokens. Do not add personal account passwords here.
