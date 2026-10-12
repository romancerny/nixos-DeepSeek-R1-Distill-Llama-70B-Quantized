{ config, pkgs, ... }:

{
  home.username = "roman";
  home.homeDirectory = "/home/roman";
  home.stateVersion = "24.11"; 

  programs.home-manager.enable = true;

  # WezTerm managed perfectly inside user environment parameters
  programs.wezterm = {
    enable = true;
    extraConfig = ''
      local wezterm = require 'wezterm'
      local config = wezterm.config_builder()
  
      -- CRITICAL FIX: Forces XWayland to prevent the tiny, unresizable window glitch on Wayland
      config.enable_wayland = false
      config.front_end = "WebGpu"
  
      -- Aesthetic and functional configurations matching the librephoenix setup
      config.hide_tab_bar_if_only_one_tab = true
      config.window_background_opacity = 0.9
      config.window_decorations = "RESIZE"
  
      return config
    '';
  };

  # 🎨 USER-LEVEL THEME TARGETS
  # Stylix implicitly mirrors your global configurations here, allowing us to explicitly toggle user apps!
  stylix.targets.wezterm.enable = true; 
}
