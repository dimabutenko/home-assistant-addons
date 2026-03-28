# Home Assistant Add-on: Calibre-Web Automated

This repository hosts a custom Home Assistant add-on for **Calibre-Web Automated**,
a Docker container that provides a web interface for your Calibre ebook library with
additional automation features (like automatic ebook processing).

The primary goal of this add-on is to integrate the `crocodilestick/calibre-web-automated`
Docker image seamlessly into Home Assistant OS, allowing users to host their ebook
library directly within their Home Assistant environment.

## Key Features

* **Calibre-Web Automated Integration:** Provides a full-featured web interface to browse, read, and manage your Calibre ebook library.
* **Automation:** Leverages the original `crocodilestick/calibre-web-automated` features for automated book processing.
* **Home Assistant OS Compatibility:** Designed to run reliably on Home Assistant OS (e.g., Raspberry Pi).
* **External Data Storage:** Ebook library data (`config`, `ingest`, `library`) is stored in the Home Assistant's `/media` directory for easy access and backup.
* **Automated Builds:** Images are pre-built for `aarch64` (Raspberry Pi) and published to GitHub Container Registry (GHCR) using GitHub Actions, speeding up installation and updates.

## Based On

This add-on is built upon and directly integrates the excellent work of:

* **Calibre-Web Automated (crocodilestick):**
    [https://github.com/crocodilestick/calibre-web-automated](https://github.com/crocodilestick/calibre-web-automated)
    *(This is the Docker image that runs the core Calibre-Web application).*

## How it Works (Schematic Overview)

Integrating custom Docker containers into Home Assistant OS add-ons can be challenging due to architectural differences (e.g., `docker-compose` vs. HA Add-on `config.yaml` limitations). This add-on employs a specific design to overcome these:

1.  **Original Container (`crocodilestick/calibre-web-automated`):**
    The base Docker image declares certain directories (like `/config`, `/calibre-library`) as `VOLUME`s, which Docker typically manages as anonymous volumes.

2.  **Home Assistant Add-on Environment:**
    * The `config.yaml` of this add-on configures `map: ["media:rw"]`, making the Home Assistant's `/media` directory accessible inside the add-on container at `/media`.
    * It also enables `apparmor: false` and `privileged: [SYS_ADMIN]` to allow advanced filesystem operations.

3.  **Custom Initialization Script (`01-ha-links.sh`):**
    This script runs early in the container's startup process (`/etc/cont-init.d/`). Its crucial role is to perform `mount --bind` operations:
    * It binds specific subdirectories from `/share/calibre-automated/` (e.g., `share/calibre-automated/library`)
    * **OVER** the default `VOLUME` paths declared by the original container (e.g., `/calibre-library`).
    This "bind mount over volume" technique ensures that the application (Calibre-Web) sees its data in the expected paths, while the actual data resides in the user-accessible `/media` directory.

4.  **GitHub Actions Integration:**
    * The add-on image (`ghcr.io/dimabutenko/ha-addon-cwa:latest`) is pre-built for `linux/aarch64` architecture (for Raspberry Pi users).
    * GitHub Actions automatically builds and publishes the Docker image to GitHub Container Registry (GHCR) whenever changes are pushed to the `main` branch.
    * The image version is automatically extracted from `config.yaml` to ensure proper versioning in GHCR.

## Installation

1.  **Add this repository** to your Home Assistant Add-on Store:
    * In Home Assistant, navigate to `Settings` -> `Add-ons` -> `Add-on Store`.
    * Click the three dots in the top right corner and select `Repositories`.
    * Paste the URL of this GitHub repository: `https://github.com/dimabutenko/home-assistant-addons.git` (replace with your actual URL).
    * Click `Add`.
2.  **Install the add-on:**
    * Refresh the Add-on Store (three dots -> `Check for updates`).
    * Find "Calibre-Web Automated" in the list and click it.
    * Click `Install`.
3.  **Prepare your data:**
    * Ensure your Calibre library data (folders `config`, `ingest`, `library`) is located in `/media/calibre-automated/` on your Home Assistant file system.
4.  **Start the add-on:**
    * Configure any desired add-on options.
    * Start the add-on.
    * Open the Web UI to confirm your library is loaded.

## Contribution

If you have suggestions or issues, please open an issue on the GitHub repository.