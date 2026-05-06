# Deployment on an IONOS VPS

Recommended base OS: Debian stable.

## Install Docker and Nginx

```bash
apt update
apt install -y docker.io docker-compose-plugin nginx certbot python3-certbot-nginx git
systemctl enable --now docker nginx
```

## Deploy DebZip

```bash
mkdir -p /opt/debzip
cd /opt/debzip
# copy or unzip this project here
cp .env.example .env
mkdir -p cache keys
./scripts/generate-gpg-key.sh
docker compose up -d --build
```

## Nginx reverse proxy

Create `/etc/nginx/sites-available/debzip`:

```nginx
server {
    listen 80;
    server_name debzip.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 900;
        proxy_send_timeout 900;
        proxy_request_buffering off;
    }
}
```

Enable it:

```bash
ln -s /etc/nginx/sites-available/debzip /etc/nginx/sites-enabled/debzip
nginx -t
systemctl reload nginx
```

## HTTPS

```bash
certbot --nginx -d debzip.example.com
```

## Cache cleanup cron

```bash
crontab -e
```

Add:

```cron
15 * * * * cd /opt/debzip && ./scripts/cache-cleanup.sh >> /var/log/debzip-cache-cleanup.log 2>&1
```
