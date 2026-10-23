# Per-project nix environment template.
#
# Copy this file into a new project as its flake.nix, adjust the two marked
# spots, then enter the environment with:
#
#   nix develop
#
# Full lifecycle (setup, pause, resume across projects): docs/nixos-projects.md
# in the agentic-ai repo.
{
  description = "Development environment for <PROJECT NAME>"; # <-- adjust

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

    # Local checkout of the agentic-ai tool. <-- adjust the path
    # Note: path inputs are pinned by content hash in flake.lock, so after
    # editing the tool itself, run `nix flake update agentic-ai` in this
    # project to pick up the changes.
    agentic-ai.url = "path:/home/roman/_/_/agentic-ai";
  };

  outputs = { nixpkgs, agentic-ai, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        packages = [
          # The orchestrator CLI (`agentic-ai ...`).
          agentic-ai.packages.${system}.agentic-ai

          # Interpreter for the test/build commands in this project's
          # config.json, and for anything the coding agents produce.
          pkgs.python3

          pkgs.git
        ];

        shellHook = ''
          echo "agentic-ai env — preflight: agentic-ai doctor --config config.json"
        '';
      };
    };
}
