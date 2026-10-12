{ config, pkgs, lib, ... }:

let
  # ---------------------------------------------------------------------
  # 🎨 THEME AUTOMATION MATRIX
  # Change this single string to ANY folder name in the librephoenix themes repo!
  # Popular options: "gruvbox", "catppuccin-mocha", "tokyonight", "dracula", "nord", "cyberpunk", "oceanic-next"
  # ---------------------------------------------------------------------
  activeTheme = "gruvbox"; 

  # Mapping engine that connects the theme name to the base16 scheme file name
  themeSchemeMap = {
    "gruvbox"          = "gruvbox-dark-hard";
    "catppuccin-mocha" = "catppuccin-mocha";
    "tokyonight"       = "tokyo-night";
    "dracula"          = "dracula";
    "nord"             = "nord";
    "cyberpunk"        = "cyberpunk";
    "oceanic-next"     = "oceanic-next";
    "rose-pine"        = "rose-pine";
    "everforest"       = "everforest";
    "sweet-barbaro"    = "sweet-barbaro";
    # Add any extra custom mappings here if the folder name differs from the yaml name
  };

  # Helper to resolve the YAML name. Fallback to the theme name if not explicitly mapped.
  schemeName = if builtins.hasAttr activeTheme themeSchemeMap 
               then themeSchemeMap.${activeTheme} 
               else activeTheme;
in
{
  imports = [
    ./hardware-configuration.nix # Auto-generated during install (Phase 3)
  ];

  # Enable experimental Flakes mechanics
  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # Permit proprietary packages (NVIDIA drivers, Discord, Google Chrome)
  nixpkgs.config.allowUnfree = true;

  # Core Bootloader Setup (modern UEFI)
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  networking.hostName = "beast-kf";
  networking.networkmanager.enable = true;

  # IMPORTANT SANDBOX DETAIL: use public DNS resolvers system-wide.
  networking.nameservers = [ "1.1.1.1" "9.9.9.9" ];

  time.timeZone = "Europe/London";
  i18n.defaultLocale = "en_GB.UTF-8";

  # Desktop Environment (must match what you pick in the Phase 2 installer)
  services.xserver.enable = true;
  services.displayManager.gdm.enable = true;
  services.desktopManager.gnome.enable = true;

  # ---------------------------------------------------------------------
  # 🚂 MEMORY MATRIX: Overcoming the 64GB Hardware Boundary
  # ---------------------------------------------------------------------
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
  # 🖥️ VIRTUALIZATION & BACKGROUND DAEMONS
  # ---------------------------------------------------------------------
  virtualisation.libvirtd.enable = true;
  programs.virt-manager.enable = true;

  # Required background Tor daemon service
  services.tor.enable = true;
  services.tor.client.enable = true;

  # ---------------------------------------------------------------------
  # 🔒 FIREWALL & LAN NETWORK ISOLATION SANDBOX (Strict Safety)
  # ---------------------------------------------------------------------
  users.groups.ai-sandbox = {};

  networking.firewall = {
    enable = true;
    extraCommands = ''
      iptables -F AI_SANDBOX_CHAIN 2>/dev/null || iptables -N AI_SANDBOX_CHAIN
      iptables -C OUTPUT -m owner --gid-owner ai-sandbox -j AI_SANDBOX_CHAIN 2>/dev/null || \
        iptables -I OUTPUT 1 -m owner --gid-owner ai-sandbox -j AI_SANDBOX_CHAIN
      iptables -A AI_SANDBOX_CHAIN -o lo -j ACCEPT
      iptables -A AI_SANDBOX_CHAIN -d 10.0.0.0/8 -j REJECT --reject-with icmp-net-prohibited
      iptables -A AI_SANDBOX_CHAIN -d 172.16.0.0/12 -j REJECT --reject-with icmp-net-prohibited
      iptables -A AI_SANDBOX_CHAIN -d 192.168.0.0/16 -j REJECT --reject-with icmp-net-prohibited
      iptables -A AI_SANDBOX_CHAIN -d 169.254.0.0/16 -j REJECT --reject-with icmp-net-prohibited
      iptables -A AI_SANDBOX_CHAIN -j ACCEPT
    '';
  };

  # ---------------------------------------------------------------------
  # 👥 DUAL-USER PROFILE DEFINITIONS (Admin vs Unprivileged Isolation)
  # ---------------------------------------------------------------------
  users.users = {
    roman = {
      isNormalUser = true;
      description = "Roman System Administrator";
      extraGroups = [ "networkmanager" "wheel" "video" "libvirtd" ]; 
      shell = pkgs.bash;
      initialPassword = "ChangeThisPassword123!"; 
    };

    ai-agent = {
      isNormalUser = true;
      description = "Isolated AI Execution Worker";
      group = "ai-sandbox";
      shell = pkgs.bash;
      initialPassword = "ChangeThisPassword456!"; 
    };
  };

  # Core developer packages and requested desktop apps available to all users
  environment.systemPackages = with pkgs; [
    # Existing Developer Core & Languages
    git
    vim
    wget
    curl
    tmux
    gnumake
    python3
    python3Packages.pip
    nodejs                  # Installed alongside Python as requested
    vscode
    google-chrome
    aider-chat 

    # Newly Added Desktop Environments & Apps
    wezterm                 
    gossip                  
    discord                 
    virt-manager            
    sparrow                 
    gimp                    
    beebeep                 
    keepassxc               
    tor-browser             
  ];

  # ---------------------------------------------------------------------
  # 🎨 MODULAR THEMING SUBSYSTEM (Stylix Core Integration)
  # ---------------------------------------------------------------------
  stylix = {
    enable = true;
    polarity = "dark";
    
    # Target systems automatically generated across environments
    targets.gnome.enable = true;
    targets.wezterm.enable = true;

    # Dynamic image resolution: Fetches the background asset directly based on the active theme
    image = pkgs.fetchurl {
      url = "https://githubusercontent.com{activeTheme}.png";
      # Setting sha256 to an empty string tells Nix to compute the cryptographic verification check dynamically
      sha256 = ""; 
    };

    # Dynamic base16 scheme path generation
    base16Scheme = "${pkgs.base16-schemes}/share/themes/${schemeName}.yaml";
  };

  system.stateVersion = "24.11";
}
