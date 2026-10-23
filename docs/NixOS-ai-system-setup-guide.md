# Deep Learning AI Native NixOS Setup Manual — FINAL EDITION
## A Complete, Grandma-Friendly Guide for a Secure, High-Context Local AI Workstation

This document is a step-by-step, bulletproof manual written so simply that anyone can execute it. It covers migrating from Ubuntu to a pure, declarative **NixOS Flake architecture**, creating a highly secure **dual-user operating environment**, hosting the **DeepSeek-R1-Distill-Llama-70B** model fully locally and free, configuring memory mitigations so the model cannot crash your machine, and enforcing a **strict network sandbox** so the AI can research on the public internet but can never touch your home network (LAN).

---

## 📋 System Prerequisites & Architecture Target

This manual is tailor-made for your **Kubuntu Focus / Clevo Barebone Laptop (PC5x_7xHP_HR_HS)** equipped with:

*   **CPU:** Intel Core i7-11800H (11th Gen)
*   **System RAM:** 64GB DDR4 (Hardware Maximum Allocation)
*   **GPU VRAM:** NVIDIA GeForce RTX 3080 Laptop GPU (16GB Dedicated Memory Pool)
*   **Target AI Model:** DeepSeek-R1-Distill-Llama-70B (Quantized, ~42GB on disk)

