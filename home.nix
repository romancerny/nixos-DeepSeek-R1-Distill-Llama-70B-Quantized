{ config, pkgs, ... }:

{
  home.username = "roman";
  home.homeDirectory = "/home/roman";
  home.stateVersion = "24.11"; 

  programs.home-manager.enable = true;

  # 🐚 ZSH SHELL PROFILE CONFIGURATION
  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;
    autocd = true;

    # Move your legacy aliases here to make them portable
    shellAliases = {
      ll = "ls -la";
      rebuild = "sudo nixos-rebuild switch --flake /etc/nixos/#beast-kf";
      gc = "nix-collect-garbage -d";
    };
  };

  # 🚀 STARSHIP PROMPT CONFIGURATION
  programs.starship = {
    enable = true;
    enableZshIntegration = true; # Seamlessly hooks into your Zsh shell context

    settings = {
      # Customises the overall visual sequence of your prompt layout
      format = "$directory$git_branch$nix_shell$memory_usage$character";

      # ❄️ NATIVE NIX-SHELL / DEV-SHELL DETECTOR
      nix_shell = {
        disabled = false;
        symbol = "❄️ ";
        style = "bold blue";
        impure_msg = "impure";
        pure_msg = "pure";
        format = "via [$symbol$state]($style) ";
      };

      # 🧠 DYNAMIC COLOR-SHIFTING RAM MODULE
      custom.ram_usage = {
        when = "true"; # Always execute
        symbol = "🧠 ";
        # Calculates percentage and formats with raw GB + % based on boundaries
        command = ''
          free | awk '/Mem:/ {
            used=$3/1024/1024; 
            total=$2/1024/1024; 
            pct=int(($3/$2)*100); 
            
            if (pct >= 90)      print "bold red|" sprintf("%.1fGB (%d%%)", used, pct);
            else if (pct >= 80) print "bold yellow|" sprintf("%.1fGB (%d%%)", used, pct);
            else                print "bold green|" sprintf("%.1fGB (%d%%)", used, pct);
          }'
        '';
        # Safely splits the color flag away from the text metric output
        format = "using [$symbol\${output text}](bold \${output color}) ";
      };

      # ⚡ DYNAMIC COLOR-SHIFTING CPU MODULE
      custom.cpu_usage = {
        when = "true"; # Always execute
        symbol = "⚡ ";
        # Reads CPU states instantly from /proc/stat to avoid slow command latency
        command = ''
          awk '/cpu / {
            idle=$5; 
            total=0; 
            for(i=2;i<=8;i++) total+=$i; 
            
            # Persist metrics across prompt renders to calculate true delta changes
            if (raw) {
              diff_idle=idle-prev_idle; 
              diff_total=total-prev_total; 
              pct=int(100*(diff_total-diff_idle)/diff_total);
            } else {
              pct=5; # Safe bootstrap fallback state
            }
            
            if (pct >= 90)      print "bold red|" pct "%";
            else if (pct >= 80) print "bold yellow|" pct "%";
            else                print "bold green|" pct "%";
          }' /proc/stat
        '';
        format = "at [$symbol\${output text}](bold \${output color}) ";
      };

      # Sets up standard crisp command prompt arrows at the end
      character = {
        success_symbol = "[➜](bold green)";
        error_symbol = "[➜](bold red)";
      };

      # Sleek, clean directory structure formatting
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
      config.enable_wayland = false
      config.front_end = "WebGpu"
      config.hide_tab_bar_if_only_one_tab = true
      config.window_background_opacity = 0.9
      config.window_decorations = "RESIZE"
      return config
    '';
  };

  # 🖥️ GNOME CUSTOM SHORTCUT ENGINE
  dconf.settings = {
    # Keep the default workspace behavior safe
    "org/gnome/mutter" = {
      "workspaces-only-on-primary" = true;
    };

    # Define the existence of custom keybinding slots
    "org/gnome/settings-daemon/plugins/media-keys" = {
      custom-keybindings = [
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0/"
        "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom1/"
      ];
    };

    # Binding Slot 0: Force-switch All Monitors Right
    "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom0" = {
      name = "Switch All Monitors Workspace Right";
      binding = "<Super><Alt>Right";
      command = "bash -c 'gsettings set org.gnome.mutter workspaces-only-on-primary false; dbus-send --session --type=method_call --dest=org.gnome.Shell /org/gnome/Shell org.gnome.Shell.Eval string:\"wm.actionMoveWorkspaceRight();\"'; gsettings set org.gnome.mutter workspaces-only-on-primary true";
    };

    # Binding Slot 1: Force-switch All Monitors Left
    "org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/custom1" = {
      name = "Switch All Monitors Workspace Left";
      binding = "<Super><Alt>Left";
      command = "bash -c 'gsettings set org.gnome.mutter workspaces-only-on-primary false; dbus-send --session --type=method_call --dest=org.gnome.Shell /org/gnome/Shell org.gnome.Shell.Eval string:\"wm.actionMoveWorkspaceLeft();\"'; gsettings set org.gnome.mutter workspaces-only-on-primary true";
    };
  };

  # Stylix targets block
  stylix.targets.wezterm.enable = true;

  # 🛠️ SILENCE WARNINGS: Prevents Stylix from trying to compile deprecated Rofi and QT options in your profile
  stylix.targets.rofi.enable = false;
  stylix.targets.qt.enable = false;
}
