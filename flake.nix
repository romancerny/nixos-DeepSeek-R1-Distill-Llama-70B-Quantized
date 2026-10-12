{
  description = "Roman's Secure AI Workstation Flake Configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    
    # 🎨 Pulling in Stylix the modular theming framework used by librephoenix
    stylix.url = "github:danth/stylix";
    stylix.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = { self, nixpkgs, stylix, ... }@inputs: {
    nixosConfigurations.beast-kf = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        stylix.nixosModules.stylix  # Inject global styling mechanics
        ./hardware-configuration.nix
        ./configuration.nix
      ];
    };
  };
}
