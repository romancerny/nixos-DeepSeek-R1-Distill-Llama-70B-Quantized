{ config, pkgs, lib, ... }:

let
  # ---------------------------------------------------------------------
  # 🎨 THEME AUTOMATION MATRIX
  # Change this single string to ANY folder/theme name in the catalog!
  # Examples: "gruvbox", "catppuccin-mocha", "tokyo-night", "dracula", "nord", "cyberpunk"
  # ---------------------------------------------------------------------
  activeTheme = "gruvbox"; 

  # Comprehensive mapping engine that connects all 55+ themes to their base16 yaml names
  themeSchemeMap = {
    "abyss"                  = "abyss";
    "amiga"                  = "amiga";
    "aperitive"              = "aperitive";
    "apple-classic"          = "apple-classic";
    "ashes"                  = "ashes";
    "atarist"                = "atarist";
    "atelier-cave"           = "atelier-cave";
    "atelier-dune"           = "atelier-dune";
    "atelier-estuary"        = "atelier-estuary";
    "atelier-forest"         = "atelier-forest";
    "atelier-heath"          = "atelier-heath";
    "atelier-lakeside"       = "atelier-lakeside";
    "atelier-plateau"        = "atelier-plateau";
    "atelier-savanna"        = "atelier-savanna";
    "atelier-seaside"        = "atelier-seaside";
    "atelier-sulphurpool"    = "atelier-sulphurpool";
    "ayu-dark"               = "ayu-dark";
    "ayu-light"              = "ayu-light";
    "ayu-mirage"             = "ayu-mirage";
    "bespin"                 = "bespin";
    "black-metal"            = "black-metal";
    "catppuccin-frappe"      = "catppuccin-frappe";
    "catppuccin-latte"       = "catppuccin-latte";
    "catppuccin-macchiato"   = "catppuccin-macchiato";
    "catppuccin-mocha"      = "catppuccin-mocha";
    "chalk"                  = "chalk";
    "classic-dark"           = "classic-dark";
    "classic-light"          = "classic-light";
    "codeschool"             = "codeschool";
    "cyberpunk"              = "cyberpunk";
    "decaf"                  = "decaf";
    "default-dark"           = "default-dark";
    "default-light"          = "default-light";
    "dracula"                = "dracula";
    "eighties"               = "eighties";
    "ember"                  = "ember";
    "espresso"               = "espresso";
    "everforest"             = "everforest";
    "everforest-light"       = "everforest-light";
    "flat"                   = "flat";
    "forest"                 = "forest";
    "github"                 = "github";
    "google-dark"            = "google-dark";
    "google-light"           = "google-light";
    "gruvbox"                = "gruvbox-dark-hard";
    "gruvbox-light"          = "gruvbox-light-medium";
    "harmonic-dark"          = "harmonic-dark";
    "hopscotch"              = "hopscotch";
    "io"                     = "io";
    "isotope"                = "isotope";
    "marrakesh"              = "marrakesh";
    "materia"                = "materia";
    "mexico-light"           = "mexico-light";
    "miramare"               = "miramare";
    "mocha"                  = "mocha";
    "monokai"                = "monokai";
    "nord"                   = "nord";
    "nord-light"             = "nord-light";
    "ocean"                  = "ocean";
    "oceanic-next"           = "oceanic-next";
    "outrun"                 = "outrun";
    "paraiso"                = "paraiso";
    "railscasts"             = "railscasts";
    "rose-pine"              = "rose-pine";
    "rose-pine-moon"         = "rose-pine-moon";
    "rose-pine-dawn"         = "rose-pine-dawn";
    "shapeshifter"           = "shapeshifter";
    "snazzy"                 = "snazzy";
    "solarized-dark"         = "solarized-dark";
    "solarized-light"        = "solarized-light";
    "summerfruit-dark"       = "summerfruit-dark";
    "summerfruit-light"      = "summerfruit-light";
    "sweet-barbaro"          = "sweet-barbaro";
    "tender"                 = "tender";
    "tokyo-night"            = "tokyo-night";
    "tomorrow"               = "tomorrow";
    "tomorrow-night"         = "tomorrow-night";
    "twilight"               = "twilight";
    "zenburn"                = "zenburn";
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
  # 👥 DUAL-USER PROFILE DEFINITIONS
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
    git
    vim
    wget
    curl
    tmux
    gnumake
    python3
    python3Packages.pip
    nodejs                  
    vscode
    google-chrome
    aider-chat 

    # Newly Added Desktop Environments & Apps
    gossip                  
    discord                 
    virt-manager            
    sparrow                 
    gimp                    
    beebeep                 
    keepassxc               
    tor-browser
    # wezterm # commented - managed by module system below
  ];

  programs.wezterm = {
    enable = true;
    # We use the extraConfig parameter to append the Lua settings directly
    extraConfig = ''
      local wezterm = require 'wezterm'
      local config = wezterm.config_builder()
  
      -- CRITICAL FIX: Forces XWayland to prevent the tiny, unresizable window glitch on Wayland
      config.enable_wayland = false
      config.front_end = "WebGpu"
  
      -- Aesthetic and functional configurations matching the librephoenix setup
      config.hide_tab_bar_if_only_one_tab = true
      -- config.color_scheme = 'Catppuccin Mocha' -- Commented out: Theme automation handled dynamically by Stylix
      config.window_background_opacity = 0.9
      config.window_decorations = "RESIZE"
  
      return config
    '';
  };

  # ---------------------------------------------------------------------
  # 🎨 MODULAR THEMING SUBSYSTEM (Stylix Core Integration)
  # ---------------------------------------------------------------------
  stylix = {
    enable = true;
    polarity = "dark";
    
    targets.gnome.enable = true;
    targets.wezterm.enable = true; # Automatically injects your activeTheme matrix scheme into WezTerm

    # Dynamic local path lookup referencing the local folder asset matrix.
    # Nix evaluates relative paths natively, bypassing network fetch rules and sha256 checksum strings.
    image = ./. + "/wallpapers/${activeTheme}.png";

    # Dynamic base16 scheme path generation
    base16Scheme = "${pkgs.base16-schemes}/share/themes/${schemeName}.yaml";
  };

  system.stateVersion = "24.11";
}
