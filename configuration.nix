{ config, pkgs, lib, ... }:

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

  # Desktop Environment
  services.xserver.enable = true;
  services.displayManager.gdm.enable = true;
  services.desktopManager.gnome.enable = true;

  # ---------------------------------------------------------------------
  # 🚂 MEMORY MATRIX: Overcoming the 64GB Hardware Boundary
  # ---------------------------------------------------------------------
  swapDevices = [ {
    device = "/var/lib/swapfile";
    size = 48 * 1024; 
  } ];

  # ---------------------------------------------------------------------
  # 🎮 NVIDIA GRAPHICS STACK (16GB RTX 3080 Laptop GPU)
  # ---------------------------------------------------------------------
  hardware.graphics.enable = true;
  services.xserver.videoDrivers = [ "nvidia" ];

  hardware.nvidia = {
    modesetting.enable = true;
    powerManagement.enable = false;
    open = false; 
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
    package = pkgs.ollama-cuda; 
    environmentVariables = {
      OLLAMA_FLASH_ATTENTION = "1";   
      OLLAMA_NUM_PARALLEL = "1";      
      OLLAMA_CONTEXT_LENGTH = "16384"; 
    };
  };

  # ---------------------------------------------------------------------
  # 🖥️ VIRTUALIZATION & BACKGROUND DAEMONS
  # ---------------------------------------------------------------------
  virtualisation.libvirtd.enable = true;
  programs.virt-manager.enable = true;

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
    # Existing Developer Core & Requested Languages
    git
    vim
    wget
    curl
    tmux
    gnumake
    python3
    python3Packages.pip
    nodejs                  # <-- FIXED: Node.js and NPM are now permanently installed!
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
  # 🎨 SWITCHABLE THEME MECHANICS (LibrePhoenix/Stylix Core Setup)
  # ---------------------------------------------------------------------
  stylix = {
    enable = true;
    
    # 🌆 Wallpaper: Simply change this path to swap your background image!
    # Tip: You can fetch a cool wallpaper locally or point it to a file.
    image = pkgs.fetchurl {
      url = "https://githubusercontent.com";
      sha256 = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="; # Run configuration once to get the exact hash if broken
    };

    # 🎨 Color Schemes: Switch themes instantly here by changing the theme scheme.
    # Examples from base16: "gruvbox-dark-hard", "dracula", "nord", "oceanic-next"
    base16Scheme = "${pkgs.base16-schemes}/share/themes/gruvbox-dark-hard.yaml";

    # Force dark appearance across GNOME and applications
    polarity = "dark";
    
    # Automatically manages styles for your environments
    targets.gnome.enable = true;
    targets.wezterm.enable = true;
  };

  system.stateVersion = "24.11";
}
