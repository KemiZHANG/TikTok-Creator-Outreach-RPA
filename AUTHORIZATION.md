# Online Authorization

The packaged TikTok RPA requires online authorization before it runs.

For distributed `.exe` builds:

- Authorization is always enabled.
- The authorization server URL is embedded into the exe during final packaging.
- `auth_config.json` only stores the user's license key.
- If `auth_config.json` is missing, malformed, or has no `license_key`, the exe stops.

Example `auth_config.json`:

```json
{
  "license_key": "staff-001",
  "timeout_seconds": 8
}
```

Local Python source runs can still be controlled with environment variables for development:

```powershell
$env:RPA_AUTH_ENABLED="1"
$env:RPA_AUTH_API_URL="http://SERVER_PUBLIC_IP:8000/api/authorize"
$env:RPA_LICENSE_KEY="staff-001"
python main2.py
```

## App ID

```text
tiktok_bd_auto
```

## Upgrade Existing Computers

Keep each computer's existing `config.json`, `images\`, OCR regions, coordinates, and templates. Upgrade by replacing only the exe and adding an `auth_config.json` with that user's license key.

## Security Note

This is a practical internal permission gate. Do not distribute editable Python source code to end users; distribute the packaged exe instead.
