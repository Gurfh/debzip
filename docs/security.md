# Security

## Input validation

The gateway and workers validate:

- release names via whitelist
- architecture names via whitelist
- package names via strict regular expression
- job IDs via strict regular expression

## Rate limiting

The gateway uses Redis-backed per-IP rate limits. Adjust limits in `gateway/app.py`.

## Resource limits

Workers enforce:

- maximum package count
- maximum total download size
- job timeout

## Manifest signing

Every ZIP includes:

```text
MANIFEST.txt
MANIFEST.txt.asc
packages/*.deb
```

If a GPG private key is available, the manifest is detached-signed. If no key is available, a placeholder `.asc` file explains that signing was not configured.

## Production hardening recommendations

- Run behind Nginx with HTTPS.
- Add authentication if the service is not public.
- Keep Docker and Debian images patched.
- Use pinned Debian image tags if reproducibility matters.
- Back up and protect signing keys.
- Add firewall rules so workers are not exposed publicly.
