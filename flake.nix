{
  inputs = {
    nixpkgs = {
      url = "github:NixOS/nixpkgs/nixos-unstable";
    };
  };

  outputs = {
    self,
    nixpkgs,
  }: let
    forAllSystems = nixpkgs.lib.genAttrs nixpkgs.lib.systems.flakeExposed;
  in {
    formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.alejandra);

    packages = forAllSystems (system: let
      pkgs = nixpkgs.legacyPackages.${system};
    in {
      # https://nixos.org/manual/nixpkgs/stable/#python
      default = pkgs.python3Packages.buildPythonApplication {
        pname = "git-syndicate";
        version = "0.0.1";
        pyproject = true;

        src = ./.;

        build-system = [
          pkgs.python3Packages.hatchling
        ];

        dependencies = [
          pkgs.git
          pkgs.openssh
        ];
      };
    });

    nixosModules = {
      default = {
        config,
        lib,
        pkgs,
        ...
      }: let
        cfg = config.services.git-syndicate;
      in {
        options.services.git-syndicate = {
          enable = lib.mkEnableOption "git-syndicate service";
          environmentFile = lib.mkOption {
            type = lib.types.path;
            description = ''
              Environment file as defined in {manpage}`systemd.exec(5)`.

              See `main.py` for available options.
            '';
          };
        };

        config = lib.mkIf cfg.enable {
          systemd.services.git-syndicate = {
            serviceConfig = {
              Type = "oneshot";
              ExecStart = "${self.packages.${pkgs.stdenv.hostPlatform.system}.default}/bin/git-syndicate";
              DynamicUser = true;
              StateDirectory = "git-syndicate";
              Environment = [
                # Required to make print()s show up in the syslog
                "PYTHONUNBUFFERED=1"
              ];
              EnvironmentFile = cfg.environmentFile;
            };
          };
          systemd.timers.git-syndicate = {
            wantedBy = ["timers.target"];
            timerConfig = {
              OnBootSec = "5m";
              OnUnitActiveSec = "4h";
              RandomizedDelaySec = "15m";
              Unit = "git-syndicate.service";
            };
          };
        };
      };
    };
  };
}
