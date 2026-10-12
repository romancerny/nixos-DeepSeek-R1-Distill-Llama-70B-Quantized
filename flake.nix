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

        # Wire up Home Manager modularly within the NixOS system layer
        home-manager.nixosModules.home-manager
        {
          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;
          home-manager.users.roman = import ./home.nix; # Points to your isolated user profile
        }
      ];
    };
  };
}
