{ config, pkgs, ... }:

{
  # 📦 INSTALL TMUXP VIA USER PACKAGES
  home.packages = [
    pkgs.tmuxp
  ];

  # 📟 TMUX PERMANENT CONFIGURATION
  programs.tmux = {
    enable = true;
    shortcut = "b"; 
    baseIndex = 1;
    newSession = true;
    escapeTime = 0;
    
    extraConfig = ''
      # Press F9 to toggle off
      bind -T root F9 \
        set prefix None \;\
        set key-table off \;\
        set status-style "bg=red,fg=white" \;\
        set status-right " [OFF] %H:%M " \;\
        refresh-client -S

      # Press F9 to toggle back on
      bind -T off F9 \
        set -u prefix \;\
        set -u key-table \;\
        set -u status-style \;\
        set -u status-right \;\
        refresh-client -S
    '';
  };

  # 📑 IMMUTABLE TMUXP CLUSTER LAYOUT CONFIGURATION
  home.file.".config/tmuxp/ssh-cluster.yaml".text = ''
    session_name: ssh-cluster
    windows:
      - window_name: ssh-servers
        layout: tiled
        panes:
          - shell_command: ssh roman@u-server-26-04-llms
          - shell_command: ssh roman@u-server-26-04
          - shell_command: ll
          - shell_command: ssh roman@hp-elite-001
  '';

  # 📊 NEW: AI ENGINEERING PERFORMANCE MONITORING METRIC MATRIX
  home.file.".config/tmuxp/perf-monitoring.yaml".text = ''
    session_name: perf-monitoring
    windows:
      - window_name: ai-telemetry
        layout: main-horizontal
        options:
          main-pane-width: 60
        panes:
          - shell_command: btop
          - shell_command: nvtop
          - shell_command: sudo iotop
  '';
}
