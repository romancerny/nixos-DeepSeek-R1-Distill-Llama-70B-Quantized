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

      # 🧠 BULLETPROOF DYNAMIC COLOR-SHIFTING RAM MODULE
      custom.ram_usage = {
        when = "true";
        command = ''
          free | awk '/Mem:/ {
            used=$3/1024/1024;
            pct=int(($3/$2)*100);
            
            # Pure literal string formatting
            if (pct >= 90)      print "\033[1;31musing 🧠 " sprintf("%.1fGB (%d%%)", used, pct) "\033[0m ";
            else if (pct >= 80) print "\033[1;33musing 🧠 " sprintf("%.1fGB (%d%%)", used, pct) "\033[0m ";
            else                print "\033[1;32musing 🧠 " sprintf("%.1fGB (%d%%)", used, pct) "\033[0m ";
          }'
        '';
        format = "$output";
      };

      # ⚡ BULLETPROOF DYNAMIC COLOR-SHIFTING CPU MODULE
      custom.cpu_usage = {
        when = "true";
        command = ''
          # Reads real-time instantaneous system load delta metrics safely from the system kernel
          read -r cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat
          
          # Calculate current active and total blocks
          prev_active=$((user + nice + system + irq + softirq + steal))
          prev_total=$((prev_active + idle + iowait))
          
          # Micro-sleep delta to measure processing cycle movements accurately
          sleep 0.1
          
          read -r cpu user nice system idle iowait irq softirq steal guest guest_nice < /proc/stat
          active=$((user + nice + system + irq + softirq + steal))
          total=$((active + idle + iowait))
          
          # Evaluate load percentage over the measured temporal gap
          pct=$(( (active - prev_active) * 100 / (total - prev_total) ))
          
          if [ "''$pct" -ge 90 ]; then
            printf "\033[1;31mat ⚡ %d%%\033[0m " "''$pct"
          elif [ "''$pct" -ge 80 ]; then
            printf "\033[1;33mat ⚡ %d%%\033[0m " "''$pct"
          else
            printf "\033[1;32mat ⚡ %d%%\033[0m " "''$pct"
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
