# mta-tracker

This is my little tracker for the N/W departures from Astoria Ditmars so that I don't have to wait in the rain / cold / heat as much asnymore
🥂

Polls the MTA realtime feed and shows the next Manhattan-bound N/W departures
on a 16x2 I2C LCD.

## Setup

```bash
python3 -m venv venv
venv/bin/pip install nyct-gtfs RPLCD smbus2
```

Run it manually:

```bash
venv/bin/python main.py
```

## Run on startup

A [systemd](https://www.freedesktop.org/wiki/Software/systemd/) service starts
the tracker on boot and restarts it if it crashes. See
[`mta-tracker.service.example`](mta-tracker.service.example).

1. Copy the example and fill in your username / install path:

   ```bash
   cp mta-tracker.service.example mta-tracker.service
   # edit mta-tracker.service: replace YOUR_USER and the paths
   ```

2. Install, enable on boot, and start:

   ```bash
   sudo cp mta-tracker.service /etc/systemd/system/mta-tracker.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now mta-tracker.service
   ```

3. Check it's running:

   ```bash
   systemctl status mta-tracker
   journalctl -u mta-tracker -f      # live logs
   ```

### Applying code edits

The service loads the code once at startup, so edits don't take effect until
you restart it:

```bash
sudo systemctl restart mta-tracker
```

### LCD not lighting up?

The service runs as your user, which needs I2C access. Make sure your user is
in the `i2c` group:

```bash
groups                          # check for "i2c"
sudo usermod -aG i2c $USER      # add it, then reboot
```
