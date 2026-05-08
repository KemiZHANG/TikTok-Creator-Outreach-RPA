# Online Authorization

This project can optionally check an online authorization service before running.

By default, the check is disabled so local development still works:

```powershell
python main2.py
```

To require authorization:

```powershell
$env:RPA_AUTH_ENABLED="1"
$env:RPA_AUTH_API_URL="https://your-auth-server.example.com/api/authorize"
$env:RPA_LICENSE_KEY="company-user-001"
python main2.py
```

If `RPA_LICENSE_KEY` is not set, the script asks for it at startup.

## App ID

This project identifies itself as:

```text
tiktok_bd_auto
```

Use this value in the authorization server's `allowed_apps` field.

## Security Note

This is an online permission gate for practical internal use. If users receive editable Python source code, a technical user could remove the authorization check. For stronger protection, distribute the RPA as an `.exe` and keep the source code private.
