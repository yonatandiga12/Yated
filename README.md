# Streamlit + Google Drive/Sheets (view + append rows)

This Streamlit app:

- Finds a Google Sheet **named `hi`** inside the Drive folder:
  - `1XZ9fZUusUYO1IpJFUZ8tlQ0NdIu0tPAq`
- Displays it as a table
- Lets you append a new row

## Files

- `app.py`: Streamlit UI + Google APIs integration
- `requirements.txt`: dependencies for Streamlit Cloud

## Local run

1. Create a local secrets file (DO NOT commit it):

Create `.streamlit/secrets.toml` with your service account JSON values (example below).

2. Install and run:

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

## Google setup (one-time)

### 1) Create a Service Account + JSON key

1. Go to Google Cloud Console → create/select a project
2. Enable APIs:
   - **Google Drive API**
   - **Google Sheets API**
3. IAM & Admin → Service Accounts → **Create service account**
4. Keys → **Add key** → **Create new key** → JSON → download the JSON

### 2) Share the Drive folder with the service account

Open the Drive folder and share it with the service account email:

- `xxxxx@yyyy.iam.gserviceaccount.com`

Give it **Editor** access (so it can edit the sheet).

## Streamlit Cloud: how to add the JSON secret (recommended way)

Streamlit Community Cloud does **not** want you to upload a JSON file into the repo.
Instead, paste its contents into **Secrets**.

1. Deploy your app repo on Streamlit Cloud
2. Go to your app → **Settings** → **Secrets**
3. Paste this template and fill it with values from your downloaded service account JSON:

```toml
[gcp_service_account]
type = "service_account"
project_id = "YOUR_PROJECT_ID"
private_key_id = "YOUR_PRIVATE_KEY_ID"
private_key = """-----BEGIN PRIVATE KEY-----
YOUR_PRIVATE_KEY_CONTENT
-----END PRIVATE KEY-----"""
client_email = "YOUR_SERVICE_ACCOUNT_EMAIL"
client_id = "YOUR_CLIENT_ID"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "YOUR_CLIENT_X509_CERT_URL"
```

Notes:

- Keep the triple quotes around `private_key` exactly like above.
- The app reads it via `st.secrets["gcp_service_account"]`.

## Troubleshooting

- If the app says it cannot find the sheet:
  - Ensure the file is actually named **exactly** `hi`
  - Ensure you shared the folder with the **service account email**
- If append fails with permissions:
  - Ensure folder sharing is **Editor** (not Viewer)
