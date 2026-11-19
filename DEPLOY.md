# Putting the app online (Streamlit Community Cloud)

Clients open a web link; accounts and data live in Supabase, so nothing depends on your PC.

1. **Push the code to GitHub** (repo: `projectdata2698-ship-it/HR-Assistant`). `.env` and
   `.streamlit/secrets.toml` are git-ignored, so no secrets are uploaded.
2. Go to https://share.streamlit.io, sign in with GitHub, **Create app**:
   repository `HR-Assistant`, branch `main`, main file `app.py`.
   Under **Advanced settings** choose Python 3.12 or 3.13.
3. In **Advanced settings > Secrets** paste the contents of `.streamlit/secrets.toml.example`
   and fill in your real values (Groq key, Supabase URL with the password URL-encoded, ADMIN_PASSWORD).
   Leave the `[auth]` part out until Google sign-in is set up.
4. Deploy. Open the link and log in as the administrator (projectdata2698@gmail.com).
5. **Google sign-in (optional):** in Google Cloud add `https://<your-app>.streamlit.app/oauth2callback`
   as an authorized redirect URI, set the same value as `redirect_uri` in the secrets, add the
   Client ID / secret, and add each client to the OAuth consent screen's test users (or publish the app).

## Letting clients in
New sign-ups are **pending**. Log in as admin > **Admin > Users > Waiting for approval** > Approve.
Approved clients can open At a glance, Summary and Excel reports; pending or blocked ones only see Chat.
Use **Access** under "Manage an account" to block / re-approve someone later.

## Before sharing the link
* Rotate the Groq key and the Supabase database password (they were pasted in chats) and update the secrets.
* Supabase: Project Settings > Database - the app only needs the Session pooler string.
