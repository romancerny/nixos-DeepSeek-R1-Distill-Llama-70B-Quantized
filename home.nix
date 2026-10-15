{ config, pkgs, ... }:

{
  home.username = "roman";
  home.homeDirectory = "/home/roman";
  home.stateVersion = "24.11"; 

  # --- INSERT THIS BLOCK FOR IOSKELEY MONO ---
  fonts.fontconfig.enable = true;
  home.packages = [
    (pkgs.stdenv.mkDerivation {
      pname = "ioskeley-mono";
      version = "2.1.0";

      src = pkgs.fetchurl {
        url = "https://github.com";
        # FIXED: Inserted the correct hash returned by the Nix daemon
        hash = "sha256-1DUWwt7RCTSZsw64xON1n8x2FhVW9jTz0Mqk7E8+k6A="; 
      };

      nativeBuildInputs = [ pkgs.unzip ];

      unpackPhase = "unzip $src";

      installPhase = ''
        mkdir -p $out/share/fonts/truetype
        cp *.ttf $out/share/fonts/truetype/
      '';
    })
  ];
  # --------------------------------------------

  programs.home-manager.enable = true;

  # 🐚 ZSH SHELL PROFILE CONFIGURATION
  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;
    autocd = true;
    shellAliases = {
      ll = "ls -la";
      rebuild = "sudo nixos-rebuild switch --flake /etc/nixos/#beast-kf";
      gc = "nix-collect-garbage -d";
    };
  };

  # 🚀 STARSHIP PROMPT CONFIGURATION
  programs.starship = {
    enable = true;
    enableZshIntegration = true;
    settings = {
      format = "$directory$git_branch$nix_shell\${custom.ram_usage}$character";
      nix_shell = {
        disabled = false;
        symbol = "❄️ ";
        style = "bold blue";
        impure_msg = "impure";
        pure_msg = "pure";
        format = "via [$symbol$state]($style) ";
      };
      custom.ram_usage = {
        when = "true";
        command = ''
          free -m | awk '/Mem:/ {
            used = int($3 / 1024 + 0.5);
            total = int($2 / 1024 + 0.5);
            pct = int(($3 / $2) * 100);
            printf "%d/%d GiB %d%%", used, total, pct;
          }'
        '';
        style = "bold #556b2f";
        format = "[🧠 $output]($style) ";
      };
      character = {
        success_symbol = "[➜](bold green)";
        error_symbol = "[➜](bold red)";
      };
      directory = {
        truncation_length = 3;
        style = "bold cyan";
      };
    };
  };

  # WezTerm settings block
  programs.wezterm = {
    enable = true;
    extraConfig = ''
      local wezterm = require 'wezterm'
      local config = wezterm.config_builder()
      
      -- Apply Ioskeley Mono Term
      config.font = wezterm.font("Ioskeley Mono Term")
      config.font_size = 13.0

      config.enable_wayland = true
      config.front_end = "WebGpu"
      config.hide_tab_bar_if_only_one_tab = true
      config.window_background_opacity = 0.9
      config.window_decorations = "RESIZE"
      return config
    '';
  };

  # 🖥️ NATIVE SWAY COMPOSITOR ENVIRONMENT MANAGEMENT
  wayland.windowManager.sway = {
    enable = true;
    config = {
      modifier = "Mod4"; 
      terminal = "wezterm";
      startup = [
        { command = "waybar"; }
      ];
      bars = [];
      
      output = {
        "HDMI-A-1" = {
          res = "3840x2160";
          scale = "1.5";
          pos = "0 0";
        };
      };

      input = {
        "type:keyboard" = {
          xkb_layout = "gb";
        };
      };

      keybindings = let 
        modifier = config.wayland.windowManager.sway.config.modifier;
      in pkgs.lib.mkOptionDefault {
        # 🌟 FIXED: Direct Sway native workspace navigation overrides (Goodbye Gnome!)
        "${modifier}+Mod1+Right" = "workspace next";
        "${modifier}+Mod1+Left" = "workspace prev";
        
        # 🌟 FIXED: Explicit terminal shortcut mapping to spin up your terminal immediately
        "${modifier}+Return" = "exec wezterm";
        
        "${modifier}+d" = "exec rofi -show drun";
        "${modifier}+Shift+e" = "exec swaymsg exit";
      };
    };
    
    extraSessionCommands = ''
      export SDL_VIDEODRIVER=wayland
      export QT_QPA_PLATFORM=wayland
      export QT_WAYLAND_DISABLE_WINDOWDECORATION="1";
      export _JAVA_AWT_WM_NONREPARENTING=1
    '';
  };

  # 🚀 ADVANCED CUSTOM POWERED ROFI ENGINE
  programs.rofi = {
    enable = true;
    package = pkgs.rofi; 
    plugins = [ pkgs.rofi-calc ];
    terminal = "wezterm";
    extraConfig = {
      modi = "drun,run,calc";
      show-icons = true;
      icon-theme = "Papirus";
      drun-format = "{name}";
      disable-history = false;
      sidebar-mode = false;
    };
    
    theme = let
      inherit (config.lib.formats.rasi) mkLiteral;
    in {
      "*" = {
        bg-color = mkLiteral "#141718ef";
        bg-alt = mkLiteral "#2d3133";
        fg-color = mkLiteral "#d1c7a3";
        fg-dim = mkLiteral "#706853";
        accent-color = mkLiteral "#a89984";
        
        background-color = mkLiteral "transparent";
        text-color = mkLiteral "@fg-color";
        font = "JetBrainsMono Nerd Font 11";
      };

      "window" = {
        location = mkLiteral "center";
        anchor = mkLiteral "center";
        fullscreen = mkLiteral "false";
        width = mkLiteral "640px";
        x-offset = mkLiteral "0px";
        y-offset = mkLiteral "0px";
        
        enabled = mkLiteral "true";
        border = mkLiteral "1px solid";
        border-color = mkLiteral "@accent-color";
        border-radius = mkLiteral "8px";
        background-color = mkLiteral "@bg-color";
        cursor = mkLiteral "default";
      };

      "mainbox" = {
        enabled = mkLiteral "true";
        spacing = mkLiteral "12px";
        padding = mkLiteral "24px";
        children = map mkLiteral [ "inputbar" "listview" ];
      };

      "inputbar" = {
        enabled = mkLiteral "true";
        spacing = mkLiteral "8px";
        children = map mkLiteral [ "prompt" "entry" ];
        background-color = mkLiteral "@bg-alt";
        border-radius = mkLiteral "6px";
        padding = mkLiteral "8px 12px";
      };

      "prompt" = {
        enabled = mkLiteral "true";
        text-color = mkLiteral "@accent-color";
        font = "JetBrainsMono Nerd Font Bold 11";
      };

      "entry" = {
        enabled = mkLiteral "true";
        placeholder = "Search Applications...";
        placeholder-color = mkLiteral "@fg-dim";
        cursor = mkLiteral "text";
      };

      "listview" = {
        enabled = mkLiteral "true";
        columns = mkLiteral "1";
        lines = mkLiteral "8";
        cycle = mkLiteral "true";
        dynamic = mkLiteral "true";
        scrollbar = mkLiteral "false";
        layout = mkLiteral "vertical";
        spacing = mkLiteral "6px";
        fixed-height = mkLiteral "true";
      };

      "element" = {
        enabled = mkLiteral "true";
        spacing = mkLiteral "10px";
        padding = mkLiteral "8px";
        border-radius = mkLiteral "4px";
        cursor = mkLiteral "pointer";
      };

      "element normal.normal" = {
        background-color = mkLiteral "transparent";
        text-color = mkLiteral "@fg-color";
      };

      "element selected.normal" = {
        background-color = mkLiteral "@bg-alt";
        text-color = mkLiteral "@fg-color";
        border = mkLiteral "1px solid";
        border-color = mkLiteral "@accent-color";
      };

      "element-icon" = {
        size = mkLiteral "24px";
        cursor = mkLiteral "inherit";
      };

      "element-text" = {
        vertical-align = mkLiteral "0.5";
        cursor = mkLiteral "inherit";
      };
    };
  };

  # 📊 COMPREHENSIVE WAYBAR METRIC DISPLAY SYSTEM
  programs.waybar = {
    enable = true;
    settings = {
      mainBar = {
        layer = "top";
        position = "top";
        height = 32;
        spacing = 4;

        modules-left = [ "custom/nix" "battery" "backlight" "pulseaudio" "pulseaudio#microphone" "cpu" "memory" ];
        modules-center = [ "sway/workspaces" ];
        modules-right = [ "custom/coffee" "clock" "network" ];

        "custom/nix" = { format = "❄️"; tooltip = false; };
        "battery" = {
          states = { warning = 30; critical = 15; };
          format = "{capacity}% 🔋";
          format-charging = "{capacity}% ⚡";
          format-plugged = "{capacity}% 🔌";
        };
        "backlight" = { format = "{percent}% 🌓"; };
        "pulseaudio" = { format = "{volume}% 🎧"; format-muted = "🔇"; };
        "pulseaudio#microphone" = {
          format = "{volume}% 🎙️";
          format-source-muted = "🎙️ MUTED";
          source = "default-audio-source";
        };
        "cpu" = { format = "{usage}% ⚙️"; tooltip = true; };
        "memory" = { format = "{percentage}% ☰"; tooltip = true; };

        "sway/workspaces" = {
          disable-scroll = true;
          all-outputs = true;
          format = "{icon} {name}";
          format-icons = {
            "1" = "🔖"; "2" = "🔄"; "3" = "💻"; "4" = "📁"; "5" = "🖌️";
            "6" = "⚙️"; "7" = "💵"; "8" = "🎓"; "9" = "🎮";
          };
        };

        "custom/coffee" = { format = "☕"; tooltip = false; };
        "clock" = { format = "{:%a %Y-%m-%d %I:%M:%S %p}"; interval = 1; };
        "network" = {
          format-wifi = "📶";
          format-ethernet = "🔌";
          format-disconnected = "⚠️";
          tooltip-format = "{ifname} via {gwaddr}";
        };
      };
    };

    style = ''
      window#waybar {
        background-color: rgba(20, 23, 24, 0.95);
        border-bottom: 1px solid #2d3133;
        color: #d1c7a3;
        font-family: "JetBrainsMono Nerd Font", monospace;
        font-size: 13px;
      }
      #modules-left, #modules-center, #modules-right { padding: 0 8px; }
      .modules-left > widget, .modules-right > widget { margin: 0 6px; }
      #workspaces button { padding: 0 6px; color: #706853; background-color: transparent; border: none; }
      #workspaces button.focused { color: #d1c7a3; border-bottom: 2px solid #a89984; }
      #workspaces button.urgent { color: #db4b4b; }
    '';
  };

  # Stylix targets block redirection
  stylix.targets.wezterm.enable = false;
  stylix.targets.sway.enable = true;
  stylix.targets.waybar.enable = true;

  stylix.targets.rofi.enable = false;
  stylix.targets.qt.enable = false;
}
