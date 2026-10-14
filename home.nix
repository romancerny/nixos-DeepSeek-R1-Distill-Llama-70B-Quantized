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
      format = "$directory$git_branch$nix_shell\${custom.cpu_usage}\${custom.ram_usage}$character";

      # ❄️ NATIVE NIX-SHELL / DEV-SHELL DETECTOR
      nix_shell = {
        disabled = false;
        symbol = "❄️ ";
        style = "bold blue";
        impure_msg = "impure";
        pure_msg = "pure";
        format = "via [$symbol$state]($style) ";
      };

      # 🧠 TRUECOLOR DYNAMIC RAM MODULE
      custom.ram_usage = {
        when = "true";
        command = ''
          free | awk '/Mem:/ {
            used=$3/1024/1024;
            pct=int(($3/$2)*100);
            
            # Explicit Truecolor RGB Escapes (Bypasses Stylix / Themes)
            green="\033[38;2;40;220;40m";
            yellow="\033[38;2;240;240;0m";
            red="\033[38;2;240;40;40m";
            reset="\033[0m";
            
            if (pct >= 90)      color=red;
            else if (pct >= 80) color=yellow;
            else                color=green;
            
            printf " %s🧠 %.1fGB (%d%%)%s ", color, used, pct, reset;
          }'
        '';
        format = "$output";
      };

      # ⚡ TRUECOLOR DYNAMIC CPU MODULE
      custom.cpu_usage = {
        when = "true";
        command = ''
          read -r cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat
          prev_active=$((user + nice + system + irq + softirq + steal))
          prev_total=$((prev_active + idle + iowait))
          
          sleep 0.1
          
          read -r cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat
          active=$((user + nice + system + irq + softirq + steal))
          total=$((active + idle + iowait))
          
          pct=$(( (active - prev_active) * 100 / (total - prev_total) ))
          
          # Explicit Truecolor RGB Escapes (Bypasses Stylix / Themes)
          green="\033[38;2;40;220;40m";
          yellow="\033[38;2;240;240;0m";
          red="\033[38;2;240;40;40m";
          reset="\033[0m";
          
          if [ "''$pct" -ge 90 ]; then
            printf " %s⚡ %d%%%s " "''$color" "''$pct" "''$reset"
          elif [ "''$pct" -ge 80 ]; then
            printf " %s⚡ %d%%%s " "''$yellow" "''$pct" "''$reset"
          else
            printf " %s⚡ %d%%%s " "''$green" "''$pct" "''$reset"
          fi
        '';
        format = "$output";
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
