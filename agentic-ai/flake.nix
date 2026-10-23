{
  description = "File-backed, single-resident-model agentic project orchestration for local Ollama";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system} system);
    in
    {
      packages = forAllSystems (pkgs: system: {
        agentic-ai = pkgs.callPackage ./agentic-ai.nix { };
        default = self.packages.${system}.agentic-ai;
      });

      # Shell for hacking on the tool itself. Per-project shells should use
      # examples/project/flake.nix instead (see docs/nixos-projects.md).
      devShells = forAllSystems (pkgs: system: {
        default = pkgs.mkShell {
          packages = [
            self.packages.${system}.agentic-ai
            pkgs.python3
            pkgs.git
          ];
        };
      });
    };
}
