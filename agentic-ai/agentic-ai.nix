# Nix derivation for the agentic-ai orchestrator.
#
# Build it directly:
#   nix-build -E 'with import <nixpkgs> {}; callPackage ./agentic-ai.nix {}'
# or via the repo flake (see flake.nix):
#   nix build
#
# Ollama is intentionally NOT part of this package. On NixOS it is expected to
# be provided by the system configuration (services.ollama); the tool only
# talks to its HTTP API. The same applies to llama.cpp: `llama-server` is
# expected on PATH (e.g. pkgs.llama-cpp with cudaSupport) for the GGUF-backed
# model, and the GGUF file itself lives in the executing user's ~/models.
# See docs/nixos-projects.md.
{ lib
, python3Packages
}:

python3Packages.buildPythonApplication {
  pname = "local-agentic-ai";
  version = "0.1.0";
  pyproject = true;

  src = ./.;

  build-system = [ python3Packages.setuptools ];

  # Runtime is Python standard library only (see pyproject.toml).
  dependencies = [ ];

  doCheck = true;
  checkPhase = ''
    runHook preCheck
    # The suite uses plain unittest and ships its own fake Ollama server, so
    # it runs fully offline inside the sandbox.
    PYTHONPATH=src python -m unittest discover -s tests -v
    runHook postCheck
  '';

  meta = with lib; {
    description = "File-backed, single-resident-model agentic project orchestration for local Ollama";
    license = licenses.mit;
    mainProgram = "agentic-ai";
    platforms = platforms.linux;
  };
}
