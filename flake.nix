{
  description = "Roman's Secure AI Workstation Flake Configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    
    # 🎨 Modular theming framework
    stylix.url = "github:danth/stylix";
    stylix.inputs.nixpkgs.follows = "nixpkgs";

    # 🏠 User profile space configuration management
    home-manager.url = "github:nix-community/home-manager";
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, stylix, home-manager, ... }@inputs: {
    nixosConfigurations.beast-kf = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        stylix.nixosModules.stylix  # Inject global styling mechanics
        ./hardware-configuration.nix
        ./configuration.nix

        # Add this block here to apply the CUDA overlay across the flake
        {
          nixpkgs.overlays = [
            (final: prev: {
              llama-cpp = prev.llama-cpp.override { cudaSupport = true; };
            })
          ];
        }

        # Wire up Home Manager modularly within the NixOS system layer
        home-manager.nixosModules.home-manager
        {
          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;

          # 👥 DUAL-USER INDEPENDENT HOME-MANAGER ATTACHMENT
          home-manager.users = {
            # 1. Roman gets the full desktop environment, shell plugins, AND tmux
            roman.imports = [ ./home.nix ];
            
            # 2. AI-Agent gets a lightweight home container mapping ONLY your shared tmux setup
            # 🌟 CHANGE THIS LINE: Add '{ pkgs }: ' before the opening block to bring pkgs into scope!
            ai-agent = { pkgs }: { 
              home.username = "ai-agent";
              home.homeDirectory = "/home/ai-agent";
              home.stateVersion = "24.11";
              
              imports = [ ./tmux.nix ];

              # 📦 Exposes the CUDA-overridden llama-cpp package cleanly into the path
              home.packages = [
                pkgs.llama-cpp
              ];
            };
          };
        }
      ];
    };
  };
}