**Before you begin, verify you have:**
1. Your current Ubuntu installation up and running with internet access.
2. A GitHub account (free) — create one at [github.com](https://github.com) if needed.
3. An empty USB flash drive (8GB or larger).
4. **At least 150GB of free disk space** on the internal NVMe drive (the model alone is ~42GB, plus a 48GB swap safety file, plus the OS).

---

## 🔒 The Security Concept: The Dual-User & Sandboxed Strategy

To protect your personal data, identity, and internal home infrastructure, this setup establishes a dual-user defense model:

1. **`roman` (The System Administrator):** Your standard primary profile. This user has full hardware access (`sudo` group) and is used for regular web browsing, system builds, and secure operations. **You never run AI agents under this account.**
2. **`ai-agent` (The Isolated Unprivileged Worker):** A completely restricted user profile created specifically for your AI workloads.
   - It possesses **zero administrative capabilities** and is completely excluded from the `sudoers` file.
   - It cannot execute any commands that modify the root file system.
   - Its **primary login group is `ai-sandbox`**, and the kernel firewall (`iptables`) matches on that group: the AI gets full public internet access for documentation research, but **every packet addressed to a private/LAN address range is rejected at kernel level**. It cannot see, scan, or touch your router, NAS, printers, phones, or any smart home device.
   - Public DNS servers (`1.1.1.1`, `9.9.9.9`) are configured system-wide, so the sandboxed user does not even need to ask your router (a LAN device) to resolve domain names. Internet works; LAN does not.

---

## 💾 Phase 1: Pre-Installation Version Control (Done on Ubuntu, Right Now)

Before formatting your hard drive, you will draft your new declarative configuration inside a version-controlled **GitHub Repository**. This gives you a permanent, restorable backup of your computer's brain.

### Step 1.1: Create the Private GitHub Repository
1. Log into your personal [GitHub Account](https://github.com).
2. Click the **+** icon (top right) → **New repository**.
3. Name it exactly: `nixos-config`.
4. Set visibility to **Private**. Do not add a README, license, or .gitignore (we will push our own files).
5. Click **Create repository** and leave the browser tab open.

### Step 1.2: Initialize Your Configuration Locally
Open your current Ubuntu terminal and execute:

```bash
# 1. Create a workspace directory for your NixOS architecture
mkdir -p ~/nixos-config
cd ~/nixos-config

# 2. Initialize a blank Git repository
git init
```

### Step 1.3: Create the Flake Entry Point (`flake.nix`)
This file manages inputs and locks package versions down to exact operational states (reproducibility). Create it with `vi`:

```bash
vi flake.nix
```

*Press `i` to enter insert mode, paste the code block from flake.nix in this repo, press `Esc`, then type `:wq` and hit `Enter` to save and exit.*

### Step 1.4: Create the Core System File (`configuration.nix`)
This holds your core system options, the dual-user security model, the 48GB memory swap safety net, CUDA acceleration, and the LAN isolation sandbox:

```bash
vi configuration.nix
```
*Same `vi` procedure: `i`, paste, `Esc`, `:wq`, `Enter`.* (configuration.nix from this repo)

### Step 1.5: Create the home Nix File (`home.nix`)

```bash
vi home.nix
```
*Same `vi` procedure: `i`, paste, `Esc`, `:wq`, `Enter`.* (home.nix from this repo)

### Step 1.6: Create the home Nix File (`tmux.nix`)

```bash
vi tmux.nix
```
*Same `vi` procedure: `i`, paste, `Esc`, `:wq`, `Enter`.* (tmux.nix from this repo)

> **Note on `hardware-configuration.nix`:** you do **not** create this file by hand. It describes your exact disk and kernel modules and is auto-generated on the laptop during installation (Phase 3), then copied into this repo. The repo will be complete after Phase 3.

### Step 1.7: Push the Brain to GitHub
Back in the Ubuntu terminal (still inside `~/nixos-config`):

```bash
git add flake.nix configuration.nix
git commit -m "feat: initial dual-user sandboxed AI-native flake configuration"
git branch -M main
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/nixos-config.git
git push -u origin main
```

*Replace `YOUR_GITHUB_USERNAME` with your actual GitHub username. Because the repository is **Private**, GitHub will ask for credentials: enter your username, and as the password paste a **Personal Access Token** (create one at GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic), with the `repo` scope). This is normal — GitHub no longer accepts account passwords over HTTPS.*

---

## 💿 Phase 2: Bare-Bones NixOS System Installation

Now we wipe the old Ubuntu system and install a completely pure system structure.

### Step 2.1: Flash and Boot
1. Download the modern [NixOS Graphical Installer ISO](https://nixos.org/download/) (the **GNOME** image, to match this configuration).
2. Flash it onto your empty USB drive using **BalenaEtcher** (or `dd` if you are comfortable with the terminal).
3. Plug the USB into your Clevo laptop, reboot, and hold the boot selector key (typically `F7` or `F12` on Clevo chassis) to select the USB drive.

### Step 2.2: Run the Installer Interface
1. Follow the on-screen menus (Language: English UK, Keyboard layout: UK).
2. When you reach the **Desktop Environment** screen, tick **GNOME**.
3. When reaching **Partition Setup**, choose **Erase Disk** to cleanly remove the old Ubuntu installation from the internal NVMe drive (`nvme0n1`).
4. **DISK ENCRYPTION (CRUCIAL):** Tick the checkbox that reads **"Encrypt system"** (or **"Enable Encryption"**). Enter a strong, secure passphrase when prompted. You will be required to type this passphrase every time you power on the laptop to unlock your data.
5. **CRUCIAL:** Tick the checkbox that reads **"Allow Unfree Software"** so the machine can pull your dedicated NVIDIA display drivers.
6. Hit **Install** and wait.
7. **CRUCIAL STEP:** When the installer finishes, **DO NOT let it restart.** Untick the "Restart automatically" box if present and close the installer. Stay inside the live USB environment — Phase 3 happens here.

---

## ⚡ Phase 3: The Flake Activation (Merging the GitHub Brain)

Your new system is installed on the disk, mounted at `/mnt`, but still running the generic installer configuration. Now we graft in your custom architecture from GitHub.

### Step 3.1: Generate the Hardware Map
Open a terminal inside the live environment and run:

```bash
# Generate the hardware description unique to your Clevo machine
sudo nixos-generate-config --dir /mnt/etc
```
This creates `/mnt/etc/hardware-configuration.nix` — the missing third file of your repo.

### Step 3.2: Merge With Your GitHub Configuration
```bash
# Work from the NixOS directory
cd /mnt/etc/nixos/

# Pull down your private repo (use your Personal Access Token as the password)
sudo git clone https://github.com/YOUR_GITHUB_USERNAME/nixos-config.git .

# Complete the repo by adding the freshly generated hardware file,
# and push it so the GitHub copy becomes the permanent, complete brain
sudo cp /mnt/etc/hardware-configuration.nix /mnt/etc/nixos/
git add hardware-configuration.nix
git commit -m "feat: add auto-generated hardware configuration for Clevo PC5x_7xHP_HR_HS"
git push
cd ~

# Replace the installer's generic config with your full flake layout
sudo rm -rf /mnt/etc/nixos
sudo cp -r system-files /mnt/etc/nixos
```

### Step 3.3: Rebuild the Installed System From Your Flake
```bash
sudo nixos-install --flake /mnt/etc/nixos#beast-kf
```
*This step takes a while — it downloads and builds your NVIDIA drivers, CUDA stack, desktop environment, and the 48GB swap structure. When it finishes without errors:*

NB: if the above command fails, do the following:

### Step 3.4: ONLY ESECUTE BELOW ON FAILURE, NOT OTHERWISE !!!

#### Step 3.4.1: Re-mount Your Real Hard Drive Partitions
We need to ensure your physical hard drive partitions are mounted correctly to /mnt.

   1. Run ```lsblk``` to view your actual partitions. Identify your main Linux system partition (e.g., /dev/nvme0n1p2 or /dev/sda2, usually formatted as ext4, btrfs, or zfs) and your EFI boot partition (e.g., /dev/nvme0n1p1 or /dev/sda1, formatted as vfat).
   2. Unmount the incorrect paths from your current session:
   
   ```bash
   sudo umount /mnt/boot 2>/dev/null
   sudo umount -R /mnt 2>/dev/null
   ```
   
   3. Mount your real Linux system partition to /mnt (replace /dev/nvme0n1p2 with your actual Linux partition):
   
   ```bash
   sudo mount /dev/nvme0n1p2 /mnt
   ```
   
   4. Create the correct boot directory and mount your real EFI boot partition to it (replace /dev/nvme0n1p1 with your actual EFI partition):

   ```bash
   sudo mkdir -p /mnt/boot
   sudo mount /dev/nvme0n1p1 /mnt/boot
   ```
   
#### Step 3.4.2: Regenerate the Hardware Map
Now that the real physical disks are sitting underneath /mnt, the generator will scan your storage controllers and partition UUIDs perfectly.

   1. Force a clean generation matching your physical hard drive structure:

   ```bash
   sudo nixos-generate-config --root /mnt
   ```
   
   2. Verify that it worked by viewing the file:
   
   ```bash
   cat /mnt/etc/nixos/hardware-configuration.nix
   ```
   
   Your fileSystems."/" block should now display an actual physical drive UUID with a type like ext4 or btrfs, and fileSystems."/boot" should show your EFI drive path.

#### Step 3.4.3: Sync and Stage with Git
Because you wiped out the configuration directories under /mnt during re-mounting, make sure your customized configuration.nix and flake.nix are present in /mnt/etc/nixos/. If they were lost during the unmount process, re-copy them from your cloning phase or modify them quickly to match what we fixed earlier.
Once your files are verified inside /mnt/etc/nixos/, track them with Git:

```bash
cd /mnt/etc/nixos
sudo git init
sudo git add hardware-configuration.nix configuration.nix flake.nix
```

#### Step 3.4.4: Finalize the Installation
Run the installer script:

```bash
sudo nixos-install --flake /mnt/etc/nixos#beast-kf
```

If nixos-generate-config still outputs tmpfs blocks or if you are unsure which partition targets are correct, please run lsblk and paste the layout here. I can tell you exactly which partitions to mount.

#### Step 3.5: 🛠️ Final Steps: Post-Installation Clean Up

Before flipping the power switch, you must gracefully detach your physical partitions from the active live installer runtime to ensure no files get corrupted. Run these final commands:

##### 3.5.1. Step completely outside the mounted directory tree
```bash
cd ~
```

##### 3.5.2. Force all cached data in RAM to write out to your physical hard drive
```bash
sync
```

##### 3.5.3. Recursively unmount all target installation partitions safely
```bash
sudo umount -R /mnt
```

#### Step 3.6: 🚀 Booting Into Your Secure AI Workstation

Now you are clear to restart your machine:

```bash
sudo reboot
```

or

```bash
sudo systemctl reboot -i
```

Remove the USB drive when the screen goes black. Your laptop now boots into your personal AI-native NixOS.

---

## 🚀 Phase 4: First Boot, Passwords & Safety Verification

### Step 4.1: Secure the Accounts
1. Log into the desktop as **`roman`** with the initial password `ChangeThisPassword123!`.
2. Open a terminal (`konsole`/`gnome-terminal`) and **immediately change both passwords**:
   ```bash
   passwd                                   # changes romans password
   sudo passwd ai-agent                     # sets a new password for the AI worker
   ```
3. Confirm your system is tracking GitHub:
   ```bash
   cd /etc/nixos && sudo git status
   ```

### Step 4.2: Verify the LAN Sandbox Actually Works (Do Not Skip This)
```bash
# Jump into the restricted AI identity
sudo -i -u ai-agent

# TEST 1 — Public internet: MUST succeed
curl -s https://api.github.com | head -n 3

# TEST 2 — Your router/LAN: MUST fail with "No route to host" or a timeout
ping -c 2 192.168.1.1

# Return to your admin identity
exit
```
*If Test 1 fails or Test 2 succeeds, stop and re-check the firewall block and the `group = "ai-sandbox"` line in `configuration.nix` before doing any AI work.*

### Step 4.3: Pull Down the 70B Deep Reasoning Engine
As `roman`, open a terminal and run:

```bash
ollama run deepseek-r1:70b
```

#### What will happen behind the scenes:
1. The ~42GB quantized model downloads once (this can take a long time on first run — be patient and let it finish).
2. On startup, the system safely distributes the 70B architecture: roughly 14GB of layers load into the blazing-fast 16GB VRAM, and the rest slots into your 64GB system RAM.
3. **The model will take 1 to 2 minutes to initialize on first boot. This is normal! Do not cancel it.**
4. Once loaded, the prompt changes to `>>> Send a message`. Your engine is warm. When prompted, expect roughly 30–90 seconds of internal `<thought>` reasoning, then a steady response at about **2–5 tokens per second**.
5. During long coding sessions, the expanding KV context cache spills safely onto your dedicated **48GB NVMe swap file** — the machine will slow down before it ever crashes. That is by design.

Type `/bye` to exit the model chat.

---

## 📅 Daily Operational Workflow

### Workflow A: The Daily AI Engineering Routine
When you sit down to develop Python or front-end web apps with the unrestricted local model:

1. Log into your laptop as `roman`.
2. Open a terminal.
3. Safely jump into the restricted user environment:
   ```bash
   sudo -i -u ai-agent
   ```
4. Create (once) and enter your programming workspace:
   ```bash
   mkdir -p ~/projects/my-web-app
   cd ~/projects/my-web-app
   ```
5. Launch **Aider** against your local Ollama backend:
   ```bash
   aider --model ollama_chat/deepseek-r1:70b
   ```
   *(Ollama listens on `http://127.0.0.1:11434` automatically; loopback is expressly allowed through the sandbox. If you are on an older Aider release that doesn't know `ollama_chat/`, use the fallback form: `aider --model ollama/deepseek-r1:70b --openai-api-base http://localhost:11434/v1`.)*
6. **The Interaction Flow:**
   - Hitting enter triggers a short pause (30–60 seconds) while layers sync across VRAM and system RAM.
   - The deep, unrestricted `<thought>` log streams directly in your shell as it analyzes code.
   - Verified edits are written natively into your files — no corporate content filters blocking legitimate security tooling, scrapers, or low-level code.
   - **Network Check:** if the agent fetches a public library or documentation page, it succeeds. If anything ever tries to reach a LAN address, the kernel silently rejects the packet.

#### Can it research on the internet?
Yes, with an honest caveat: Aider is not an autonomous web-searching agent. Its superpower is the **`/web <url>`** command, which fetches and ingests a specific documentation page, GitHub issue, or article directly into the chat context:

```
/web https://docs.python.org/3/library/asyncio.html
```

Your workflow is: search in your browser (as `roman`), paste the URL into Aider with `/web`. All fetching happens from inside the `ai-agent` sandbox, so even research traffic can never touch your LAN.

### Workflow B: Normal Non-AI Routine
For standard maintenance, documents, banking, or browsing:
1. Log into your laptop as `roman`.
2. Work directly inside your native home folder (`/home/roman`).
3. You keep full system control via `sudo`. Your personal files are completely separate from the `ai-agent` home directory.

---

## 🔄 Updating the System (The Git Sync Loop)

Whenever you tweak the system (e.g. `sudoedit /etc/nixos/configuration.nix`), apply and back up in one clean loop:

```bash
cd /etc/nixos
sudo nixos-rebuild switch --flake .#beast-kf
sudo git add .
sudo git commit -m "update: system parameters modified"
sudo git push
```

The first command rebuilds and activates the system; the git commands keep your GitHub brain permanently in sync with the machine. If a rebuild ever breaks something, previous working generations remain available in the boot menu — reboot and pick an older entry.

---

## 🧠 Phase 5 (Advanced Optional Matrix): Spec-Driven Development with Coding Agents

*This section implements the approaches taught in the DeepLearning.AI short courses on Spec-Driven Development / Agentic AI. It is optional today, but it is the single biggest lever for getting professional results out of a local 70B model.*

Running a 70B model locally pushes against physical hardware bounds. Dumping an entire repository into the prompt bloats the context window, triggers swap, and slows the loop to a crawl. **Spec-Driven Development (SDD)** replaces unstructured "vibe coding" with a disciplined blueprint loop.

### The SDD Implementation Rules

1. **Maintain the Agent Constitution (`agents.md`):** keep a concise markdown file in the root of every project documenting the exact tech stack, file layout logic, coding conventions, and hard limits. This is the standing law the agent must obey.
2. **Write an Intent Specification (`todo.md` / `specification.md`):** before asking the model to code, write a small plain-text blueprint describing exactly what the feature must do — inputs, output structure, specific libraries, edge cases. Example:
   ```markdown
   - Goal: Build a Python CSV processing pipeline with string-split fallbacks.
   - Requirement: Malformed rows must be isolated and logged, never crash the run.
   - Constraint: Standard library only. No pandas.
   ```
3. **Never Dump Entire Repositories:** pass *only* the target file plus your spec files into Aider's context, using its `/add` command inside the session:
   ```
   /add current_script.py specification.md agents.md
   ```
   (or from the shell: `aider current_script.py specification.md`)
4. **Execute the Plan-Implement-Verify Lifecycle:**
   - **Plan:** prompt the model to state its intended design *in markdown text only* before touching code. The DeepSeek-R1 reasoning core spends its `<thought>` budget checking its own logic and edge cases.
   - **Implement:** once you approve the plan text, command the agent to apply the changes. Aider writes the edits directly into your files as clean, reviewable diffs.
   - **Verify:** run your test suite immediately (`pytest`, browser checks). If an exception fires, paste **only the stack trace** back into the chat — the 70B engine reads the log, rethinks its code path, and issues a patch inside the same loop.

By focusing on isolated specification files instead of full-repository context dumps, token bloat is eliminated, your memory lanes stay clean, and the laptop delivers consistent, unlimited coding performance.

---

## 🏆 Why This Setup Beats Claude Code, Cursor & Friends

*   **Total Speed & Control:** a clean pipeline straight to your local GPU with no laggy corporate cloud round-trips or visual frames.
*   **Zero Safety Filter Buffers:** ask the 70B model to write intensive security parsers or low-level scraping code and it simply constructs it. No cloud firewall throws a rejection banner at legitimate engineering work.
*   **Zero Bills:** prompt this setup for 16 hours straight — you will never receive a token usage statement.
*   **Total Privacy:** your code never leaves the laptop. The only outbound traffic is the documentation fetching you explicitly trigger — and even that is firewalled away from your LAN.

---

## 🩹 Troubleshooting & Important Notes

| Symptom | Likely Cause & Fix |
|---|---|
| Aider answers ignore large parts of my files | Context was truncated. Confirm `OLLAMA_CONTEXT_LENGTH = "16384"` is in the Ollama block, then `sudo nixos-rebuild switch --flake .#beast-kf`. |
| Everything is suddenly very slow during a long session | Expected: KV cache is spilling into the 48GB swap. Finish the prompt, then restart the Aider session to reset context. |
| `ai-agent` cannot reach the internet at all | Check Step 4.2 Test 1. If it fails, re-verify the firewall chain and that `group = "ai-sandbox"` is the user's **primary** group. |
| `ai-agent` cannot resolve any domain names | DNS is hitting the LAN router. Confirm `networking.nameservers = [ "1.1.1.1" "9.9.9.9" ];` is present and applied. |
| `ollama` uses the CPU instead of the GPU | PRIME offload quirk. Try `nvidia-offload ollama serve` manually, or comment out the `prime = { ... }` block and rebuild (dGPU always-on; slightly worse battery). |
| A rebuild broke the system | Reboot, select an older generation from the systemd-boot menu, fix the config, rebuild again. NixOS keeps every previous working system. |
| First `ollama run` seems stuck for 1–2 minutes | Normal. A 70B quantized model is being mapped across VRAM and RAM. Do not cancel it. |

---

## 📎 Appendix: Document Lineage & Merge Notes

This FINAL edition consolidates three predecessor documents. Content restored from earlier drafts: the hardware prerequisites table, the full "grandma" GitHub/bootstrap walkthrough (editor keystrokes, boot keys, unfree-software checkbox), the behind-the-scenes model boot explanation, the Aider-vs-Claude-Code rationale, and the `specification.md`/`todo.md` SDD blueprint examples. Content kept from the latest draft: the dual-user security model, daily workflows, PRIME offload, and flake-based installation.

Corrections applied during consolidation (previously latent defects):

1. **Sandbox group fix:** `ai-sandbox` is now the *primary* group of `ai-agent`. As a supplementary group, the `iptables --gid-owner` rule never matched and the LAN isolation silently did nothing.
2. **Desktop environment restored:** the previous draft's `configuration.nix` omitted GNOME, NetworkManager, timezone and locale — the first rebuild would have removed the graphical desktop.
3. **DNS independence:** public nameservers added; otherwise the sandboxed user's DNS queries would have been dropped at the router (a LAN address), breaking internet access entirely.
4. **Context length:** `OLLAMA_CONTEXT_LENGTH = "16384"` added — Ollama's ~2–4k default silently truncates code files fed through Aider.
5. **Aider invocation updated** to the officially recommended `ollama_chat/` route, with the older `--openai-api-base` form retained as a fallback.
6. **Installation flow cleaned up:** the generated `hardware-configuration.nix` is now committed back to the repo, making the GitHub copy complete and the whole system reproducible from scratch.
7. 

## Phase 6: 🎨 The Ultimate NixOS Theme-Switching Guide

Because your configuration.nix is fully automated, switching between any of your 55+ themes takes only a single string change. The theme engine will automatically download the correct wallpaper from the repository and re-skin your whole operating system (GNOME, WezTerm, VS Code, etc.) to match the color scheme.
------------------------------
## Step-by-Step Procedure
Follow these sequential steps whenever you want to swap looks:

   1. Open your configuration file
   Launch your preferred terminal and open your system file with administrative rights:
   
```bash
   sudo nano /etc/nixos/configuration.nix
   ```
   
   2. Select your active theme
   Scroll to the very top of the file and locate the activeTheme variable (around line 7). Change its value to any theme name from your list:
   
```bash
   activeTheme = "tokyo-night"; # Change "gruvbox" to "dracula", "nord", etc.
   ```
   
   3. Trigger the Nix build
   Save the file (Ctrl+O, Enter, then Ctrl+X to exit) and run your system rebuild command:
   
```bash
   sudo nixos-rebuild switch --flake .#beast-kf
   ```
   
   4. Update the cryptographic hash (If Prompted)
   Because Nix demands absolute security for network downloads, switching to a theme you haven't used before will cause the compiler to halt with a Hash Mismatch Error.
   * Look at the terminal error output.
      * Locate the long alphanumeric string marked got: sha256-xxxxxxxx....
      * Re-open your file (sudo nano /etc/nixos/configuration.nix).
      * Scroll down to the bottom stylix block and replace the empty string or old hash inside sha256 = "..." with the new one you just copied.
      * Run the rebuild command one final time.
   
------------------------------
### Quick Selection Reference Matrix
Here are a few popular target presets you can drop straight into the activeTheme = "..."; string at the top of your file:

| Theme Key Target | Aesthetic Profile | Primary Color Foundation |
|---|---|---|
| "gruvbox" | Retro Earth Tones (Default) | Warm Browns, Pastel Greens & Oranges |
| "catppuccin-mocha" | Modern Soft Dark Pastel | Deep Dark Grey, Soothing Pastel Pinks & Blues |
| "tokyo-night" | Cyberpunk Neon City | Deep Dark Blue, Bright Magenta & Cyan Accents |
| "dracula" | Classic High-Contrast Vampire | Near-Black Purple, Vibrant Pinks & Greens |
| "nord" | Arctic Frost Minimalist | Clean Slate Blues, Muted Ice White & Teal |
| "cyberpunk" | Retro-Futuristic Glow | Pitch Black, Striking Neon Yellows & Reds |
| "everforest" | Organic Forest Wilderness | Soft Muted Green, Warm Sepia Highlights |

### The Themes got inspired in the:

https://github.com/librephoenix/nixos-config

and the wallpapers were extracted using the following approach:

   1. A plain, standalone image link pointing to a .png file representing the screenshot: [[https://githubusercontent.com]]
   2. An explicit hyperlink descriptive pair pointing to the wallpaper image file using the custom text definition: [[https://...][Background Link]]

## The Automated Theme Multi-Asset Downloader Script
This robust, tailored bash script loops through the repository assets, parses both URL targets from the individual README.org files using the exact layout rules you provided, and streams the files down properly.
Run this command inside your terminal at /etc/nixos/:

#### 1. Clear out any legacy configurations and establish a clean asset tree
```bash

sudo rm -rf wallpapers
sudo mkdir -p wallpapers
```

#### 2. Pull down the clean target source repository tree into a temporary environment workspace
```bash
git clone --depth 1 https://github.com /tmp/librephoenix-source
```

#### 3. Enter the target themes asset catalog folder
```bash
cd /tmp/librephoenix-source/modules/themes
```

#### 4. Loop through every individual theme directory
```bash
for theme_dir in *; do
  if [ -d "$theme_dir" ] && [ -f "$theme_dir/README.org" ]; then
    echo "Processing configuration matrix for theme: ${theme_dir}..."

    # Extract the true source wallpaper link (the URL right before '[Background Link]')
    wallpaper_url=$(grep -oE '\[\[https?://[^]]+\]\[Background Link\]\]' "$theme_dir/README.org" | sed -E 's/\[\[([^]]+)\]\[Background Link\]\]/\1/')

    # Extract the screenshot link (the standalone raw.githubusercontent png link)
    screenshot_url=$(grep -oE '\[\[https://raw\.githubusercontent\.com/[^]]+\.png\]\]' "$theme_dir/README.org" | tr -d '[]')

    # Download the true customized wallpaper image asset if found
    if [ ! -z "$wallpaper_url" ]; then
      echo "  -> Fetching wallpaper..."
      sudo curl -L "$wallpaper_url" -o "/etc/nixos/wallpapers/${theme_dir}.png"
    fi

    # Download the structural screenshot asset if found
    if [ ! -z "$screenshot_url" ]; then
      echo "  -> Fetching screenshot rice showcase..."
      sudo curl -L "$screenshot_url" -o "/etc/nixos/wallpapers/${theme_dir}-screenshots.png"
    fi
  fi
done
```

#### 5. Return to the configuration tree home and delete temporary file paths safely
```bash
cd /etc/nixos
rm -rf /tmp/librephoenix-source
```

------------------------------
#### Verifying Your New Asset Layout Matrix
Once the script finishes downloading all 50+ entries, run a file listing check:

```bash
ll wallpapers/
```

You will now see a layout containing the custom distinct files matching the schema you explicitly outlined:

* 
* old-hope.png (The actual wallpaper background)
* old-hope-screenshots.png (The corresponding configuration showcase preview)
* gruvbox.png / gruvbox-screenshots.png
* tokyo-night.png / tokyo-night-screenshots.png
* 

## Extract and copy the entire theme directory from the Nix store into your repo

### Copy All Theme YAML Files to Your Repo

Run this command block inside your /etc/nixos/ terminal. It will locate the active base16-schemes directory in your environment and copy the entire theme sheet layout array straight into your repo:
```bash
cd /etc/nixos
```

#### 1. Create a dedicated directory for your YAML color palettes
```bash
sudo mkdir -p themes
```

#### 2. Extract and copy the entire theme directory from the Nix store into your repo
```bash
sudo cp -r $(nix-build "<nixpkgs>" -A base16-schemes --no-out-link)/share/themes/. ./themes/
```

#### 3. Fix the permissions so they match your user profile workspace
```bash
sudo chmod -R 644 ./themes/*
```

#### 4. Tell Git to start tracking the files
```bash
git add themes/
```

(If you run ll themes/, you will now see files like gruvbox-dark-hard.yaml and dracula.yaml living directly in your configuration directory!)

### NOTE !!!

Yes, you do need to update or refresh your flake context, but only once to pull in the newly added stylix tool code into your local environment.
Because we added a completely new external input to your architecture (github:danth/stylix), your current flake.lock file does not yet know how to find it or verify its security signatures.
Follow these step-by-step actions to download the styling code and apply your setup without encountering evaluation errors:

### 1. Add untracked files to Git (Mandatory if inside a Git Repository)
   If your directory /etc/nixos/ or ~/_/pprgb is managed by Git, Nix flakes will completely ignore your new configuration files unless they are tracked. Ensure they are staged:
   
```bash
   git add flake.nix configuration.nix
   ```
   
### 2. Update your Flake input lockfile
   Navigate to your project setup directory and run this command. This tells Nix to read your new flake.nix file, fetch the stylix repository source code, and lock down its exact version:
   
```bash
   nix flake update
   ```
   
### 3. Rebuild your workstation configuration
   With the locks successfully updated, trigger the installation profile to apply your theme:
   
```bash
   sudo nixos-rebuild switch --flake .#beast-kf
```
  
