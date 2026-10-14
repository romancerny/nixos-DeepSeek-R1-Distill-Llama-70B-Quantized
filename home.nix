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

    # Lightweight prompt integration using default frameworks
    oh-my-zsh = {
      enable = true;
      plugins = [ "git" "sudo" ];
      theme = "robbyrussell";
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
