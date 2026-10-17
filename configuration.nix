{ config, pkgs, lib, ... }:

let
  activeTheme = "miramare"; 

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

  schemeName = if builtins.hasAttr activeTheme themeSchemeMap 
               then themeSchemeMap.${activeTheme} 
               else activeTheme;
in
{
  imports = [
    ./hardware-configuration.nix
  ];

  nix.settings.experimental-features = [ "nix-command" "flakes" ];
  nixpkgs.config.allowUnfree = true;

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  networking.hostName = "beast-kf";
  networking.networkmanager.enable = true;
  networking.nameservers = [ "1.1.1.1" "9.9.9.9" ];

  time.timeZone = "Europe/London";
  i18n.defaultLocale = "en_GB.UTF-8";

  # 💻 SWAY & GREETD
  services.xserver.enable = false; 
  
  programs.sway = {
    enable = true;
    extraOptions = [ "--unsupported-gpu" ];
    extraPackages = with pkgs; [
      swaylock
      swayidle
      wl-clipboard
      mako 
      alacritty
      # 🌟 FIXED: Ensures the background layout package is present to stop Stylix wallpaper rendering hangs
      swaybg 
    ];
  };

  services.greetd = {
    enable = true;
    settings = {
      default_session = {
        command = "${pkgs.tuigreet}/bin/tuigreet --time --remember --cmd 'sway --unsupported-gpu'";
        user = "greeter";
      };
    };
  };

  services.dbus.enable = true;
  xdg.portal = {
    enable = true;
    wlr.enable = true;
    extraPortals = [ pkgs.xdg-desktop-portal-wlr ];
  };

  # 🚂 MEMORY MATRIX
  swapDevices = [ {
    device = "/var/lib/swapfile";
    size = 48 * 1024; 
  } ];

  # 🎮 NVIDIA GRAPHICS STACK
  hardware.graphics.enable = true;
  services.xserver.videoDrivers = [ "nvidia" ];

  # 🖥️ UNIFIED SYSTEM ENVIRONMENT VARIABLES
  environment.sessionVariables = {
    # 🌐 PLAYWRIGHT SCRAPING REDIRECTION FOR AIDER
    PLAYWRIGHT_BROWSERS_PATH = "${pkgs.playwright-driver.browsers}";

    # GRAPHICS SUB-SYSTEM PATHWAYS
    NIXOS_OZONE_GFX_ACCELERATION = "1";
    XDG_SESSION_TYPE = "wayland";
    XDG_CURRENT_DESKTOP = "sway";
    MOZ_ENABLE_WAYLAND = "1";
    WLR_NO_HARDWARE_CURSORS = "1"; 
    WLR_RENDERER = "vulkan";
    GBM_BACKEND = "nvidia-drm";
    __GLX_VENDOR_LIBRARY_NAME = "nvidia";
  };

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

  # 🐋 OLLAMA HARDWARE INFERENCE LAYER
  services.ollama = {
    enable = true;
    package = pkgs.ollama-cuda; 
    environmentVariables = {
      OLLAMA_FLASH_ATTENTION = "1";   
      OLLAMA_NUM_PARALLEL = "1";      
      OLLAMA_CONTEXT_LENGTH = "16384"; 
    };
  };

  virtualisation.libvirtd.enable = true;
  programs.virt-manager.enable = true;
  services.tor.enable = true;
  services.tor.client.enable = true;

  # 🔒 FIREWALL & LAN NETWORK ISOLATION SANDBOX
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

  # 👥 DUAL-USER PROFILE DEFINITIONS
  programs.zsh.enable = true;
  users.users = {
    roman = {
      isNormalUser = true;
      description = "Roman System Administrator";
      extraGroups = [ "networkmanager" "wheel" "video" "libvirtd" "input" "tty" ]; 
      shell = pkgs.zsh;
      initialPassword = "ChangeThisPassword123!"; 
    };
    ai-agent = {
      isNormalUser = true;
      description = "Isolated AI Execution Worker";
      group = "ai-sandbox";
      shell = pkgs.zsh;
      initialPassword = "ChangeThisPassword456!"; 
    };
  };

  # 📦 DECLARED SYSTEM APPLICATIONS
  environment.systemPackages = with pkgs; [
    # Baseline tools
    git vim wget htop curl tmux gnumake python3 python3Packages.pip nodejs                  
    vscode google-chrome gossip discord virt-manager sparrow                    
    gimp beebeep keepassxc tor-browser kdePackages.kate pkgs."aider-chat"
    wireplumber nmap
    
    # Telemetry Layer
    btop
    nvtopPackages.full
    iotop

    # Headless Automation Engines for Aider /web scraping
    playwright-driver
    playwright
  ];

  # 🎨 MODULAR THEMING SUBSYSTEM
  stylix = {
    enable = true;
    polarity = "dark";
    targets.gnome.enable = false;
    targets.qt.enable = false;
    image = ./. + "/wallpapers/${schemeName}.png";
    base16Scheme = let
      targetPath = ./. + "/themes/${schemeName}.yaml";
      fallbackPath = ./. + "/themes/gruvbox-dark-hard.yaml";
    in
      if builtins.pathExists targetPath then targetPath else fallbackPath;
  };

  system.stateVersion = "24.11";
}
