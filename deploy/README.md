# Calls across different networks (public server)

Two people on different networks (home Wi-Fi vs. mobile data, office firewalls) often **cannot connect
directly**. A **TURN relay** forwards their video when that happens. This folder runs the app, automatic
HTTPS and a TURN relay for you. **I could not run Docker while building this, so treat it as a careful
draft: follow the steps and send me any error text.**

## What you need
* A small Linux server (VPS) with a **public IP address**. This costs money; prices vary by provider.
* A **domain or subdomain** with an `A` record pointing to that server (HTTPS and browser cameras need it).
* Docker and Docker Compose installed on the server.
* Firewall / cloud security group **open** for: `80/tcp`, `443/tcp`, `3478/udp`, `3478/tcp`,
  and `49160-49260/udp` (the relay's port range).

## Steps
1. Copy the whole project to the server (for example with `git` or `scp`).
2. `cd deploy && cp .env.example .env` and edit `.env`: set `DOMAIN`, `ACCESS_CODE`, `TURN_SECRET`.
3. `docker compose up -d --build`
4. Open `https://YOUR_DOMAIN`. The first load can take a minute while the certificate is issued.
5. In the **📹 Video call** tab press **🌐 Check my connection**, type a room code and check again.
   You want: **✅ Relay server reachable**.

## How people use it
* The **host** opens the site, enters the **access code** when asked, and starts a call.
* **Guests** just open the invite link and join; they do not need the access code.
* Anyone who has a room code can join that room, so share links only with people you trust.

## Security notes
* The app has **no user accounts**. The access code stops strangers using your server for translation, OCR,
  history and starting rooms. It is a single shared secret, not a full login.
* TURN logins are **short-lived** (1 hour) and only given out for rooms that exist; the shared secret never
  leaves the server. The relay refuses to connect to private network addresses.
* The relay carries video between people, so your server's bandwidth is used. Watch your provider's traffic
  limits. Calls between people who can connect directly do not use the relay.
* Video is encrypted between browsers (WebRTC). The relay cannot see it, but the server operator can see
  which IP addresses connect.
* Captions are translated on your server; text is not saved to history during calls.

## Translation model on the server
Mock mode only knows a few greetings. The NLLB model is large (about 3 GB, non-commercial licence) and
needs a server with enough RAM (about 4 GB or more). It is not baked into the image.

## Stop / update
`docker compose down` stops everything. After changing code: `docker compose up -d --build`.
