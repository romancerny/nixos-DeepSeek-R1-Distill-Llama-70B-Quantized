{ config, pkgs, ... }:

{
  home.username = "roman";
  home.homeDirectory = "/home/roman";
  home.stateVersion = "24.11"; 

  programs.home-manager.enable = true;

  # 🚀 PURE NATIVE STARSHIP PROMPT CONFIGURATION
  programs.starship = {
    enable = true;
    enableZshIntegration = true;

    settings = {
      # 🌟 PERFECT SEQUENCE: Location -> Git -> Nix Snowflake -> CPU -> RAM -> Command Arrow
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

      # 🧠 BULLETPROOF DYNAMIC RAM ENGINE
      custom.ram_usage = {
        when = "true";
        command = ''
          free | awk '/Mem:/ {
            used=$3/1024/1024;
            pct=int(($3/$2)*100);
            
            if (pct >= 90)      color="#f04040"; # Vibrant Red
            else if (pct >= 80) color="#f0f000"; # Vibrant Yellow
            else                color="#40e040"; # Vibrant Green
            
            # The backslash before the pipe splits the text from the color cleanly for Starship
            printf "%.1fGB (%d%%)\\|%s\n", used, pct, color;
          }'
        '';
        format = "[🧠 \${output text}](bold \${output color}) ";
      };

      # ⚡ DYNAMIC DIFFERENTIAL CPU ENGINE
      custom.cpu_usage = {
        when = "true";
        command = ''
          # Reads metrics instantly from the kernel status lines
          read -r _ u1 n1 s1 i1 io1 ir1 si1 st1 _ < /proc/stat
          sleep 0.05
          read -r _ u2 n2 s2 i2 io2 ir2 si2 st2 _ < /proc/stat
          
          prev_idle=$((i1 + io1))
          idle=$((i2 + io2))
          prev_total=$((u1 + n1 + s1 + i1 + io1 + ir1 + si1 + st1))
          total=$((u2 + n2 + s2 + i2 + io2 + ir2 + si2 + st2))
          
          diff_idle=$((idle - prev_idle))
          diff_total=$((total - prev_total))
          
          if [ "$diff_total" -eq 0 ]; then
            pct=0
          else
            pct=$(( 100 * (diff_total - diff_idle) / diff_total ))
          fi
          
          if [ "$pct" -ge 90 ]; then      color="#f04040"
          elif [ "$pct" -ge 80 ]; then    color="#f0f000"
          else                            color="#40e040"
          fi
          
          printf "%d%%\\|%s\n" "$pct" "$color"
        '';
        format = "[⚡ \${output text}](bold \${output color}) ";
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
