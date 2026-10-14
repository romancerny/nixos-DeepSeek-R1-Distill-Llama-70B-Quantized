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

    # ⚡ NATIVE RENDER ENGINE: Calculates states instantly before drawing the prompt
    initExtra = ''
      # Fast file descriptor to parse CPU metrics without launching heavy subprocesses
      get_cpu_pct() {
        read -r _ u1 n1 s1 i1 io1 ir1 si1 st1 _ < /proc/stat
        # Short micro-sleep to capture real delta spikes accurately
        (sysbench --threads=1 --time=1 cpu run > /dev/null 2>&1 &) 2>/dev/null
        read -r _ u2 n2 s2 i2 io2 ir2 si2 st2 _ < /proc/stat
        
        local idle1=$((i1 + io1))
        local idle2=$((i2 + io2))
        local total1=$((u1 + n1 + s1 + i1 + io1 + ir1 + si1 + st1))
        local total2=$((u2 + n2 + s2 + i2 + io2 + ir2 + si2 + st2))
        
        local diff_idle=$((idle2 - idle1))
        local diff_total=$((total2 - total1))
        
        if [ "$diff_total" -eq 0 ]; then
          echo 0
        else
          echo $(( 100 * (diff_total - diff_idle) / diff_total ))
        fi
      }

      # Pre-command engine that updates environment variables dynamically
      set_starship_telemetry() {
        # 1. Evaluate RAM state
        local ram_info=($(free | awk '/Mem:/ {print $3/1024/1024, int(($3/$2)*100)}'))
        local ram_gb=''${ram_info[1]}
        local ram_pct=''${ram_info[2]}
        
        if [ "$ram_pct" -ge 90 ]; then   export STARSHIP_RAM_COLOR="red"
        elif [ "$ram_pct" -ge 80 ]; then export STARSHIP_RAM_COLOR="yellow"
        else                             export STARSHIP_RAM_COLOR="green"
        fi
        export STARSHIP_RAM_TEXT="$(printf "%.1fGB (%d%%)" "$ram_gb" "$ram_pct")"

        # 2. Evaluate CPU state instantly from file streams
        local cpu_pct=$(awk '/cpu / {print int(100 - ($5*100/($2+$3+$4+$5+$6+$7+$8)))}' /proc/stat)
        
        if [ "$cpu_pct" -ge 90 ]; then   export STARSHIP_CPU_COLOR="red"
        elif [ "$cpu_pct" -ge 80 ]; then export STARSHIP_CPU_COLOR="yellow"
        else                             export STARSHIP_CPU_COLOR="green"
        fi
        export STARSHIP_CPU_TEXT="$cpu_pct%"
      }

      # Append the custom telemetry function right into the Zsh layout draw cycle
      autoload -Uz add-zsh-hook
      add-zsh-hook precmd set_starship_telemetry
    '';
  };

  # 🚀 STARSHIP PROMPT CONFIGURATION
  programs.starship = {
    enable = true;
    enableZshIntegration = true; # Seamlessly hooks into your Zsh shell context

    settings = {
      # Customises the overall visual sequence of your prompt layout
      format = "$directory$git_branch$nix_shell\${custom.cpu_telemetry}\${custom.ram_telemetry}$character";

      # ❄️ NATIVE NIX-SHELL / DEV-SHELL DETECTOR
      nix_shell = {
        disabled = false;
        symbol = "❄️ ";
        style = "bold blue";
        impure_msg = "impure";
        pure_msg = "pure";
        format = "via [$symbol$state]($style) ";
      };

      # ⚡ CPU METRICS
      custom.cpu_telemetry = {
        when = "true";
        command = "echo $STARSHIP_CPU_TEXT";
        format = "[⚡ $output](bold $STARSHIP_CPU_COLOR) ";
      };

      # 🧠 RAM METRICS
      custom.ram_telemetry = {
        when = "true";
        command = "echo $STARSHIP_RAM_TEXT";
        format = "[🧠 $output](bold $STARSHIP_RAM_COLOR) ";
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
