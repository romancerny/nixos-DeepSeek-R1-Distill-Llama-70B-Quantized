{ config, pkgs, lib, ... }:

{
  imports = [
    ./hardware-configuration.nix # Auto-generated during install (Phase 3)
  ];

  # Enable experimental Flakes mechanics
  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # Permit proprietary packages (NVIDIA drivers)
  nixpkgs.config.allowUnfree = true;

  # Core Bootloader Setup (modern UEFI)
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  networking.hostName = "beast-kf";
  networking.networkmanager.enable = true;

  # IMPORTANT SANDBOX DETAIL: use public DNS resolvers system-wide.
  # Home DNS normally goes through the router (a LAN address), which the
  # sandbox firewall drops for the ai-agent user. Public DNS means the
  # sandboxed user never needs to touch the LAN for anything.
  networking.nameservers = [ "1.1.1.1" "9.9.9.9" ];

  time.timeZone = "Europe/London";
  i18n.defaultLocale = "en_GB.UTF-8";

  # Desktop Environment (must match what you pick in the Phase 2 installer)
  services.xserver.enable = true;
  services.displayManager.gdm.enable = true;
  services.desktopManager.gnome.enable = true;
  # KDE Plasma alternative (if you chose Plasma in the installer, swap to these):
  # services.displayManager.sddm.enable = true;
  # services.desktopManager.plasma6.enable = true;

  # ---------------------------------------------------------------------
  # 🚂 MEMORY MATRIX: Overcoming the 64GB Hardware Boundary
  # ---------------------------------------------------------------------
  # A 48GB NVMe swap block cushions the 70B model's KV context cache spillover
  # and prevents Out-Of-Memory kernel panics during long coding sessions.
  swapDevices = [ {
    device = "/var/lib/swapfile";
    size = 48 * 1024; # 48 Gigabytes (value is in Megabytes)
  } ];

  # ---------------------------------------------------------------------
  # 🎮 NVIDIA GRAPHICS STACK (16GB RTX 3080 Laptop GPU)
  # ---------------------------------------------------------------------
  hardware.graphics.enable = true;
  services.xserver.videoDrivers = [ "nvidia" ];

  hardware.nvidia = {
    modesetting.enable = true;
    powerManagement.enable = false;
    open = false; # Proprietary driver = maximum CUDA stability on this generation
    nvidiaSettings = true;
    package = config.boot.kernelPackages.nvidiaPackages.stable;

    # Clevo hybrid-graphics bus IDs (verify with `lspci | grep -E 'VGA|3D'`
    # after install; these are the standard layout for this chassis)
    prime = {
      offload = {
        enable = true;
        enableOffloadCmd = true;
      };
      intelBusId = "PCI:0:2:0";
      nvidiaBusId = "PCI:1:0:0";
    };
  };

  # ---------------------------------------------------------------------
  # 🐋 OLLAMA HARDWARE INFERENCE LAYER
  # ---------------------------------------------------------------------
  services.ollama = {
    enable = true;
    package = pkgs.ollama-cuda; # Modern nixpkgs-unstable syntax for NVIDIA cards
    environmentVariables = {
      OLLAMA_FLASH_ATTENTION = "1";   # Cuts context KV cache footprint cleanly in half
      OLLAMA_NUM_PARALLEL = "1";      # Single-prompt prioritization, blocks memory spikes
      OLLAMA_CONTEXT_LENGTH = "16384"; # Prevents silent truncation of large code files
    };
  };

  # ---------------------------------------------------------------------
  # 🔒 FIREWALL & LAN NETWORK ISOLATION SANDBOX (Strict Safety)
  # ---------------------------------------------------------------------
  # Any process whose PRIMARY group is ai-sandbox gets full public internet,
  # but every packet toward a private network range is rejected by the kernel.
  users.groups.ai-sandbox = {};

  networking.firewall = {
    enable = true;
    extraCommands = ''
      # Flush the chain if it exists, otherwise create it (idempotent on reload)
      iptables -F AI_SANDBOX_CHAIN 2>/dev/null || iptables -N AI_SANDBOX_CHAIN

      # Attach the chain once, at the top of the outbound path
      iptables -C OUTPUT -m owner --gid-owner ai-sandbox -j AI_SANDBOX_CHAIN 2>/dev/null || \
        iptables -I OUTPUT 1 -m owner --gid-owner ai-sandbox -j AI_SANDBOX_CHAIN

      # 1. Allow loopback so the agent can reach the local Ollama server (127.0.0.1:11434)
      iptables -A AI_SANDBOX_CHAIN -o lo -j ACCEPT

      # 2. Reject all outbound traffic to private/LAN infrastructure ranges
      iptables -A AI_SANDBOX_CHAIN -d 10.0.0.0/8 -j REJECT --reject-with icmp-net-prohibited
      iptables -A AI_SANDBOX_CHAIN -d 172.16.0.0/12 -j REJECT --reject-with icmp-net-prohibited
      iptables -A AI_SANDBOX_CHAIN -d 192.168.0.0/16 -j REJECT --reject-with icmp-net-prohibited
      iptables -A AI_SANDBOX_CHAIN -d 169.254.0.0/16 -j REJECT --reject-with icmp-net-prohibited

      # 3. Allow everything else (the public internet)
      iptables -A AI_SANDBOX_CHAIN -j ACCEPT
    '';
  };

  # ---------------------------------------------------------------------
  # 👥 DUAL-USER PROFILE DEFINITIONS (Admin vs Unprivileged Isolation)
  # ---------------------------------------------------------------------
  users.users = {
    # Primary Administrator Profile
    roman = {
      isNormalUser = true;
      description = "Roman System Administrator";
      extraGroups = [ "networkmanager" "wheel" "video" ]; # 'wheel' grants sudo
      shell = pkgs.bash;
      initialPassword = "ChangeThisPassword123!"; # Change immediately on first login
    };

    # Isolated Unprivileged Worker Profile
    ai-agent = {
      isNormalUser = true;
      description = "Isolated AI Execution Worker";
      # CRITICAL: ai-sandbox must be the PRIMARY group (not a supplementary one),
      # because the iptables --gid-owner match only sees a process's primary
      # group. This single line is what makes the LAN firewall actually apply.
      group = "ai-sandbox";
      # Deliberately NOT in 'wheel' — zero sudo capability.
      shell = pkgs.bash;
      initialPassword = "ChangeThisPassword456!"; # Change immediately on first login
    };
  };

  # Core developer packages available to all users
  environment.systemPackages = with pkgs; [
    git
    vim
    wget
    curl
    tmux
    gnumake
    python3
    python3Packages.pip
    vscode
    google-chrome
    aider-chat # Native terminal AI pair-programming agent engine
  ];

  system.stateVersion = "24.11";
}

